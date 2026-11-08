#!/usr/bin/env python3
"""Write our served articles as one markdown file per law, the W2 upload set, and its upload-manifest.json.

    python -I make_w2_corpus.py --canvas "<Walid's indexing-pipeline canvas>.json" [--out DIR] [--replace]
        [--harness DIR] [--baseline eval-final.json | --no-baseline]

Spec: .hq/docs/specs/spec-rag-system.md, «Owner decision 2026-11-08: W2 first, run here, with a pre-registered
rule», the line «Pinned with the rule, before any parse». File shape `slug-title-served-v1`: one file per law,
named <registry slug>.md, holding one «# <registry title>» line, then for each article «### المادة N[ suffix]»
and its served text byte for byte (corrections applied; inner «## الباب/الفصل» captions kept as served). The
exact bytes are pinned in README.md («## make_w2_corpus.py»).

The served text is what legal_search.ingest stores (ingest.py:45-77, db.py:229): the law's shards parsed in file
order, the registry's corrections applied, the counts checked. ingest itself needs psycopg, so its checks are
repeated here with the stdlib-only modules (corpus, corrections, registry, normalize).

The canvas is untrusted data: it is read with json only, and only the TitleChunker's level regexes and settings
are used. Compiling its patterns can at worst be slow (catastrophic backtracking), never run code. They are
matched the way RAGFlow v0.27.3 matches them (rag/flow/chunker/title_chunker/common.py:334-340, :370), so the
checks below say what RAGFlow's chunker will see. Every check runs before anything is written, except the
read-back, which parses the written files with legal_search's own shard parser.

Python standard library only. Writes nothing outside --out; prints counts and hashes, never article text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace as with_changes
from pathlib import Path

TOOL = Path(__file__).resolve().parent
HARNESS = TOOL.parents[1]
WORKSPACE = TOOL.parents[2]
# python -I leaves the script's folder off sys.path; this is a fixed path, never the current directory.
sys.path[:0] = [str(HARNESS / 'services' / 'legal-search' / 'src')]

from legal_search import corpus as ls_corpus  # noqa: E402
from legal_search import corrections as ls_corrections  # noqa: E402
from legal_search import normalize as ls_normalize  # noqa: E402
from legal_search import registry as ls_registry  # noqa: E402
from legal_search.corpus import Article, parse_law, parse_shard  # noqa: E402
from legal_search.corrections import apply_corrections, load_corrections  # noqa: E402
from legal_search.normalize import normalize  # noqa: E402
from legal_search.registry import Law, directory_counts, load_registry  # noqa: E402

FILE_SHAPE = 'slug-title-served-v1'
MANIFEST = 'upload-manifest.json'
DEFAULT_OUT = WORKSPACE / '.hq' / 'scratch' / 'w2-run' / 'in'
DEFAULT_BASELINE = WORKSPACE / '.hq' / 'docs' / 'audits' / 'librechat-platform' / 'p3-evidence' / 'eval-final.json'
CORPUS_DIR = Path('jordanian-law') / 'references' / 'القوانين-الأردنية'
REGISTRY = Path('content') / 'corpus' / 'laws.json'
CORRECTIONS = Path('content') / 'corpus' / 'corrections.json'

# The canvas's level family, by 1-based level. Article headings must resolve to ARTICLE_LEVEL. An article body may
# hold lines at CAPTION_LEVEL only (the served «## الباب/الفصل» captions, kept by the owner's decision); the title
# line may sit at TITLE_LEVEL or at none.
TITLE_LEVEL, CAPTION_LEVEL, ARTICLE_LEVEL = 1, 2, 3
BODY_LEVEL = sys.maxsize - 1  # common.py:47
NOT_BULLET = (r'0', r'[0-9]+ +[0-9~个只-]', r'[0-9]+\.{2,}', r'[0-9]+(\.[0-9]+){2,}[的中]')  # rag/nlp/__init__.py:366-368
SLUG = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')

# What RAGFlow's markdown path would act on, so none of it may appear (checked on each whole file):
HAZARDS = (
    # rag/app/naive.py:957-1060 fetches markdown and HTML image sources, over http(s) or from a local path. Its
    # html_img_re (:959) takes «src=» anywhere, with no word boundary and in any case; this is a superset of it.
    ('a markdown image', re.compile(r'!\[')),
    ('an HTML image or src attribute', re.compile(r'(?i)<img\b|src\s*=')),
    ('a URL', re.compile(r'(?i)\b[a-z][a-z0-9+.-]*://|\bwww\.|\b(?:data|file|javascript|vbscript|mailto):')),
    ('a markdown link', re.compile(r'\[[^\]\n]*\]\([^)\n]*\)|^[ \t]{0,3}\[[^\]\n]+\]:', re.MULTILINE)),
    # deepdoc/parser/markdown_parser.py:100-113 rewrites every such tag up to the next «>», across lines.
    ('an HTML tag RAGFlow rewrites', re.compile(r'<(?:table|td|tr|th|tbody|thead|div)[^>]*>', re.IGNORECASE)),
    ('an HTML table', re.compile(r'(?i)<table(?:\s|>)')),  # common.py:314, markdown_parser.py:115
    ('a code fence', re.compile(r'^[ \t]*(?:`{3,}|~{3,})', re.MULTILINE)),  # common.py:314, markdown_parser.py:45-49
    ('a pipe (markdown table pass)', re.compile(r'\|')),  # markdown_parser.py:74 runs its table passes on any «|»
    ('a carriage return', re.compile('\r')),
    ('a byte order mark', re.compile('﻿')),
    ('a control character', re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')),
)
ANGLE = re.compile('[<>]')  # recorded, not refused: served fragments of HTML or script, kept byte for byte


class Refused(ValueError):
    """An input or the output folder fails a check; nothing (more) is written."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_of(article: Article) -> str:
    """The spec's article key, <slug>:<number>[:<suffix>] (spec «What any replacement must preserve», item 5)."""
    return f'{article.law_slug}:{article.number}' + (f':{article.suffix}' if article.suffix else '')


