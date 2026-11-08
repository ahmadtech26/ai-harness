"""make_w2_corpus.py: the pinned file shape, the counts, the canvas checks, the hazards, determinism, the out folder.

Most tests build a small invented library (registry, law-directory.md, shards, corrections) and a fixture canvas in a
temporary folder. The tests marked «real data» read our library (and, if present, Walid's canvas and eval-final.json)
and write only to temporary folders."""

import contextlib
import dataclasses
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import make_w2_corpus as m
from legal_search import corpus as ls_corpus
from legal_search import corrections as ls_corrections
from legal_search import normalize as ls_normalize
from legal_search import registry as ls_registry
from legal_search.corpus import parse_law
from legal_search.corrections import apply_corrections, load_corrections
from legal_search.normalize import normalize
from legal_search.registry import directory_counts, load_registry

# His four level regexes, retyped here only (the tool reads them from the canvas); test_real_canvas compares them.
LEVELS = [
    '^\\s*#\\s+قانون\\s+.+$',
    '^\\s*##\\s+(?:الباب|الفصل)\\s+.+$',
    '^\\s*###\\s+(?:المادة\\s*\\(?[0-9٠-٩]+\\)?(?:\\s+مكرر(?:ة)?)?|نص المادة مكرر)(?:\\s|:|$).*$',
    '^####[^#]',
]
REAL_CANVAS = m.WORKSPACE / '.hq' / 'scratch' / 'inbox-evidence-law-2026-11-07' / 'اقرأ – فهرسة التشريعات القانونية.json'
REAL_LIBRARY = (m.HARNESS / m.REGISTRY).is_file() and (m.HARNESS / m.CORPUS_DIR / 'law-directory.md').is_file()

LEASE_SHARD = """---
parent_law: قانون الإيجار
source: fixture
---

# قانون الإيجار

### المادة 1

يسمى هذا القانون قانون الإيجار.

### المادة 2 — يلتزم المؤجر بتسليم العين المؤجرة.
وتكون العين صالحة للانتفاع.

---

### المادة 2 مكرر

يلتزم المستأجر بدفع الأجرة.

ويكون الدفع في موعده.
## الباب الثاني أحكام ختامية
"""
CIVIL_SHARD = """---
parent_law: القانون المدني
source: fixture
---

### المادة 1

ينعقد العقد بمجرد ارتباط الإيجاب بالقبول.

### المادة 2

ملغاة

### المادة 3

### المادة 4

لا ضرر ولا ضرار.
"""


def canvas_dsl(levels=None, method='group', hierarchy=3, families=None, chunkers=1) -> dict:
    components = {'File': {'obj': {'component_name': 'File', 'params': {}}, 'downstream': [], 'upstream': []}}
    for n in range(chunkers):
        components[f'TitleChunker:Fixture{n}'] = {'obj': {'component_name': 'TitleChunker', 'params': {
            'method': method, 'hierarchy': hierarchy, 'chunk_token_cap': 8000, 'include_heading_content': True,
            'levels': families if families is not None else [levels or LEVELS]}}}
    return {'components': components, 'graph': {'nodes': [], 'edges': []}}