# The canvas ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Canvas:
    name: str
    sha256: str
    size: int
    component: str
    method: str
    hierarchy: int
    chunk_token_cap: object
    patterns: tuple  # the level family, as strings, empty ones dropped (common.py:370)
    family: tuple  # the same, compiled


def load_canvas(path: Path) -> Canvas:
    """The TitleChunker's level family and settings from the pipeline DSL's `components` (what the canvas runs;
    graph.nodes[].data.form is the editor's copy)."""
    try:
        raw = path.read_bytes()
        dsl = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Refused(f'canvas: cannot read it as UTF-8 JSON: {error.__class__.__name__}') from error
    components = dsl.get('components') if isinstance(dsl, dict) else None
    if not isinstance(components, dict):
        raise Refused('canvas: no `components` object (expected a bare pipeline DSL)')
    found = [(cid, c) for cid, c in components.items()
             if isinstance(c, dict) and isinstance(c.get('obj'), dict) and c['obj'].get('component_name') == 'TitleChunker']
    if len(found) != 1:
        raise Refused(f'canvas: {len(found)} TitleChunker components, expected exactly 1')
    cid, component = found[0]
    params = component['obj'].get('params')
    if not isinstance(params, dict):
        raise Refused('canvas: the TitleChunker has no params')
    method = params.get('method')
    if method != 'group':
        raise Refused(f'canvas: TitleChunker method {method!r}; this tool models the group method only')
    levels = params.get('levels')
    if not (isinstance(levels, list) and len(levels) == 1 and isinstance(levels[0], list)
            and all(isinstance(p, str) for p in levels[0])):
        # With several families RAGFlow keeps the one matching most lines (common.py:343-370); not modelled here.
        raise Refused('canvas: TitleChunker levels must be exactly one family of regex strings')
    patterns = tuple(p for p in levels[0] if p)
    if len(patterns) < ARTICLE_LEVEL:
        raise Refused(f'canvas: {len(patterns)} levels, fewer than the article level {ARTICLE_LEVEL}')
    try:
        family = tuple(re.compile(p) for p in patterns)
        hierarchy = int(params.get('hierarchy'))
    except (re.error, TypeError, ValueError) as error:
        raise Refused(f'canvas: bad TitleChunker setting: {error}') from error
    return Canvas(path.name, sha256_bytes(raw), len(raw), cid, method, hierarchy, params.get('chunk_token_cap'),
                  patterns, family)


def not_bullet(line: str) -> bool:
    return any(re.match(p, line) for p in NOT_BULLET)