class Fixture:
    """A temporary harness: two laws (civil has a known gap at 3, whose heading has no text), a canvas, an out path."""

    def __init__(self, root: Path, *, lease=LEASE_SHARD, civil=CIVIL_SHARD, corrections=(), lease_count=3,
                 civil_count=4, canvas=None):
        self.root = root
        self.harness = root / 'harness'
        corpus = self.harness / m.CORPUS_DIR
        for folder, shard in (('قانون-الإيجار', lease), ('المدني', civil)):
            (corpus / folder / 'sections').mkdir(parents=True)
            (corpus / folder / 'sections' / '00-المواد.md').write_bytes(shard.encode('utf-8'))
        (corpus / 'law-directory.md').write_text(
            '| القانون | المجلد | المواد |\n|---|---|---|\n'
            f'| الإيجار | `قانون-الإيجار` | {lease_count} |\n| المدني | `المدني` | {civil_count} |\n', encoding='utf-8')
        registry = {'laws': [
            {'slug': 'lease-law', 'title': 'قانون الإيجار', 'folder': 'قانون-الإيجار'},
            {'slug': 'civil', 'title': 'القانون المدني', 'folder': 'المدني',
             'known_gaps': [{'number': 3, 'reason': 'no text'}]},
        ]}
        (self.harness / m.REGISTRY).parent.mkdir(parents=True)
        (self.harness / m.REGISTRY).write_text(json.dumps(registry, ensure_ascii=False), encoding='utf-8')
        (self.harness / m.CORRECTIONS).write_text(
            json.dumps({'corrections': [{'reason': 'r', 'source': 's', **c} for c in corrections]},
                       ensure_ascii=False), encoding='utf-8')
        self.canvas = root / 'canvas.json'
        self.canvas.write_text(json.dumps(canvas or canvas_dsl(), ensure_ascii=False), encoding='utf-8')
        self.out = root / 'out'

    def edit_registry(self, index: int, **changes):
        path = self.harness / m.REGISTRY
        registry = json.loads(path.read_text(encoding='utf-8'))
        registry['laws'][index].update(changes)
        path.write_text(json.dumps(registry, ensure_ascii=False), encoding='utf-8')

    def build(self, out=None, **kwargs):
        kwargs.setdefault('baseline', None)
        return m.build(self.canvas, out or self.out, harness=self.harness, **kwargs)

    def main(self, *extra, out=None):
        argv = ['--canvas', str(self.canvas), '--out', str(out or self.out), '--harness', str(self.harness),
                '--no-baseline', *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = m.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, **kwargs) -> Fixture:
        return Fixture(self.root, **kwargs)

    def refused(self, fixture: Fixture, needle: str):
        with self.assertRaises(m.Refused) as caught:
            fixture.build()
        self.assertIn(needle, str(caught.exception))
        self.assertFalse(any(fixture.out.glob('*')) if fixture.out.exists() else False, 'nothing may stay written')
        return str(caught.exception)