def level_of(line: str, family: tuple) -> int | None:
    """The 1-based level RAGFlow gives a line, or None: the first pattern that matches (common.py:334-340)."""
    stripped = line.strip()
    for level, pattern in enumerate(family, start=1):
        if pattern.match(stripped) and not not_bullet(stripped):
            return level
    return None


def plain_matches(line: str, family: tuple) -> set:
    """Every level whose pattern matches the stripped line, ignoring order and not_bullet (the strict test)."""
    stripped = line.strip()
    return {level for level, pattern in enumerate(family, start=1) if pattern.match(stripped)}


def resolve_target_level(levels: list, hierarchy: int) -> int | None:
    """common.py:514-521, used by the group method when hierarchy > 0 (group_chunker.py:37-41)."""
    title_levels = sorted({level for level in levels if 0 < level < BODY_LEVEL})
    if not title_levels:
        return None
    return title_levels[min(max(int(hierarchy), 1), len(title_levels)) - 1]


# The library, as legal_search serves it --------------------------------------------------------------------------

def label(number: int, suffix: str) -> str:
    return f'المادة {number}' + (f' {suffix}' if suffix else '')


def load_library(harness: Path) -> list:
    """[(law, [article, ...])] in registry order, articles in file order with corrections applied, checked as
    legal_search.ingest.prepare and _law_articles do (ingest.py:45-77)."""
    corpus = harness / CORPUS_DIR
    try:
        laws = load_registry(harness / REGISTRY)
        corrections = load_corrections(harness / CORRECTIONS)
        counts = directory_counts(corpus / 'law-directory.md')
    except (OSError, ValueError, KeyError, TypeError) as error:  # RegistryError and CorrectionError are ValueErrors
        raise Refused(f'library: {error}') from error
    unknown = sorted({c.law for c in corrections} - {law.slug for law in laws})
    if unknown:
        raise Refused(f'library: corrections name laws not in the registry: {", ".join(unknown)}')
    library = []
    for law in laws:
        if not SLUG.match(law.slug):
            raise Refused(f'library: slug {law.slug!r} is not a safe file name')
        title = law.title
        if not title or title != title.strip() or '\n' in title or '\r' in title or title.startswith('#'):
            raise Refused(f'{law.slug}: the registry title cannot stand on one «# » line')
        directory = corpus / law.folder
        if not (directory / 'sections').is_dir():
            raise Refused(f'{law.slug}: folder not found: {law.folder}')
        if law.folder not in counts:
            raise Refused(f'{law.slug}: folder {law.folder} is not listed in law-directory.md')
        try:
            parsed = [with_changes(a, law_title=law.title) for a in parse_law(directory, law.slug)]
            articles = apply_corrections(parsed, [c for c in corrections if c.law == law.slug])
        except (OSError, ValueError) as error:  # CorrectionError is a ValueError
            raise Refused(f'{law.slug}: {error}') from error
        keys = Counter((a.number, a.suffix) for a in articles)
        duplicates = sorted(k for k, n in keys.items() if n > 1)
        if duplicates:
            raise Refused(f'{law.slug}: duplicate article {label(*duplicates[0])}')
        present = [g for g in law.known_gaps if (g.number, g.suffix) in keys]
        if present:
            raise Refused(f'{law.slug}: known gap {label(present[0].number, present[0].suffix)} is present')
        expected = counts[law.folder] - len(law.known_gaps)
        if len(articles) != expected:
            raise Refused(f'{law.slug}: {len(articles)} articles, expected {expected} '
                          f'(directory {counts[law.folder]} minus {len(law.known_gaps)} known gaps)')
        library.append((law, articles))
    return library


def corpus_sha256(library: list) -> str:
    """As legal_search.evaluate.corpus_digest (evaluate.py:153-159) and score_w1.corpus_sha256: each article's key
    and normalised text, in key order. Equal to eval-final.json's run.corpus_sha256 on the same library."""
    rows = sorted((a.law_slug, a.number, a.suffix, a.text) for _, articles in library for a in articles)
    digest = hashlib.sha256()
    for slug, number, suffix, text in rows:
        digest.update(json.dumps([slug, number, suffix, normalize(text)], ensure_ascii=False).encode('utf-8'))
    return digest.hexdigest()


def served_text_sha256(library: list) -> str:
    """The same rows with the text as served (not normalised): a change of any byte changes it."""
    rows = sorted((a.law_slug, a.number, a.suffix, a.text) for _, articles in library for a in articles)
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(list(row), ensure_ascii=False).encode('utf-8'))
    return digest.hexdigest()


# The files -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rendered:
    law: Law
    articles: list
    name: str
    data: bytes
    lines: list  # (role, article index or None, line text); role is title, heading, body or blank


def render(law: Law, articles: list) -> Rendered:
    """«# <title>», a blank line, then per article «### <label>», a blank line, its text; articles separated by
    one blank line; LF line ends, a final LF, UTF-8 without BOM."""
    lines = [('title', None, f'# {law.title}'), ('blank', None, '')]
    for index, article in enumerate(articles):
        if index:
            lines.append(('blank', None, ''))
        lines.append(('heading', index, f'### {article.label}'))
        lines.append(('blank', None, ''))
        lines.extend(('body' if line.strip() else 'blank', index, line) for line in article.text.split('\n'))
    text = '\n'.join(line for _, _, line in lines) + '\n'
    return Rendered(law, articles, f'{law.slug}.md', text.encode('utf-8'), lines)


def check(rendered: Rendered, canvas: Canvas) -> dict:
    """Refuse what would make RAGFlow chunk or fetch other than the pinned shape; return the file's facts."""
    name, family, articles = rendered.name, canvas.family, rendered.articles

    def where(index):
        return f'{name} {key_of(articles[index])}' if index is not None else f'{name} title line'

    try:
        text = rendered.data.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise Refused(f'{name}: not UTF-8: {error}') from error
    for index, article in enumerate(articles):
        # The shard parser's normal form (corpus.py:55, :73): what a replace correction could break. Text outside
        # it would not read back byte for byte, so it is refused before anything is written.
        body = article.text
        if not body or '\n\n\n' in body or any(line != line.strip() for line in body.split('\n')):
            raise Refused(f'{where(index)}: the served text is empty, or has a blank run or a line with outer '
                          f'whitespace; the file shape cannot hold it byte for byte')
    if rendered.data.startswith(b'\xef\xbb\xbf') or not text.endswith('\n') or text.endswith('\n\n'):
        raise Refused(f'{name}: the file must start without a BOM and end with exactly one LF')
    for what, pattern in HAZARDS:
        match = pattern.search(text)
        if match:
            line_no = text.count('\n', 0, match.start())
            raise Refused(f'{where(rendered.lines[line_no][1])}: holds {what} (file line {line_no + 1})')
    levels, headings, captions, title_level = [], 0, 0, None
    caption_flags = {}  # article index -> for each non-blank body line in order, whether it is a caption line
    for role, index, line in rendered.lines:
        if role == 'blank':
            continue
        level, plain = level_of(line, family), plain_matches(line, family)
        if role == 'title':
            if level not in (None, TITLE_LEVEL) or plain - {TITLE_LEVEL}:
                raise Refused(f'{where(None)}: matches level {sorted(plain)}, not the title level or none')
            title_level = level
        elif role == 'heading':
            headings += 1
            if level != ARTICLE_LEVEL or ARTICLE_LEVEL not in plain:
                raise Refused(f'{where(index)}: heading resolves to level {level}, not the article level '
                              f'{ARTICLE_LEVEL} of the canvas')
        else:
            forbidden = plain - {CAPTION_LEVEL}
            if forbidden:
                raise Refused(f'{where(index)}: a body line matches canvas level {sorted(forbidden)}')
            captions += level == CAPTION_LEVEL
            caption_flags.setdefault(index, []).append(level == CAPTION_LEVEL)
        levels.append(level if level is not None else BODY_LEVEL)
    if headings != len(articles):
        raise Refused(f'{name}: {headings} heading lines for {len(articles)} articles')
    target = resolve_target_level(levels, canvas.hierarchy)
    if target != ARTICLE_LEVEL:
        raise Refused(f'{name}: the chunker would cut at level {target}, not at the article level {ARTICLE_LEVEL}')
    # A caption line resolves to level 2 <= the target 3, so it opens a section of its own (group_chunker.py:31) and
    # leaves its article's section: a trailing one joins the next article's chunk unless the article's group is under
    # MIN_GROUP_TOKENS (:22, :91); an inner one also takes the body text after it. Recorded, not refused (the owner's
    # shape keeps the captions as served).
    tail = [key_of(articles[i]) for i, flags in caption_flags.items() if flags[-1]]
    inner = [key_of(articles[i]) for i, flags in caption_flags.items()
             if True in flags and not all(flags[flags.index(True):])]
    return {
        'name': name, 'law': rendered.law.slug, 'title': rendered.law.title,
        'sha256': sha256_bytes(rendered.data), 'bytes': len(rendered.data),
        'articles': len(articles), 'lines': len(rendered.lines), 'title_level': title_level,
        'caption_lines': captions, 'target_level': target, 'keys': [key_of(a) for a in articles],
        'caption_tail_articles': tail, 'caption_inner_articles': inner,
    }