class Shape(Base):
    def test_exact_bytes(self):
        f = self.fixture()
        f.build()
        self.assertEqual(sorted(p.name for p in f.out.iterdir()), ['civil.md', 'lease-law.md', 'upload-manifest.json'])
        self.assertEqual((f.out / 'lease-law.md').read_bytes(), (
            '# قانون الإيجار\n'
            '\n'
            '### المادة 1\n'
            '\n'
            'يسمى هذا القانون قانون الإيجار.\n'
            '\n'
            '### المادة 2\n'
            '\n'
            'يلتزم المؤجر بتسليم العين المؤجرة.\n'
            'وتكون العين صالحة للانتفاع.\n'
            '\n'
            '### المادة 2 مكرر\n'
            '\n'
            'يلتزم المستأجر بدفع الأجرة.\n'
            '\n'
            'ويكون الدفع في موعده.\n'
            '## الباب الثاني أحكام ختامية\n').encode('utf-8'))
        self.assertEqual((f.out / 'civil.md').read_bytes(), (
            '# القانون المدني\n\n### المادة 1\n\nينعقد العقد بمجرد ارتباط الإيجاب بالقبول.\n\n'
            '### المادة 2\n\nملغاة\n\n### المادة 4\n\nلا ضرر ولا ضرار.\n').encode('utf-8'))

    def test_served_text_byte_for_byte_and_captions_kept(self):
        f = self.fixture()
        manifest = f.build()['manifest']
        law = load_registry(f.harness / m.REGISTRY)[0]
        served = parse_law(f.harness / m.CORPUS_DIR / law.folder, law.slug)
        data = (f.out / 'lease-law.md').read_text(encoding='utf-8')
        for article in served:
            self.assertEqual(data.count(f'### {article.label}\n\n{article.text}\n'), 1)
        lease = manifest['files'][0]
        self.assertEqual((lease['caption_lines'], lease['title_level'], lease['target_level']), (1, 1, 3))
        civil = manifest['files'][1]
        self.assertEqual((civil['caption_lines'], civil['title_level'], civil['target_level']), (0, None, 3))

    def test_no_bom_lf_only(self):
        f = self.fixture()
        f.build()
        for path in f.out.iterdir():
            data = path.read_bytes()
            self.assertFalse(data.startswith(b'\xef\xbb\xbf'), path.name)
            self.assertNotIn(b'\r', data, path.name)
            data.decode('utf-8')

    def test_captions_are_recorded_by_where_they_sit_in_the_article(self):
        # lease-law 2 مكرر ends in a caption; civil 4 gets one with body text after it (group_chunker.py:31 opens a
        # section at each).
        correction = {'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'نص قبله.\n## الفصل الأول أحكام\nنص بعده.'}
        f = self.fixture(corrections=[correction])

        manifest = f.build()['manifest']

        self.assertEqual(manifest['caption_tail_articles'], ['lease-law:2:مكرر'])
        self.assertEqual(manifest['caption_inner_articles'], ['civil:4'])
        self.assertEqual(manifest['totals']['caption_lines'], 2)


class Counts(Base):
    def test_counts_and_order_equal_legal_search(self):
        f = self.fixture(corrections=[{'type': 'relabel', 'law': 'lease-law', 'number': 2, 'suffix': 'مكرر',
                                       'new_suffix': 'مكرر ثانياً'}])
        manifest = f.build()['manifest']
        corpus = f.harness / m.CORPUS_DIR
        counts = directory_counts(corpus / 'law-directory.md')
        corrections = load_corrections(f.harness / m.CORRECTIONS)
        for law, facts in zip(load_registry(f.harness / m.REGISTRY), manifest['files']):
            served = apply_corrections(parse_law(corpus / law.folder, law.slug),
                                       [c for c in corrections if c.law == law.slug])
            self.assertEqual(facts['articles'], len(served))
            self.assertEqual(facts['articles'], counts[law.folder] - len(law.known_gaps))
            self.assertEqual(facts['keys'], [m.key_of(a) for a in served])
        self.assertIn('lease-law:2:مكرر ثانياً', manifest['files'][0]['keys'])
        self.assertIn('### المادة 2 مكرر ثانياً\n', (f.out / 'lease-law.md').read_text(encoding='utf-8'))
        self.assertEqual(manifest['totals']['articles'], 6)
        self.assertEqual(manifest['totals']['known_gaps'], ['civil:3'])

    def test_count_off_the_directory_is_refused(self):
        self.refused(self.fixture(lease_count=4), 'lease-law: 3 articles, expected 4')

    def test_manifest_records_its_inputs(self):
        f = self.fixture()
        result = f.build()
        manifest = result['manifest']
        self.assertEqual(manifest['file_shape'], 'slug-title-served-v1')
        self.assertEqual(manifest['canvas']['sha256'], hashlib.sha256(f.canvas.read_bytes()).hexdigest())
        self.assertEqual(manifest['canvas']['levels'], LEVELS)
        self.assertEqual(manifest['generator']['sha256'], hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest())
        self.assertIsNone(manifest['baseline'])
        for facts in manifest['files']:
            data = (f.out / facts['name']).read_bytes()
            self.assertEqual((facts['sha256'], facts['bytes']), (hashlib.sha256(data).hexdigest(), len(data)))
        upload_set = ''.join(f'{x["name"]} {x["sha256"]}\n' for x in sorted(manifest['files'], key=lambda x: x['name']))
        self.assertEqual(manifest['upload_set_sha256'], hashlib.sha256(upload_set.encode()).hexdigest())
        raw = (f.out / m.MANIFEST).read_bytes()
        self.assertEqual(result['manifest_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(self.root.name.encode('utf-8'), raw, 'no path of this run in the manifest')

    def test_manifest_hashes_each_input_and_module(self):
        f = self.fixture()

        manifest = f.build()['manifest']

        self.assertEqual(manifest['inputs'], {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in (
                ('laws.json', f.harness / m.REGISTRY), ('corrections.json', f.harness / m.CORRECTIONS),
                ('law-directory.md', f.harness / m.CORPUS_DIR / 'law-directory.md'))})
        self.assertEqual(manifest['legal_search'], {
            Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (ls_corpus, ls_corrections, ls_normalize, ls_registry)})
        self.assertEqual((manifest['canvas']['chunk_token_cap'], manifest['canvas']['hierarchy'],
                          manifest['canvas']['title_chunker']), (8000, 3, 'TitleChunker:Fixture0'))

    def test_served_text_digest_is_over_the_text_as_served(self):
        f = self.fixture()
        rows = []
        for law in load_registry(f.harness / m.REGISTRY):
            rows += [(a.law_slug, a.number, a.suffix, a.text) for a in parse_law(f.harness / m.CORPUS_DIR / law.folder,
                                                                                 law.slug)]
        served, normalised = hashlib.sha256(), hashlib.sha256()
        for slug, number, suffix, text in sorted(rows):
            served.update(json.dumps([slug, number, suffix, text], ensure_ascii=False).encode('utf-8'))
            normalised.update(json.dumps([slug, number, suffix, normalize(text)], ensure_ascii=False).encode('utf-8'))

        manifest = f.build()['manifest']

        self.assertEqual(manifest['served_text_sha256'], served.hexdigest())
        self.assertEqual(manifest['corpus_sha256'], normalised.hexdigest())
        self.assertNotEqual(manifest['served_text_sha256'], manifest['corpus_sha256'])

    def test_baseline_must_match(self):
        f = self.fixture()
        baseline = self.root / 'eval-final.json'
        baseline.write_text(json.dumps({'run': {'corpus_sha256': '0' * 64}}), encoding='utf-8')
        with self.assertRaises(m.Refused) as caught:
            f.build(baseline=baseline)
        self.assertIn('not the baseline', str(caught.exception))
        library = m.load_library(f.harness)
        baseline.write_text(json.dumps({'run': {'corpus_sha256': m.corpus_sha256(library)}}), encoding='utf-8')
        self.assertTrue(f.build(baseline=baseline)['manifest']['baseline']['match'])


class Library(Base):
    """The ingest checks the tool repeats (ingest.py:45-77) and its own checks on the registry."""

    def test_a_duplicate_article_is_refused(self):
        # The directory count is raised to match, so only the duplicate check stands between it and the upload set.
        lease = LEASE_SHARD.replace('## الباب الثاني أحكام ختامية\n', '## الباب الثاني أحكام ختامية\n\n### المادة 1\n\nنص ثان.\n')

        self.refused(self.fixture(lease=lease, lease_count=4), 'lease-law: duplicate article المادة 1')

    def test_text_under_a_known_gap_is_refused(self):
        # The directory count is raised to match, so only the known-gap check refuses it.
        civil = CIVIL_SHARD.replace('### المادة 3\n', '### المادة 3\n\nنص وجد.\n')

        self.refused(self.fixture(civil=civil, civil_count=5), 'civil: known gap المادة 3 is present')

    def test_a_correction_for_a_law_not_in_the_registry_is_refused(self):
        correction = {'type': 'replace', 'law': 'nope', 'number': 1, 'text': 'نص'}

        self.refused(self.fixture(corrections=[correction]), 'corrections name laws not in the registry: nope')

    def test_a_folder_missing_from_the_law_directory_is_refused(self):
        f = self.fixture()
        directory = f.harness / m.CORPUS_DIR / 'law-directory.md'
        directory.write_text(directory.read_text(encoding='utf-8').replace('| المدني | `المدني` | 4 |\n', ''),
                             encoding='utf-8')

        self.refused(f, 'civil: folder المدني is not listed in law-directory.md')

    def test_an_unsafe_slug_is_refused(self):
        for slug in ('../x', 'Lease', 'a/b', '-x'):
            with self.subTest(slug=slug):
                f = Fixture(Path(tempfile.mkdtemp(dir=self.root)))
                f.edit_registry(0, slug=slug)

                with self.assertRaises(m.Refused) as caught:
                    f.build()

                self.assertIn(f'slug {slug!r} is not a safe file name', str(caught.exception))
                self.assertFalse(any(f.root.glob('*.md')) or f.out.exists())

    def test_a_title_that_cannot_stand_on_one_line_is_refused(self):
        for title in ('قانون الإيجار ', ' قانون الإيجار', '', 'قانون\nالإيجار', '#قانون الإيجار'):
            with self.subTest(title=repr(title)):
                f = Fixture(Path(tempfile.mkdtemp(dir=self.root)))
                f.edit_registry(0, title=title)

                with self.assertRaises(m.Refused) as caught:
                    f.build()

                self.assertIn('lease-law: the registry title cannot stand on one «# » line', str(caught.exception))
                self.assertFalse(f.out.exists())


class CanvasRegex(Base):
    def test_planted_bad_heading_fails_the_level_3_check(self):
        f = self.fixture()
        law, articles = m.load_library(f.harness)[0]
        good = m.render(law, articles)
        lines = [(role, i, '### مادة 2' if line == '### المادة 2' else line) for role, i, line in good.lines]
        bad = dataclasses.replace(good, lines=lines,
                                  data=('\n'.join(x for _, _, x in lines) + '\n').encode('utf-8'))
        canvas = m.load_canvas(f.canvas)
        m.check(good, canvas)
        with self.assertRaises(m.Refused) as caught:
            m.check(bad, canvas)
        self.assertIn('lease-law.md lease-law:2: heading resolves to level None', str(caught.exception))

    def test_a_stricter_canvas_regex_refuses_a_suffixed_heading(self):
        strict = [*LEVELS[:2], '^\\s*###\\s+المادة\\s+[0-9]+$', LEVELS[3]]
        self.refused(self.fixture(canvas=canvas_dsl(levels=strict)), 'lease-law:2:مكرر: heading resolves to level')

    def test_body_line_at_level_1_is_refused(self):
        lease = LEASE_SHARD.replace('ويكون الدفع في موعده.', 'ويكون الدفع في موعده.\n# قانون التجارة')
        self.refused(self.fixture(lease=lease), 'lease-law:2:مكرر: a body line matches canvas level [1]')

    def test_body_line_at_level_3_is_refused(self):
        lease = LEASE_SHARD.replace('### المادة 1\n', '### المادة 1 — ### المادة 9 نص منقول\n')
        self.refused(self.fixture(lease=lease), 'lease-law:1: a body line matches canvas level [3]')

    def test_body_line_at_level_4_is_refused(self):
        lease = LEASE_SHARD.replace('ويكون الدفع في موعده.', '#### فرع')
        self.refused(self.fixture(lease=lease), 'a body line matches canvas level [4]')

    def test_level_3_through_a_correction_is_refused(self):
        correction = {'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'نص\n### المادة 5'}
        self.refused(self.fixture(corrections=[correction]), 'civil:4: a body line matches canvas level [3]')

    def test_a_title_line_matching_another_level_is_refused(self):
        # His level 1 still wins the title line, but a level-2 pattern that also matches it is refused (the strict
        # test); civil's title, not a «قانون» title, would resolve to level 2 outright.
        loose = [LEVELS[0], '^#\\s+.+', *LEVELS[2:]]

        self.refused(self.fixture(canvas=canvas_dsl(levels=loose)),
                     'lease-law.md title line: matches level [1, 2], not the title level or none')

    def test_caption_level_is_allowed_in_a_body(self):
        f = self.fixture()
        f.build()
        self.assertIn('\n## الباب الثاني أحكام ختامية\n', (f.out / 'lease-law.md').read_text(encoding='utf-8'))

    def test_a_file_the_chunker_would_cut_above_the_articles_is_refused(self):
        # lease-law.md holds levels 1 (title), 2 (caption) and 3: at hierarchy 2 the group target is 2 (common.py:514-521).
        self.refused(self.fixture(canvas=canvas_dsl(hierarchy=2)), 'lease-law.md: the chunker would cut at level 2')

    def test_canvas_shapes_refused(self):
        for dsl, needle in (
                (canvas_dsl(chunkers=2), '2 TitleChunker components'),
                (canvas_dsl(chunkers=0), '0 TitleChunker components'),
                (canvas_dsl(method='hierarchy'), 'group method only'),
                (canvas_dsl(families=[LEVELS, LEVELS]), 'exactly one family'),
                (canvas_dsl(levels=LEVELS[:2]), 'fewer than the article level'),
                (canvas_dsl(levels=['(', *LEVELS[1:]]), 'bad TitleChunker setting'),
                ({'dsl': {}}, 'no `components` object')):
            with self.subTest(needle=needle):
                path = self.root / 'c.json'
                path.write_text(json.dumps(dsl, ensure_ascii=False), encoding='utf-8')
                with self.assertRaises(m.Refused) as caught:
                    m.load_canvas(path)
                self.assertIn(needle, str(caught.exception))

    def test_empty_patterns_are_dropped_as_ragflow_does(self):
        path = self.root / 'c.json'
        path.write_text(json.dumps(canvas_dsl(levels=['', *LEVELS]), ensure_ascii=False), encoding='utf-8')
        self.assertEqual(m.load_canvas(path).patterns, tuple(LEVELS))

    def test_title_levels(self):
        family = m.load_canvas(self.fixture().canvas).family
        self.assertEqual(m.level_of('# قانون العمل', family), 1)
        self.assertIsNone(m.level_of('# القانون المدني الأردني', family))
        self.assertIsNone(m.level_of('# مجلة الأحكام العدلية', family))
        self.assertEqual(m.level_of('### المادة 25 مكرر ثانياً', family), 3)


class Hazards(Base):
    def test_each_hazard_is_refused(self):
        for text, needle in (
                ('انظر https://example.test/a', 'a URL'),
                ('انظر www.example.test', 'a URL'),
                ('صورة ![x](a.png)', 'a markdown image'),
                ('انظر data:x', 'a URL'),
                ('صورة <img alt=x>', 'an HTML image or src attribute'),
                # naive.py:959 has no word boundary before «src=» and ignores case.
                ("صورة xsrc='a.png'", 'an HTML image or src attribute'),
                ('صورة SRC="/etc/x.png"', 'an HTML image or src attribute'),
                ('رابط [هنا](a.md)', 'a markdown link'),
                ('[1]: a.md', 'a markdown link'),
                ('نص <div class="x">نص', 'an HTML tag RAGFlow rewrites'),
                ('نص <DIV a>نص', 'an HTML tag RAGFlow rewrites'),  # markdown_parser.py:101 ignores case
                ('نص <table>', 'an HTML tag RAGFlow rewrites'),
                ('نص <table x', 'an HTML table'),  # civil 4 is the file's last article: no «>» follows
                ('نص\n```\nشيفرة', 'a code fence'),
                ('أ | ب', 'a pipe'),
                ('نص\rنص', 'a carriage return'),
                ('نص﻿نص', 'a byte order mark'),
                ('نص\x07نص', 'a control character'),
                ('نص\x7fنص', 'a control character')):
            with self.subTest(needle=needle, text=text):
                root = Path(tempfile.mkdtemp(dir=self.root))
                f = Fixture(root, corrections=[{'type': 'replace', 'law': 'civil', 'number': 4, 'text': text}])
                with self.assertRaises(m.Refused) as caught:
                    f.build()
                self.assertIn(needle, str(caught.exception))
                self.assertIn('civil.md civil:4', str(caught.exception))
                self.assertFalse(f.out.exists() and any(f.out.iterdir()))

    def test_tag_rewrite_is_read_across_articles(self):
        # «<div» in one article and the next «>» two articles later: RAGFlow would delete the text between.
        corrections = [{'type': 'replace', 'law': 'civil', 'number': 1, 'text': 'نص <div'},
                       {'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'أ > ب'}]
        self.refused(self.fixture(corrections=corrections), 'civil.md civil:1: holds an HTML tag RAGFlow rewrites')

    def test_an_unclosed_tag_at_the_end_is_kept_and_recorded(self):
        f = self.fixture(corrections=[{'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'نص\n\n<div'}])
        manifest = f.build()['manifest']
        self.assertEqual(manifest['angle_bracket_articles'], ['civil:4'])
        self.assertTrue((f.out / 'civil.md').read_bytes().endswith('نص\n\n<div\n'.encode('utf-8')))

    def test_a_lone_closing_angle_is_kept_and_recorded(self):
        f = self.fixture(corrections=[{'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'أ > ب'}])

        manifest = f.build()['manifest']

        self.assertEqual(manifest['angle_bracket_articles'], ['civil:4'])

    def test_read_back_refuses_text_the_shard_parser_would_change(self):
        # A «---» line passes every check before writing, but legal_search's parser drops it (corpus.py:16, :72):
        # the file would not read back as the served text, so the written files are removed.
        correction = {'type': 'replace', 'law': 'civil', 'number': 4, 'text': 'أ\n---\nب'}
        self.refused(self.fixture(corrections=[correction]), 'civil.md: parsed back 3 articles for 3 served')

    def test_text_outside_the_parser_normal_form_is_refused_before_writing(self):
        for text in ('نص ', 'أ\n\n\nب', '', ' أ\nب'):
            with self.subTest(text=repr(text)):
                root = Path(tempfile.mkdtemp(dir=self.root))
                f = Fixture(root, corrections=[{'type': 'replace', 'law': 'civil', 'number': 4, 'text': text}])
                with self.assertRaises(m.Refused) as caught:
                    f.build()
                self.assertIn('cannot hold it byte for byte', str(caught.exception))
                self.assertFalse(f.out.exists())


class Determinism(Base):
    def test_same_bytes_twice(self):
        f = self.fixture()
        first, second = f.build(out=self.root / 'a'), f.build(out=self.root / 'b')
        self.assertEqual(first['manifest_sha256'], second['manifest_sha256'])
        names = sorted(p.name for p in (self.root / 'a').iterdir())
        self.assertEqual(names, sorted(p.name for p in (self.root / 'b').iterdir()))
        for name in names:
            self.assertEqual((self.root / 'a' / name).read_bytes(), (self.root / 'b' / name).read_bytes(), name)


class OutFolder(Base):
    def test_non_empty_out_is_refused(self):
        f = self.fixture()
        f.out.mkdir()
        (f.out / 'stray.md').write_text('x', encoding='utf-8')
        code, stdout, stderr = f.main()
        self.assertEqual(code, 2)
        self.assertIn('--out is not empty', stderr)
        self.assertEqual(sorted(p.name for p in f.out.iterdir()), ['stray.md'])
        self.assertEqual((f.out / 'stray.md').read_text(encoding='utf-8'), 'x')

    def test_replace_overwrites_this_tools_files(self):
        f = self.fixture()
        self.assertEqual(f.main()[0], 0)
        (f.out / 'old-law.md').write_text('x', encoding='utf-8')
        self.assertEqual(f.main()[0], 2)
        code, stdout, _ = f.main('--replace')
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in f.out.iterdir()), ['civil.md', 'lease-law.md', 'upload-manifest.json'])
        self.assertIn('upload-manifest.json sha256 ', stdout)

    def test_replace_never_removes_a_foreign_entry(self):
        f = self.fixture()
        self.assertEqual(f.main()[0], 0)
        (f.out / 'notes.txt').write_text('keep', encoding='utf-8')
        (f.out / 'sub').mkdir()
        code, _, stderr = f.main('--replace')
        self.assertEqual(code, 2)
        self.assertIn('entries this tool does not write', stderr)
        self.assertEqual(sorted(p.name for p in f.out.iterdir()),
                         ['civil.md', 'lease-law.md', 'notes.txt', 'sub', 'upload-manifest.json'])

    def test_replace_never_removes_a_symlinked_md(self):
        # Windows refuses os.symlink without a privilege, so the entry is a regular file that reports itself a link.
        f = self.fixture()
        self.assertEqual(f.main()[0], 0)
        link = f.out / 'link.md'
        link.write_text('x', encoding='utf-8')
        is_symlink = type(link).is_symlink

        with mock.patch.object(type(link), 'is_symlink', lambda p: p.name == 'link.md' or is_symlink(p)):
            code, _, stderr = f.main('--replace')

        self.assertEqual(code, 2)
        self.assertIn('entries this tool does not write, left alone: link.md', stderr)
        self.assertEqual(link.read_text(encoding='utf-8'), 'x')

    def test_out_that_is_a_file_is_refused(self):
        f = self.fixture()
        f.out.write_text('x', encoding='utf-8')

        with self.assertRaises(m.Refused) as caught:
            f.build()

        self.assertIn('--out is not a folder', str(caught.exception))
        self.assertEqual(f.out.read_text(encoding='utf-8'), 'x')

    def test_missing_out_is_created(self):
        f = self.fixture()
        self.assertEqual(f.main(out=self.root / 'new' / 'in')[0], 0)
        self.assertTrue((self.root / 'new' / 'in' / m.MANIFEST).is_file())

    def test_isolated_run_from_a_foreign_folder(self):
        f = self.fixture()
        foreign = self.root / 'foreign'
        foreign.mkdir()
        (foreign / 'json.py').write_text('raise SystemExit("planted module imported")', encoding='utf-8')
        run = subprocess.run(
            [sys.executable, '-I', '-B', str(Path(m.__file__)), '--canvas', str(f.canvas), '--out', str(f.out),
             '--harness', str(f.harness), '--no-baseline'],
            cwd=foreign, capture_output=True, env={k: v for k, v in os.environ.items() if k != 'PYTHONPATH'})
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', 'replace'))
        self.assertIn('2 files, 6 articles', run.stdout.decode('utf-8'))


@unittest.skipUnless(REAL_LIBRARY, 'real data: our library is not in this checkout')
class RealData(Base):
    def test_our_library(self):
        canvas = self.root / 'canvas.json'
        canvas.write_text(json.dumps(canvas_dsl(), ensure_ascii=False), encoding='utf-8')
        baseline = m.DEFAULT_BASELINE if m.DEFAULT_BASELINE.is_file() else None
        manifest = m.build(canvas, self.root / 'out', baseline=baseline)['manifest']
        totals = manifest['totals']
        self.assertEqual((totals['files'], totals['articles']), (22, 6592))
        self.assertEqual(totals['known_gaps'], ['civil-code:1287'])
        corpus = m.HARNESS / m.CORPUS_DIR
        counts = directory_counts(corpus / 'law-directory.md')
        for law, facts in zip(load_registry(m.HARNESS / m.REGISTRY), manifest['files']):
            self.assertEqual((facts['name'], facts['articles'], facts['target_level']),
                             (f'{law.slug}.md', counts[law.folder] - len(law.known_gaps), 3))
        if baseline:
            self.assertTrue(manifest['baseline']['match'])

    @unittest.skipUnless(REAL_CANVAS.is_file(), 'real data: Walid\'s indexing canvas is not here')
    def test_real_canvas(self):
        # His file is untrusted: it is read only by the tool, run as python -I, against the fixture library.
        f = self.fixture()
        run = subprocess.run(
            [sys.executable, '-I', '-B', str(Path(m.__file__)), '--canvas', str(REAL_CANVAS), '--out', str(f.out),
             '--harness', str(f.harness), '--no-baseline'], cwd=self.root, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', 'replace'))
        canvas = json.loads((f.out / m.MANIFEST).read_text(encoding='utf-8'))['canvas']
        self.assertEqual((canvas['levels'], canvas['method'], canvas['hierarchy']), (LEVELS, 'group', 3))


if __name__ == '__main__':
    unittest.main()