def read_back(path: Path, rendered: Rendered) -> None:
    """The written file holds the rendered bytes, and legal_search's own shard parser reads back exactly the served
    articles, in order: each served article appears once, with its text byte for byte."""
    if path.read_bytes() != rendered.data:
        raise Refused(f'{rendered.name}: the bytes on disk differ from the bytes written')
    parsed = [(a.number, a.suffix, a.text) for a in parse_shard(path, rendered.law.slug)]
    served = [(a.number, a.suffix, a.text) for a in rendered.articles]
    if parsed != served:
        diff = next((i for i, (p, s) in enumerate(zip(parsed, served)) if p != s), min(len(parsed), len(served)))
        raise Refused(f'{rendered.name}: parsed back {len(parsed)} articles for {len(served)} served; first '
                      f'difference at position {diff + 1}')


# The output folder -----------------------------------------------------------------------------------------------

def owned(entry: Path) -> bool:
    return entry.is_file() and not entry.is_symlink() and (entry.suffix == '.md' or entry.name == MANIFEST)


def prepare_out(out: Path, replace: bool) -> list:
    """The files a --replace run removes; refuses a non-empty folder without --replace, and any entry this tool
    does not write, even with it."""
    if out.exists() and not out.is_dir():
        raise Refused(f'--out is not a folder: {out}')
    entries = sorted(out.iterdir()) if out.is_dir() else []
    if entries and not replace:
        raise Refused(f'--out is not empty ({len(entries)} entries); pass --replace to overwrite this tool\'s files')
    foreign = [e.name for e in entries if not owned(e)]
    if foreign:
        raise Refused(f'--out holds entries this tool does not write, left alone: {", ".join(foreign[:5])}')
    return entries


def module_sha256(module) -> str:
    return sha256_bytes(Path(module.__file__).read_bytes())


def baseline_corpus(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding='utf-8'))['run']['corpus_sha256']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused(f'baseline: cannot read run.corpus_sha256 from {path.name}') from error


def build(canvas_path: Path, out: Path, *, replace: bool = False, harness: Path = HARNESS,
          baseline: Path | None = DEFAULT_BASELINE) -> dict:
    """Check everything, then write the files and the manifest. Returns the manifest and its sha256."""
    stale = prepare_out(out, replace)
    canvas = load_canvas(canvas_path)
    library = load_library(harness)
    corpus_sha = corpus_sha256(library)
    base = None
    if baseline is not None:
        recorded = baseline_corpus(baseline)
        if recorded != corpus_sha:
            raise Refused(f'the library\'s corpus sha256 {corpus_sha[:12]} is not the baseline\'s {recorded[:12]} '
                          f'({baseline.name}): W2 and T-B2 would not index the same text')
        base = {'file': baseline.name, 'corpus_sha256': recorded, 'match': True}
    rendered = [render(law, articles) for law, articles in library]
    facts = [check(r, canvas) for r in rendered]
    angle = [key_of(a) for _, articles in library for a in articles if ANGLE.search(a.text)]
    caption_tail = [key for f in facts for key in f.pop('caption_tail_articles')]
    caption_inner = [key for f in facts for key in f.pop('caption_inner_articles')]

    out.mkdir(parents=True, exist_ok=True)
    for entry in stale:
        entry.unlink()
    written = []
    try:
        for r in rendered:
            path = out / r.name
            path.write_bytes(r.data)
            written.append(path)
        for r in rendered:
            read_back(out / r.name, r)
    except (Refused, OSError):
        for path in written:
            path.unlink(missing_ok=True)
        raise

    upload_set = ''.join(f'{f["name"]} {f["sha256"]}\n' for f in sorted(facts, key=lambda f: f['name']))
    manifest = {
        'w2_upload': 1,
        'file_shape': FILE_SHAPE,
        'generator': {'name': Path(__file__).name, 'sha256': sha256_bytes(Path(__file__).read_bytes())},
        'legal_search': {m.__name__.rsplit('.', 1)[-1] + '.py': module_sha256(m)
                         for m in (ls_corpus, ls_corrections, ls_normalize, ls_registry)},
        'inputs': {p.name: sha256_bytes((harness / p).read_bytes())
                   for p in (REGISTRY, CORRECTIONS, CORPUS_DIR / 'law-directory.md')},
        'canvas': {'name': canvas.name, 'sha256': canvas.sha256, 'bytes': canvas.size,
                   'title_chunker': canvas.component, 'method': canvas.method, 'hierarchy': canvas.hierarchy,
                   'chunk_token_cap': canvas.chunk_token_cap, 'levels': list(canvas.patterns),
                   'article_level': ARTICLE_LEVEL, 'caption_level': CAPTION_LEVEL},
        'corpus_sha256': corpus_sha,
        'served_text_sha256': served_text_sha256(library),
        'baseline': base,
        'upload_set_sha256': sha256_bytes(upload_set.encode('utf-8')),
        'totals': {
            'files': len(facts),
            'articles': sum(f['articles'] for f in facts),
            'bytes': sum(f['bytes'] for f in facts),
            'caption_lines': sum(f['caption_lines'] for f in facts),
            'title_lines_at_level_1': sum(f['title_level'] == TITLE_LEVEL for f in facts),
            'known_gaps': [f'{law.slug}:{g.number}' + (f':{g.suffix}' if g.suffix else '')
                           for law, _ in library for g in law.known_gaps],
        },
        'angle_bracket_articles': angle,
        'caption_tail_articles': caption_tail,
        'caption_inner_articles': caption_inner,
        'files': facts,
    }
    data = (json.dumps(manifest, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    (out / MANIFEST).write_bytes(data)
    return {'manifest': manifest, 'manifest_sha256': sha256_bytes(data)}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument('--canvas', type=Path, required=True, help='the indexing-pipeline canvas JSON (read as data)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT, help=f'default {DEFAULT_OUT}')
    parser.add_argument('--replace', action='store_true', help='overwrite this tool\'s files in a non-empty --out')
    parser.add_argument('--harness', type=Path, default=HARNESS, help='the AI Harness checkout holding the corpus')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE,
                       help='eval-final.json whose run.corpus_sha256 the library must equal')
    group.add_argument('--no-baseline', action='store_true', help='skip that check (recorded as null)')
    args = parser.parse_args(argv)
    try:
        result = build(args.canvas, args.out, replace=args.replace, harness=args.harness,
                       baseline=None if args.no_baseline else args.baseline)
    except Refused as error:
        print(f'refused: {error}', file=sys.stderr)
        return 2
    manifest = result['manifest']
    for f in manifest['files']:
        print(f'{f["name"]}: {f["articles"]} articles, {f["bytes"]} bytes, title level {f["title_level"]}, '
              f'{f["caption_lines"]} caption lines, target level {f["target_level"]}')
    totals = manifest['totals']
    print(f'{totals["files"]} files, {totals["articles"]} articles, {totals["bytes"]} bytes, '
          f'{totals["caption_lines"]} caption lines, {totals["title_lines_at_level_1"]} title lines at level 1')
    print(f'corpus sha256 {manifest["corpus_sha256"]}'
          + (' (equals the baseline)' if manifest['baseline'] else ' (no baseline check)'))
    print(f'served text sha256 {manifest["served_text_sha256"]}')
    print(f'upload set sha256 {manifest["upload_set_sha256"]}')
    print(f'canvas sha256 {manifest["canvas"]["sha256"]}')
    print(f'generator sha256 {manifest["generator"]["sha256"]}')
    print(f'articles holding < or >, kept as served: {", ".join(manifest["angle_bracket_articles"]) or "none"}')
    print(f'articles ending in caption lines: {len(manifest["caption_tail_articles"])}; with a caption line before '
          f'more of their text: {len(manifest["caption_inner_articles"])}')
    print(f'{MANIFEST} sha256 {result["manifest_sha256"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
