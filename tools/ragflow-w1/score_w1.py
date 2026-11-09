#!/usr/bin/env python3
"""Score Walid's W1 results against our search, under the spec's W1 mapping rule and decision rule (c).

    python -I score_w1.py --results <quarantine>/<handover-id>/w1-results.jsonl --out-dir DIR [--laws-held a,b]
        [--articles-lacking law:number,...] [--allow-unevidenced-laws]
    python -I score_w1.py --results .hq/scratch/w2-run/out/<engine>/w2-results-<arm>.jsonl --own-run
        --manifest .hq/scratch/w2-run/out/<engine>/w2-manifest.json --out-dir DIR [--w2-decide]
        [--fallback .hq/scratch/w2-run/out/<engine>/w2-fallback-<arm>.json]
    python -I score_w1.py --self-check

Spec: .hq/docs/specs/spec-rag-system.md, «The decisive test» (Definitions, Part 2, the W1 mapping rule,
decision rule (c), and the block «Owner decision 2026-11-08: W2 first, run here, with a pre-registered rule»)
and «The miss pattern» (the strata). README.md («intake_w1.py and score_w1.py — our side») states every rule
as built. Walid's results file is read only after intake_w1.py quarantined it and a person recorded a clear
screen. An own run (W2: our corpus in our own throwaway RAGFlow) is read only beside a W2 manifest that ties it
to that dataset. The outputs hold ids, ranks, counts and metrics, never chunk text (REQ-RAG-047).

Python standard library only. It imports the stdlib-only legal_search modules of the repository it sits in
(corpus, corrections, registry, normalize, metrics), never db, ingest, evalset or citation (they need psycopg).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

TOOL = Path(__file__).resolve().parent
HARNESS = TOOL.parents[1]
WORKSPACE = TOOL.parents[2]
# python -I leaves the script's folder off sys.path; both entries are fixed paths, never the current directory.
sys.path[:0] = [str(TOOL), str(HARNESS / 'services' / 'legal-search' / 'src')]

from intake_w1 import (COUNTS_KEYS, DEFAULT_PACKAGE, FIELDS, SETTING_KEYS, Refused, check_cleared,  # noqa: E402
                       read_results, sha256_file)
from legal_search.corpus import parse_law  # noqa: E402
from legal_search.corrections import apply_corrections, load_corrections  # noqa: E402
from legal_search.metrics import Scored, hit_at, recall_at, summarise  # noqa: E402
from legal_search.normalize import normalize, tokens  # noqa: E402
from legal_search.registry import directory_counts, load_registry  # noqa: E402

Key = tuple  # (law slug, number, suffix), as legal_search.metrics.Key

EVALSET = HARNESS / 'content' / 'eval' / 'retrieval-v1.jsonl'
BENCH = WORKSPACE / '.hq' / 'scratch' / 'rag-bench'
EVIDENCE = WORKSPACE / '.hq' / 'docs' / 'audits' / 'librechat-platform' / 'p3-evidence'  # tracked, durable
BASELINE = EVIDENCE / 'eval-final.json'
# The bench files with a durable copy in p3-evidence (copied 2026-11-08, byte-identical; README, «Where the arms are
# read from»). Each is read from its copy when present, else from the bench with a warning (bench_source).
DURABLE = {'results/rows-round2.jsonl': 'rag-bench-rows-round2.jsonl',
           'results/rows-round4.jsonl': 'rag-bench-rows-round4.jsonl',
           'results/perf/pg-rows-question.jsonl': 'rag-bench-pg-rows-question.jsonl',
           'data/eval.jsonl': 'rag-bench-eval.jsonl'}
SPLIT = EVIDENCE / 'rag-bench-split.json'
SPLIT_IN_BENCH = 'data/split.json'
STRATA_TERMS = 'data/eval.jsonl'  # in the bench: derive_strata's recorded query terms (a durable copy in DURABLE)
# The bench's split (T-B2 was tuned on half A), as copied to p3-evidence; the W2 deciding reading uses only it.
SPLIT_SHA256 = '6e7909beedf20c4d79aad0038b58a64c665718b5fb552416689e4e77445cd1a4'
# T-B2's ranked lists: rows-round2.jsonl as copied to p3-evidence (README, «Where the arms are read from»). The
# deciding reading compares against these rows only; the re-scored all-80 figures alone do not pin the half-B rows.
T_B2_ROWS_SHA256 = '7bccbab9495646bc770d3ac5dbe6d243befd5a675d37861b32e5b3b46b0691ac'
HALVES = ('A', 'B')
REGISTRY = HARNESS / 'content' / 'corpus' / 'laws.json'

# Own runs (W2): spec «Owner decision 2026-11-08». The W2 manifest is the shared contract the ingest tool writes.
OWN_ROOT = WORKSPACE / '.hq' / 'scratch' / 'w2-run' / 'out'
OWN_LABEL = 'own run (W2)'
W2_MANIFEST = 'w2-manifest.json'
W2_MANIFEST_KEYS = frozenset({'w2', 'created_at', 'engine', 'embedder', 'ragflow_version', 'ragflow_image_digest',
                              'dataset_id', 'language', 'document_count', 'chunk_count', 'predicted_chunk_count',
                              'all_match', 'canvas_sha256', 'upload_manifest_sha256', 'file_shape',
                              'embedding_batch_size', 'max_concurrent_tasks', 'tei_wait_patch'})
W2_EMBEDDER_KEYS = frozenset({'name', 'revision', 'via'})
# The TEI-wait patch the server ran (spec, «Owner decision 2026-11-08 (later)»; tools/ragflow-w2/patch_tei_wait.py).
# Operational, not a retrieval setting: recorded and printed, never a deciding gap. «diff» is the unified diff text
# (the spec: «Its diff and both sha256 go in the W2 manifest»); rf_ingest.py checks it against the patched file.
W2_TEI_WAIT_KEYS = frozenset({'file', 'image_sha256', 'patched_sha256', 'changed_lines', 'wait_s', 'diff'})
W2_TEI_WAIT_FILE = 'rag/llm/embedding_model.py'
W2_TEI_WAIT_SHIPPED = 30  # v0.27.3's wait (rag/llm/embedding_model.py:1247, :1253)
# The owner's approved change (tools/ragflow-w2/README.md, «## TEI wait patch»; check_tei_wait.py APPROVED, which
# refuses any other before a parse). Another one is warned about, not a deciding gap.
W2_TEI_WAIT_APPROVED = {'image_sha256': 'c2e46e1cb5d128122a48b8283d135b81321441655dbd9c22c9ecd8035a6c0536',
                        'patched_sha256': '90f3a20d0bfab00175670c90c93e410592029bbf7b75b7aadfe944f71c74acab',
                        'changed_lines': [1247, 1253], 'wait_s': 900}
W2_ENGINES = ('elasticsearch', 'infinity')
W2_VIA = 'builtin-tei'
# The hosted run (spec-rag-system.md:472, «The hosted run»; tools/ragflow-w2/README.md, «Hosted run (owner,
# 2026-11-09)»): exploratory only, never the deciding cell. Its own root, beside OWN_ROOT; its manifest holds
# hosted_embedder (rf_ingest.py, from register_hosted.py's record) in place of tei_wait_patch, and an embedder whose
# revision is null: a hosted model has none to pin.
HOSTED_ROOT = WORKSPACE / '.hq' / 'scratch' / 'w2-hosted' / 'out'
W2_HOSTED_VIA = 'hosted-openrouter'
W2_HOSTED_MANIFEST_KEYS = (W2_MANIFEST_KEYS - {'tei_wait_patch'}) | {'hosted_embedder'}
W2_HOSTED_KEYS = frozenset({'model', 'instance', 'factory', 'base_url', 'provider_order', 'data_policy'})
W2_HOSTED_FACTORY = 'OpenRouter'
W2_HOSTED_BASE_URL = 'https://openrouter.ai/api/v1'
W2_FILE_SHAPE = 'slug-title-served-v1'
W2_DOCUMENTS = 22  # one generated file per law of the registry
# Exactly what the release image reports: its VERSION file is `git describe --tags` run at the tag
# (v0.27.3 Dockerfile:267-269, built by .github/workflows/release-python.yml:79), served by common/versions.py:23-33.
RAGFLOW_VERSION = 'v0.27.3'
OWN_RESULTS = re.compile(r'^w2-results-(v3|rt)\.jsonl$')
OWN_FALLBACK = 'w2-fallback-{arm}.json'
# What run_w1.py sends for each arm (run_w1.py retrieval_settings(); a test checks these against its defaults):
# v3 = its defaults, the FINAL REVIEW v3 Retrieval node; rt = --vector-similarity-weight 0.4 (Retrieval TEST).
V3_SETTINGS = {'page': 1, 'page_size': 20, 'similarity_threshold': 0.2, 'vector_similarity_weight': 0.3,
               'top_k': 1024, 'rerank_candidates_count': 64, 'keyword': False, 'use_kg': False,
               'toc_enhance': False, 'cross_languages': [], 'highlight': False}
OWN_ARMS = {'v3': V3_SETTINGS, 'rt': {**V3_SETTINGS, 'vector_similarity_weight': 0.4}}
OWN_ARM_LABELS = {'v3': 'FINAL REVIEW v3 settings (20 chunks, threshold 0.2, vector weight 0.3, no reranker)',
                  'rt': 'Retrieval TEST vector weight 0.4 (otherwise FINAL REVIEW v3)'}
# The deciding cell, fixed by the amendment before anything ran. The model revision is the one the runbook fetches
# (.hq/scratch/w2-research/deploy/runbook.md, Step 4: `main` on 2026-11-08); the canvas is the sha256 of the raw
# bytes of Walid's indexing pipeline «اقرأ – فهرسة التشريعات القانونية.json», which the amendment imports as it is
# (rf_ingest.py check_canvas() hashes those bytes). The provider is the one the server names built-in TEI by
# (tenant_model_service.py:268, rf_ingest.py creates the dataset with '<model>@Builtin'). The RAGFlow image digest
# is recorded from the run, not pinned here: no `docker pull` has confirmed one yet (README, «known limits»).
DECIDING = {'engine': 'elasticsearch', 'embedder': 'Qwen/Qwen3-Embedding-0.6B',
            'revision': '97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3', 'provider': 'Builtin', 'via': W2_VIA,
            'canvas_sha256': '3f0fcb62b79a0b292f05ccfc9ad198259acfb3b459a21c73c6ca4fc369bf588d', 'arm': 'v3',
            'field': 'query', 'against': 'T-B2', 'half': 'B'}
DECIDING_RULE = ('W2 wins only if the paired-bootstrap 95% interval of W2 minus T-B2 lies above zero: recall within '
                 'the equal served-text budget, both scored through the mapping rule at T-B2\'s budget, on the query '
                 'field, on the held-out half B. Otherwise «not shown».')

TOP = 5  # search_law serves at most 5 articles (caps.py:10 max_results, tools.py:79 limit=5)
SEED, RESAMPLES = 20261106, 10_000  # the bench's paired bootstrap (rag-bench py/report.py:21-26)
# An interval end counts as off zero only past this. Per-item recall is k/1, k/2 or k/3 (at most 3 expected
# articles), so a difference is a multiple of 1/6 and a nonzero mean over n items is at least 1/(6n), 0.002 at
# n = 80; a float sum of thirds that is zero in exact arithmetic can leave a residue near 1e-17.
ZERO_TOLERANCE = 1e-9
RULES = ('truncate', 'include', 'exclude')  # how the chunk that crosses the budget counts; the first decides
INFER_MIN_CHUNKS, INFER_MIN_TOKENS = 3, 8  # held: the best source, matching 8+ tokens, of 3 of his chunks
# The matched half of an n-token article must lie within WINDOW_FACTOR * n consecutive chunk tokens (‡). On
# neighbour runs of our own articles (README, «The mapping rule»), 2 and 1.5 still let two runs map an article
# through two adjacent articles beside it, which neither maps alone; 1 lets none.
WINDOW_FACTOR = 1
NEVER_REACHED = ('civil-code-02', 'civil-code-memo-03', 'penal-code-02', 'penal-code-08', 'civil-procedure-01',
                 'investment-fund-01')  # spec «The miss pattern»
TRACKED = 'civil-code-08'
STRATUM_SIZES = {'under': 17, 'half': 49, 'all': 14}  # spec «The miss pattern» table


@dataclass(frozen=True)
class ArmSpec:
    name: str
    field: str
    label: str
    source: str  # a file under the bench folder, or 'baseline' for eval-final.json
    cfg: str | None
    recorded: tuple  # (recall@5, hit@5, mrr) on all 80, as recorded


# The comparison arms. Part 1 (A1) has not run, so these are the recorded ones: A0 and the two T rows on the
# query field (spec Part 1 table); on the question field, Postgres and the BM25 rows of PROOF-rag-bench.md
# «On the question text instead of the keyword query». Recorded figures: score-all.json[cfg]['all']['overall'],
# and eval-final.json ['metrics']['overall'] for A0.
ARMS = (
    ArmSpec('A0', 'query', 'Postgres today (eval-final.json)', 'baseline', None, (0.5625, 0.6375, 0.4874)),
    ArmSpec('T-B2', 'query', 'Tantivy r2|b2|t0.5|h1.0', 'results/rows-round2.jsonl', 'r2|b2|t0.5|h1.0',
            (0.7229, 0.7875, 0.5498)),
    ArmSpec('T-B3d', 'query', 'Tantivy r2|b3d|l2.0|w16', 'results/rows-round2.jsonl', 'r2|b3d|l2.0|w16',
            (0.7063, 0.7625, 0.574)),
    ArmSpec('A0q', 'question', 'Postgres today, question verbatim', 'results/perf/pg-rows-question.jsonl',
            'pgrust:question:gold', (0.4604, 0.525, 0.3707)),
    ArmSpec('B1q', 'question', 'BM25 B1 A-selected, question', 'results/rows-round2.jsonl', 'r2|q:question',
            (0.6937, 0.7625, 0.5987)),
    ArmSpec('T-B2q', 'question', 'B2 A-selected, question', 'results/rows-round4.jsonl',
            'r4|q:question|r2|b2|t0.5|h1.0', (0.675, 0.7375, 0.6005)),
    ArmSpec('T-B3dq', 'question', 'B3d A-selected, question', 'results/rows-round4.jsonl',
            'r4|q:question|r2|b3d|l2.0|w16', (0.6875, 0.75, 0.6206)),
    ArmSpec('B4q', 'question', 'B4 A-selected, question', 'results/rows-round4.jsonl',
            'r4|q:question|r2|b4|guardlight|dismax', (0.7, 0.7625, 0.6003)),
)


@dataclass(frozen=True)
class Item:
    id: str
    query: str
    question: str
    expected: frozenset
    law: str  # the law it is reported under: that of its expected articles (legal_search/evalset.py:66-68)


@dataclass(frozen=True)
class Arm:
    spec: ArmSpec
    ranked: dict  # item id -> tuple of keys, in rank order
    recomputed: dict
    source_sha256: str
    source_path: str = ''
    durable: bool = False  # read from the tracked p3-evidence copy, not the scratch bench
    warning: str | None = None  # set when a durable copy exists in name but was missing, and the bench was read


# The library, as search_law serves it ---------------------------------------------------------------------------

def library_texts(harness: Path = HARNESS) -> dict:
    """Every article's text, keyed (law, number, suffix): the shards parsed with the registry's corrections applied
    and the counts checked, as legal_search.ingest._law_articles does (ingest.py:42-62), which stores a.text
    (db.py:229) and so serves it. ingest itself needs psycopg, so its steps are repeated here."""
    corpus = harness / 'jordanian-law' / 'references' / 'القوانين-الأردنية'
    laws = load_registry(harness / 'content' / 'corpus' / 'laws.json')
    corrections = load_corrections(harness / 'content' / 'corpus' / 'corrections.json')
    counts = directory_counts(corpus / 'law-directory.md')
    texts: dict = {}
    for law in laws:
        articles = apply_corrections(parse_law(corpus / law.folder, law.slug),
                                     [c for c in corrections if c.law == law.slug])
        if len(articles) != counts[law.folder] - len(law.known_gaps):
            raise ValueError(f'{law.slug}: {len(articles)} articles, not the directory count minus known gaps')
        for article in articles:
            key = (article.law_slug, article.number, article.suffix)
            if key in texts:
                raise ValueError(f'{law.slug}: duplicate article {article.number}')
            texts[key] = article.text
    return texts


def corpus_sha256(texts: dict) -> str:
    """As legal_search.evaluate.corpus_digest (evaluate.py:153-159): key and normalised text, in key order."""
    digest = hashlib.sha256()
    for key in sorted(texts):
        digest.update(json.dumps([*key, normalize(texts[key])], ensure_ascii=False).encode('utf-8'))
    return digest.hexdigest()


def load_evalset(path: Path = EVALSET) -> tuple[list, str]:
    """The items in file order and the set's sha256, computed as legal_search.evalset does (evalset.py:108)."""
    lines = [line for line in path.read_text(encoding='utf-8').replace('\r\n', '\n').split('\n') if line.strip()]
    items = []
    for line in lines[1:]:
        raw = json.loads(line)
        expected = frozenset((e['law'], e['number'], e.get('suffix', '')) for e in raw['expected'])
        items.append(Item(raw['id'], raw['query'], raw['question'], expected, raw['expected'][0]['law']))
    return items, hashlib.sha256('\n'.join(lines[1:]).encode('utf-8')).hexdigest()


def label(key: Key) -> str:
    return f'{key[0]}:{key[1]}' + (f' {key[2]}' if key[2] else '')


# The mapping rule ----------------------------------------------------------------------------------------------

def need(n: int) -> int:
    """At least half of n tokens: ceil(n / 2)."""
    return (n + 1) // 2


def window(n: int) -> int:
    """The stretch of chunk tokens the matched half of an n-token article must lie within: WINDOW_FACTOR * n."""
    return WINDOW_FACTOR * n


def lcs_length(masks: dict, n: int, other) -> int:
    """Length of the longest common subsequence of an n-token sequence (given as token -> bitmask of its positions)
    and `other`. Bit-parallel (Allison-Dix / Hyyrö): one big-integer step per token of `other`."""
    full = (1 << n) - 1
    v = full
    for token in other:
        match = masks.get(token)
        if match:
            u = v & match
            v = ((v + u) | (v - u)) & full
    return n - bin(v).count('1')


def masks_of(sequence) -> dict:
    masks: dict = {}
    for position, token in enumerate(sequence):
        masks[token] = masks.get(token, 0) | (1 << position)
    return masks


def _windows(counts: Counter, chunk, width: int):
    """(start, bound) for each stretch chunk[start:start + width] worth testing: those that start on one of the
    article's tokens, and the last one. Any other stretch holds no more of the article than one of these (its
    matched tokens lie in the stretch that starts at its first matched token, or in the last stretch). The bound
    is the sum, over the article's tokens, of the smaller of the two counts: no common subsequence is longer."""
    held = Counter(token for token in chunk[:width] if token in counts)
    bound = sum(min(count, counts[token]) for token, count in held.items())
    last = len(chunk) - width
    for start in range(last + 1):
        if start:
            leaving, entering = chunk[start - 1], chunk[start + width - 1]
            if leaving in counts:
                held[leaving] -= 1
                bound -= held[leaving] < counts[leaving]
            if entering in counts:
                bound += held[entering] < counts[entering]
                held[entering] += 1
        if start == last or chunk[start] in counts:
            yield start, bound


def window_lcs(masks: dict, counts: Counter, n: int, chunk, width: int, enough: int | None = None) -> int:
    """The most tokens of an n-token article, in order, that any `width` consecutive tokens of the chunk hold: the
    longest common subsequence of the article and a stretch of the chunk. Stops early once it reaches `enough`."""
    if len(chunk) <= width:
        return lcs_length(masks, n, chunk)
    best = 0
    for start, bound in _windows(counts, chunk, width):
        if bound > best:
            best = max(best, lcs_length(masks, n, chunk[start:start + width]))
            if best == n or (enough is not None and best >= enough):
                break
    return best


def pigeonhole(sequence, frequency: Counter) -> list:
    """The article's rarest distinct tokens, taken until they cover more than floor(n/2) of its n positions.
    A chunk that holds ceil(n/2) of the article's tokens in order matches ceil(n/2) positions; at most floor(n/2)
    lie outside this set, so the chunk holds at least one token of it. Indexing an article under these tokens
    only therefore never drops an article the rule would map."""
    n = len(sequence)
    counts = Counter(sequence)
    chosen, covered = [], 0
    for token in sorted(counts, key=lambda t: (frequency[t], t)):
        chosen.append(token)
        covered += counts[token]
        if n - covered < need(n):
            break
    return chosen


class Mapper:
    """A chunk retrieves article A (n tokens) when some stretch of window(n) consecutive chunk tokens (n: no longer
    than A) holds at least half of A's normalised tokens, in order: the longest common subsequence of that stretch
    and A is at least ceil(n/2). Without the stretch, a long chunk of neighbouring articles collects half of A's
    tokens from several of them and «retrieves» A without holding it. Tokens are legal_search.normalize.tokens
    (folded, clitics stripped, stopwords kept), the tokens the library indexes (db.py:230 stores
    normalize(text)). An article with no token is never mapped."""

    def __init__(self, texts: dict):
        self.tokens = {key: tuple(tokens(text)) for key, text in texts.items()}
        frequency = Counter(token for sequence in self.tokens.values() for token in set(sequence))
        self.postings = defaultdict(list)
        for key, sequence in self.tokens.items():
            for token in pigeonhole(sequence, frequency):
                self.postings[token].append(key)
        self._counts = {key: Counter(sequence) for key, sequence in self.tokens.items()}
        self._sets = {key: frozenset(sequence) for key, sequence in self.tokens.items()}
        self._masks: dict = {}
        self._cache: dict = {}

    def candidates(self, chunk) -> set:
        return {key for token in set(chunk) for key in self.postings.get(token, ())}

    def retrieves(self, chunk, key, chunk_set: frozenset | None = None) -> bool:
        sequence = self.tokens[key]
        n = len(sequence)
        if n == 0:
            return False
        shared = self._sets[key] & (frozenset(chunk) if chunk_set is None else chunk_set)
        # A common subsequence uses only shared tokens, each at most as often as A holds it: an upper bound.
        if sum(map(self._counts[key].__getitem__, shared)) < need(n):
            return False
        masks = self._masks_of(key)
        # The whole chunk holds every stretch: if it falls short, so does each stretch.
        if lcs_length(masks, n, chunk) < need(n):
            return False
        return window_lcs(masks, self._counts[key], n, chunk, window(n), need(n)) >= need(n)

    def _masks_of(self, key) -> dict:
        if key not in self._masks:
            self._masks[key] = masks_of(self.tokens[key])
        return self._masks[key]

    def articles(self, text: str, within: tuple | None = None) -> tuple:
        """The articles a chunk with this text retrieves, sorted by key. `within` limits the test to those keys:
        a text whose tokens are a prefix of another's retrieves only articles the longer one retrieves, since
        every stretch of the prefix is part of a stretch of the whole."""
        cache_key = (text, within)
        if cache_key not in self._cache:
            chunk = tokens(text)
            chunk_set = frozenset(chunk)
            pool = self.candidates(chunk) if within is None else within
            self._cache[cache_key] = tuple(sorted(k for k in pool if self.retrieves(chunk, k, chunk_set)))
        return self._cache[cache_key]

    def best_source(self, text: str) -> tuple | None:
        """(key, tokens matched) of the article the chunk retrieves with the most tokens matched in order within
        one stretch (then the longer, then by key): the article the chunk most likely came from. None when it
        retrieves nothing."""
        mapped = self.articles(text)
        if not mapped:
            return None
        chunk = tokens(text)

        def matched(key):
            n = len(self.tokens[key])
            return window_lcs(self._masks_of(key), self._counts[key], n, chunk, window(n)), n, key
        count, _, key = max(matched(key) for key in mapped)
        return key, count


# The equal served-text budget ------------------------------------------------------------------------------------

def served_chars(ranked, texts: dict) -> int:
    """Characters of law text the arm serves for an item: len(text), in code points, of each article in its top 5.
    search_law serves format_articles(found) (tools.py:109): per article a «[i] heading» line, the text, and a
    publication and verification line built from the registry (citation.py:62-69). Only the text is counted: the
    rest is framing about the source, not retrieved law text, and RAGFlow's chunk content holds no such framing."""
    return sum(len(texts[key]) for key in ranked[:TOP])


_SPACE = re.compile(r'\s')


def cut(text: str, left: int) -> str:
    """The first `left` characters of `text`, cut back to the last whitespace at or before them, so the piece
    holds whole words only and its tokens are a prefix of the text's tokens (normalize.tokens is char-local
    and splits on whitespace). A cut inside the first word leaves nothing."""
    if len(text) <= left:
        return text
    spaces = [match.start() for match in _SPACE.finditer(text, 0, left + 1)]
    return text[:spaces[-1]] if spaces else ''


def counted(chunks: list, budget: int, rule: str) -> list:
    """The chunk texts that count, in rank order, until their characters reach the budget. The chunk that crosses
    it: 'truncate' counts it up to the budget, cut back to a whole word, so W1 never reads past the budget;
    'include' counts it whole; 'exclude' stops before it. A chunk that starts at the budget never counts."""
    out, used = [], 0
    for text in chunks:
        left = budget - used
        if left <= 0:
            break
        if len(text) <= left:
            out.append(text)
            used += len(text)
        elif rule == 'truncate':
            out.append(cut(text, left))
            used = budget
        elif rule == 'include':
            out.append(text)
            used += len(text)
        else:
            break
    return out


def score_chunks(mapper: Mapper, chunks: list, budget: int, rule: str, expected: frozenset,
                 allowed: frozenset | None = None) -> dict:
    """W1 for one item at one budget. `allowed`, when given, keeps only those articles (the self-check's strict
    reading: each chunk may count only for the article it was made from)."""
    pieces = counted(chunks, budget, rule)
    first: dict = {}
    mapped = []
    for rank, piece in enumerate(pieces, 1):
        whole = chunks[rank - 1]
        keys = mapper.articles(whole) if piece == whole else mapper.articles(piece, mapper.articles(whole))
        if allowed is not None:
            keys = tuple(k for k in keys if k in allowed)
        if keys:
            mapped.append([rank, [label(k) for k in keys]])
        for key in keys:
            first.setdefault(key, rank)
    ranked = tuple(first)  # each mapped article once, at the rank of the first chunk that maps it
    return {
        'chunks_counted': len(pieces),
        'chars_counted': sum(map(len, pieces)),
        'cut_rank': len(pieces) if pieces and pieces[-1] != chunks[len(pieces) - 1] else None,
        'mapped': mapped,
        'expected_first_rank': {label(k): first.get(k) for k in sorted(expected)},
        'reached': hit_at(expected, ranked, len(ranked)),
        'recall': recall_at(expected, ranked, len(ranked)),
    }


# Recorded arms and strata ----------------------------------------------------------------------------------------

def _rows(path: Path, cfg: str) -> dict:
    prefix = '{"cfg":' + json.dumps(cfg) + ','
    with open(path, encoding='utf-8') as handle:
        rows = [json.loads(line) for line in handle if line.startswith(prefix)]
    return {row['id']: tuple(tuple(key) for key in row['ranked']) for row in rows}


def where(path: Path) -> str:
    """A path as the reports print it: relative to the workspace when inside it, with forward slashes."""
    path = Path(path)
    try:
        return path.resolve().relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.as_posix()


def bench_source(relative: str, bench: Path, durable: Path | None) -> tuple:
    """(path, durable, warning) for a bench file: its p3-evidence copy when DURABLE names one and it is present;
    else the bench file, with a warning when a durable copy was expected."""
    name = DURABLE.get(relative)
    if name and durable is not None and (Path(durable) / name).is_file():
        return Path(durable) / name, True, None
    path = Path(bench) / relative
    warning = (f'{relative}: the durable copy {where(Path(durable) / name) if durable is not None else name} is '
               f'missing; read from the bench folder instead ({where(path)})') if name else None
    return path, False, warning


def arm_source(spec: ArmSpec, bench: Path, baseline: Path, durable: Path | None) -> tuple:
    """(path, durable, warning) for an arm's source: eval-final.json for A0, else bench_source."""
    if spec.source == 'baseline':
        return baseline, True, None
    return bench_source(spec.source, bench, durable)


def strata_source(bench: Path, durable: Path | None) -> tuple:
    """(path, durable, warning) for the strata's recorded query terms (bench_source of data/eval.jsonl)."""
    return bench_source(STRATA_TERMS, bench, durable)


def load_arms(items: list, bench: Path = BENCH, baseline: Path = BASELINE, names=None,
              durable: Path | None = EVIDENCE) -> list:
    """Each arm's recorded ranked lists, re-scored with legal_search.metrics.summarise; refuses a source whose
    re-scored figures differ from the recorded ones (the source changed since the spec cited it). Sources with a
    durable copy (DURABLE) are read from `durable` when present, else from the bench with a warning."""
    arms = []
    for spec in ARMS:
        if names is not None and spec.name not in names:
            continue
        path, is_durable, warning = arm_source(spec, bench, baseline, durable)
        if spec.source == 'baseline':
            ranked = {row['id']: tuple(tuple(k) for k in row['ranked']) for row in
                      json.loads(path.read_text(encoding='utf-8'))['items']}
        else:
            ranked = _rows(path, spec.cfg)
        missing = [item.id for item in items if item.id not in ranked]
        if missing:
            raise ValueError(f'{spec.name}: {path} has no ranked list for {len(missing)} items')
        overall = summarise([Scored(i.law, i.expected, ranked[i.id]) for i in items])['overall']
        recomputed = (overall['recall@5'], overall['hit@5'], overall['mrr'])
        if recomputed != spec.recorded:
            raise ValueError(f'{spec.name}: re-scored {recomputed} from {path}, recorded {spec.recorded}')
        arms.append(Arm(spec, ranked, overall, sha256_file(path), where(path), is_durable, warning))
    return arms


def load_split(path: Path, items: list) -> dict:
    """split.json: item id -> 'A' or 'B', for exactly the eval set's ids (rag-bench data/split.json; T-B2's
    settings were tuned on half A). In the file's key order, not the eval set's: the bench's py/report.py
    bootstrap() takes a scope's ids in that order (line 22), and score_field does the same."""
    split = json.loads(Path(path).read_text(encoding='utf-8'))
    ids = {item.id for item in items}
    if not isinstance(split, dict) or set(split) != ids:
        raise ValueError(f'{where(path)}: its ids are not the eval set\'s')
    if any(half not in HALVES for half in split.values()):
        raise ValueError(f'{where(path)}: a half other than A or B')
    sizes = Counter(split.values())
    if sizes['A'] != sizes['B']:
        raise ValueError(f'{where(path)}: halves of {sizes["A"]} and {sizes["B"]} items, not two equal halves')
    return dict(split)


def resolve_split(given: Path | None, bench: Path = BENCH) -> tuple:
    """(path, warning): the split given, else the durable copy, else the bench's with a warning. Refused when the
    one it would read is missing."""
    if given is not None:
        if not Path(given).is_file():
            raise Refused(f'--split: no file {given}')
        return Path(given), None
    if SPLIT.is_file():
        return SPLIT, None
    fallback = Path(bench) / SPLIT_IN_BENCH
    if not fallback.is_file():
        raise Refused(f'split.json: neither the durable copy {where(SPLIT)} nor the bench\'s {where(fallback)} exists; '
                      'pass --split')
    return fallback, f'split.json: the durable copy {where(SPLIT)} is missing; read from the bench ({where(fallback)})'


def split_source(path: Path) -> dict:
    """The split as the reports record it: its path, its sha256, and whether that is the pinned bench split."""
    sha = sha256_file(path)
    return {'path': where(path), 'sha256': sha, 'pinned': sha == SPLIT_SHA256}


def t_b2_source(bench: Path = BENCH, baseline: Path = BASELINE, durable: Path | None = EVIDENCE) -> dict:
    """Where T-B2's rows would be read from (arm_source), with their sha256 (None when the file is missing), without
    loading the library: --w2-decide checks it before anything else is read."""
    spec = next(spec for spec in ARMS if spec.name == DECIDING['against'])
    path, is_durable, _ = arm_source(spec, bench, baseline, durable)
    return {'path': where(path), 'sha256': sha256_file(path) if Path(path).is_file() else None,
            'durable': is_durable}


def term_share(terms: list, text: str) -> float:
    """The share of query terms that prefix-match the article's normalised words (Postgres `term:*`)."""
    words = set(normalize(text).split())
    return sum(1 for term in terms if any(word.startswith(term) for word in words)) / len(terms)


def derive_strata(items: list, texts: dict, terms: Path) -> dict:
    """Spec «The miss pattern»: an item's stratum is the share of its `query` terms that prefix-match its best single
    expected article. The terms are the recorded legal_search.db.query_terms(query) in the bench's data/eval.jsonl
    (written by py/export_corpus.py:40), since db.py needs psycopg: `terms` is that file or its durable copy
    (strata_source). Checked against the spec's counts."""
    recorded = {}
    with open(terms, encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            recorded[row['id']] = row
    strata = {}
    for item in items:
        row = recorded.get(item.id)
        if row is None or row['query'] != item.query or {tuple(e) for e in row['expected']} != set(item.expected):
            raise ValueError(f'{item.id}: the bench eval row differs from the eval set')
        share = max(term_share(row['terms'], texts[key]) for key in item.expected)
        stratum = 'under' if share < 0.5 else 'all' if share == 1 else 'half'
        strata[item.id] = {'stratum': stratum, 'share': round(share, 4), 'terms': len(row['terms'])}
    sizes = Counter(row['stratum'] for row in strata.values())
    if dict(sizes) != STRATUM_SIZES or any(strata[i]['stratum'] != 'under' for i in NEVER_REACHED) \
            or strata[TRACKED]['stratum'] != 'half':
        raise ValueError(f'the derived strata {dict(sizes)} differ from the spec\'s «The miss pattern»')
    return strata


# Laws held, bootstrap ---------------------------------------------------------------------------------------------

def laws_held(given: list | None, mapper: Mapper, lines: list, slugs: set, allow_unevidenced: bool = False) -> dict:
    """The laws his corpus holds: those given with --laws-held, else those inferred from his chunks. The evidence
    is computed either way. A given law that no chunk of his comes from is refused unless allow_unevidenced, and
    an inferred law that was not given is warned about: either one changes which items are decisive."""
    if given:
        unknown = sorted(set(given) - slugs)
        if unknown:
            raise Refused(f'--laws-held names laws the registry does not have: {", ".join(unknown)}')
    evidence, inferred = law_evidence(mapper, lines)
    if not given:
        return {'laws': inferred, 'source': 'inferred', 'evidence': dict(sorted(evidence.items())),
                'inferred': inferred, 'warnings': []}
    laws = sorted(set(given))
    unevidenced = [law for law in laws if not evidence.get(law)]
    if unevidenced and not allow_unevidenced:
        raise Refused(f'--laws-held names laws that none of his chunks comes from: {", ".join(unevidenced)}. Their '
                      'items would count as his failures. Check his --list-datasets facts or his declaration, or '
                      'pass --allow-unevidenced-laws')
    warnings = [f'given, but no chunk of his comes from it: {law}' for law in unevidenced]
    warnings += [f'given, but the best source of only {evidence[law]} of his chunks (inference needs '
                 f'{INFER_MIN_CHUNKS}): {law}' for law in laws if 0 < evidence.get(law, 0) < INFER_MIN_CHUNKS]
    warnings += [f'not given, but inferred from his chunks: {law} (its items count as «lacking», not as his '
                 'failures)' for law in inferred if law not in laws]
    return {'laws': laws, 'source': 'given', 'evidence': dict(sorted(evidence.items())), 'inferred': inferred,
            'warnings': warnings}


def law_evidence(mapper: Mapper, lines: list) -> tuple:
    """(chunks per law, laws inferred held). Each chunk counts once, for the law of its best source, and only when
    that source matches 8 tokens or more. Counting every article a chunk maps would credit laws that only share
    wording (chunks cut from five laws' articles map 3 or more articles of all 22 laws), and a short article is
    matched by text that is not law."""
    evidence = Counter()
    for line in lines:
        for chunk in line['chunks']:
            source = mapper.best_source(chunk['content'] or '')
            if source is not None and source[1] >= INFER_MIN_TOKENS:
                evidence[source[0][0]] += 1
    return evidence, sorted(law for law, count in evidence.items() if count >= INFER_MIN_CHUNKS)


def own_laws_held(mapper: Mapper, lines: list, slugs: set) -> dict:
    """An own run holds our whole corpus: every registry law (the manifest's 22 documents, one per law), and no
    article is lacking. The evidence is computed as for W1 and reported. A law that is the best source of fewer
    than INFER_MIN_CHUNKS returned chunks gets a note worded for our corpus: it says what retrieval returned, not
    that the dataset lacks the law, and it moves no item out of the held scopes."""
    evidence, inferred = law_evidence(mapper, lines)
    few = [law for law in sorted(slugs) if evidence.get(law, 0) < INFER_MIN_CHUNKS]
    notes = [f'{law} is the best source ({INFER_MIN_TOKENS}+ tokens) of {evidence.get(law, 0)} returned chunks, fewer '
             f'than {INFER_MIN_CHUNKS}; the dataset holds it, so this is what retrieval returned, not a missing law'
             for law in few]
    return {'laws': sorted(slugs), 'source': OWN_LABEL, 'evidence': dict(sorted(evidence.items())),
            'inferred': inferred, 'warnings': [], 'notes': notes}


def bootstrap(diffs: list, n: int = RESAMPLES, seed: int = SEED) -> dict | None:
    """Paired bootstrap of the mean per-item difference, as the bench's py/report.py bootstrap() (lines 21-26):
    a fresh random.Random(seed) per interval, n resamples of rng.choice per item, the 2.5% and 97.5% means. An end
    within ZERO_TOLERANCE of zero is zero: float residue never reads as «above» or «below»."""
    if not diffs:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    lo, hi = means[int(0.025 * n)], means[int(0.975 * n) - 1]
    return {'items': len(diffs), 'mean': round(sum(diffs) / len(diffs), 4), 'lo': round(lo, 4), 'hi': round(hi, 4),
            'excludes_zero_above': lo > ZERO_TOLERANCE, 'excludes_zero_below': hi < -ZERO_TOLERANCE,
            'up': sum(1 for d in diffs if d > 0), 'down': sum(1 for d in diffs if d < 0)}


# Scoring one field -----------------------------------------------------------------------------------------------

def _mean(values: list) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _reading(decisive: list, intervals: bool, held_items: int) -> str | None:
    if not intervals:
        return None
    if not held_items:
        return 'cannot be read: no item is on a law his corpus holds'
    return 'beats with an interval excluding zero' if decisive else 'does not beat: no decisive interval excludes zero'


def lacks(item: Item, held: set, lacking_articles: frozenset) -> str | None:
    """Why his corpus cannot hold the item's answer: 'law' when its law is not held, 'articles' when every
    expected article is one his copy is known to lack (--articles-lacking); None when the item is held."""
    if item.law not in held:
        return 'law'
    if item.expected <= lacking_articles:
        return 'articles'
    return None


def score_field(field: str, items: list, lines: dict, arms: list, mapper: Mapper, texts: dict, strata: dict,
                held: set, intervals: bool = True, strict: bool = False,
                lacking_articles: frozenset = frozenset(), halves: dict | None = None) -> dict:
    """W1 on one field against each arm of that field, at each arm's budget. `lines` maps item id -> result line.
    Each arm is scored two ways: by its ranked keys (legal_search.metrics, as the spec scores every arm), and
    through the same mapping rule applied to the text it serves («through the rule»), which credits it, as W1
    is credited, for an expected article whose tokens another served article holds. `strict` (self-check only)
    lets a W1 chunk count only for articles in the arm's own top 5. `halves` (item id -> 'A' or 'B', from
    split.json) adds the scopes half_A and half_B: the held items of each half."""
    why = {i.id: lacks(i, held, lacking_articles) for i in items}
    # The bootstrap resamples by position, so the order of a scope's ids moves its interval's ends. With a split,
    # every scope takes split.json's key order, as the bench's report.py bootstrap() does (line 22); without one,
    # the eval set's order.
    order = list(halves) if halves else [i.id for i in items]
    if sorted(order) != sorted(i.id for i in items):
        raise ValueError('the halves do not name exactly the items')
    ids_in = {
        'all': order,
        'held': [i for i in order if why[i] is None],
        'stratum': [i for i in order if strata[i]['stratum'] == 'under'],
        'stratum_held': [i for i in order if strata[i]['stratum'] == 'under' and why[i] is None],
        'lacking': [i for i in order if why[i] is not None],
    }
    half_scopes = [f'half_{half}' for half in HALVES] if halves else []
    for half in HALVES if halves else ():
        ids_in[f'half_{half}'] = [i for i in order if halves[i] == half and why[i] is None]
    rows = {i.id: {'id': i.id, 'law': i.law, 'stratum': strata[i.id]['stratum'], 'held': why[i.id] is None,
                   'lacks': why[i.id], **({'half': halves[i.id]} if halves else {}),
                   'status': lines[i.id]['status'] if i.id in lines else 'missing',
                   'chunks_returned': len(lines[i.id]['chunks']) if i.id in lines else 0, 'arms': {}} for i in items}
    report = {'lines': Counter(row['status'] for row in rows.values()),
              'not_ok': sorted(i for i, row in rows.items() if row['status'] != 'ok'), 'arms': {}}
    for arm in arms:
        for item in items:
            line = lines.get(item.id)
            chunks = [c['content'] or '' for c in line['chunks']] if line and line['status'] == 'ok' else []
            top = arm.ranked[item.id][:TOP]
            budget = served_chars(top, texts)
            allowed = frozenset(top) if strict else None
            w1 = {rule: score_chunks(mapper, chunks, budget, rule, item.expected, allowed) for rule in RULES}
            through = score_chunks(mapper, [texts[key] for key in top], budget, RULES[0], item.expected)
            rows[item.id]['arms'][arm.spec.name] = {
                'budget_chars': budget, **w1[RULES[0]],
                'other_rules': {rule: {'reached': w1[rule]['reached'], 'recall': w1[rule]['recall'],
                                       'chunks_counted': w1[rule]['chunks_counted']} for rule in RULES[1:]},
                'arm_reached': hit_at(item.expected, top, TOP),
                'arm_recall': recall_at(item.expected, top, TOP),
                'arm_rule_reached': through['reached'],
                'arm_rule_recall': through['recall'],
            }
        cells = {i: rows[i]['arms'][arm.spec.name] for i in rows}
        scopes = {}
        for scope, ids in ids_in.items():
            scopes[scope] = {
                'items': len(ids),
                'w1_reached': sum(int(cells[i]['reached']) for i in ids),
                'arm_reached': sum(int(cells[i]['arm_reached']) for i in ids),
                'w1_recall': _mean([cells[i]['recall'] for i in ids]),
                'arm_recall': _mean([cells[i]['arm_recall'] for i in ids]),
                'arm_rule_reached': sum(int(cells[i]['arm_rule_reached']) for i in ids),
                'arm_rule_recall': _mean([cells[i]['arm_rule_recall'] for i in ids]),
                **{f'w1_recall_{rule}': _mean([cells[i]['other_rules'][rule]['recall'] for i in ids])
                   for rule in RULES[1:]},
                **{f'w1_reached_{rule}': sum(int(cells[i]['other_rules'][rule]['reached']) for i in ids)
                   for rule in RULES[1:]},
            }
        diffs = {}
        if intervals:
            for scope in ('all', 'held', 'stratum', 'stratum_held', *half_scopes):
                ids = ids_in[scope]
                diffs[f'{scope}_recall'] = bootstrap([cells[i]['recall'] - cells[i]['arm_recall'] for i in ids])
                diffs[f'{scope}_reached'] = bootstrap([cells[i]['reached'] - cells[i]['arm_reached'] for i in ids])
            for scope in ('held', 'stratum_held', *half_scopes):
                diffs[f'{scope}_recall_vs_rule'] = bootstrap(
                    [cells[i]['recall'] - cells[i]['arm_rule_recall'] for i in ids_in[scope]])
        decisive = [name for name in ('held_recall', 'stratum_held_recall')
                    if diffs.get(name) and diffs[name]['excludes_zero_above']]
        decisive_rule = [name for name in ('held_recall_vs_rule', 'stratum_held_recall_vs_rule')
                         if diffs.get(name) and diffs[name]['excludes_zero_above']]
        per_law = {}
        for law in sorted({i.law for i in items}):
            ids = [i.id for i in items if i.law == law]
            per_law[law] = {'items': len(ids), 'held': law in held,
                            'w1_reached': sum(int(cells[i]['reached']) for i in ids),
                            'arm_reached': sum(int(cells[i]['arm_reached']) for i in ids),
                            'w1_recall': _mean([cells[i]['recall'] for i in ids]),
                            'arm_recall': _mean([cells[i]['arm_recall'] for i in ids])}
        report['arms'][arm.spec.name] = {
            'label': arm.spec.label, 'cfg': arm.spec.cfg, 'source_sha256': arm.source_sha256,
            'recorded_all80': dict(zip(('recall@5', 'hit@5', 'mrr'), arm.spec.recorded)),
            'budget_chars_median': statistics.median(cells[i]['budget_chars'] for i in rows),
            'scopes': scopes, 'intervals': diffs, 'per_law': per_law,
            'decision_c': {'beats': bool(decisive), 'basis': decisive,
                           'reading': _reading(decisive, intervals, len(ids_in['held'])),
                           'beats_through_rule': bool(decisive_rule), 'basis_through_rule': decisive_rule,
                           'reading_through_rule': _reading(decisive_rule, intervals, len(ids_in['held']))},
        }
    report['lines'] = dict(report['lines'])
    report['items'] = [rows[i.id] for i in items]
    return report


def best_arm(arms: list, field: str) -> str:
    """Our best arm on a field: the highest recorded all-80 recall@5, then the first listed."""
    return max((arm for arm in arms if arm.spec.field == field), key=lambda arm: arm.spec.recorded[0]).spec.name


# Context, scoring a file, the self-check -------------------------------------------------------------------------

@dataclass
class Context:
    texts: dict
    items: list
    set_sha256: str
    corpus_sha256: str
    arms: list
    strata: dict
    mapper: Mapper
    slugs: set
    halves: dict = dataclasses.field(default_factory=dict)  # item id -> 'A' or 'B', in split.json's key order
    sources: dict = dataclasses.field(default_factory=dict)  # each file read: path, sha256, durable or pinned
    warnings: list = dataclasses.field(default_factory=list)  # a durable copy missing, the bench read instead


def missing_sources(bench: Path = BENCH, baseline: Path = BASELINE, durable: Path | None = EVIDENCE) -> list:
    """The files load_context would read that are not there: each arm's source (arm_source) and the strata's
    recorded query terms (strata_source), as the reports print paths."""
    paths = [arm_source(spec, bench, baseline, durable)[0] for spec in ARMS] + [strata_source(bench, durable)[0]]
    return list(dict.fromkeys(where(path) for path in paths if not Path(path).is_file()))


def load_context(bench: Path = BENCH, baseline: Path = BASELINE, evalset: Path = EVALSET, split: Path | None = None,
                 durable: Path | None = EVIDENCE) -> Context:
    missing = missing_sources(bench, baseline, durable)
    if missing:
        raise Refused(f'missing: {", ".join(missing)}. Each source is read from its durable copy in p3-evidence when '
                      'that is present, else from the scratch bench folder (README, «Where the arms are read from»). '
                      'Restore the copies or the bench folder, or pass --bench')
    texts = library_texts()
    items, set_sha = load_evalset(evalset)
    corpus_sha = corpus_sha256(texts)
    run = json.loads(baseline.read_text(encoding='utf-8'))['run']
    if (set_sha, corpus_sha) != (run['set_sha256'], run['corpus_sha256']):
        raise ValueError('the eval set or the corpus differs from the one the recorded arms were run on')
    split_path, split_warning = resolve_split(split, bench)
    arms = load_arms(items, bench, baseline, durable=durable)
    terms, terms_durable, terms_warning = strata_source(bench, durable)
    sources = {'arms': {arm.spec.name: {'path': arm.source_path, 'sha256': arm.source_sha256, 'durable': arm.durable}
                        for arm in arms},
               'split': split_source(split_path),
               'strata_terms': {'path': where(terms), 'sha256': sha256_file(terms), 'durable': terms_durable}}
    warnings = list(dict.fromkeys(w for w in (*(arm.warning for arm in arms), split_warning, terms_warning) if w))
    return Context(texts, items, set_sha, corpus_sha, arms, derive_strata(items, texts, terms), Mapper(texts),
                   {key[0] for key in texts}, load_split(split_path, items), sources, warnings)


# Own runs (W2) --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class OwnRun:
    manifest: dict
    manifest_sha256: str
    manifest_path: str
    results_sha256: str
    arm: str  # 'v3' or 'rt', from the file name, checked against the header's settings
    path: Path  # the results file, resolved


_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_HEX40 = re.compile(r'[0-9a-f]{40}')  # used with fullmatch
_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise Refused(f'the W2 manifest: {message}')


def is_hosted(manifest: dict) -> bool:
    """A W2 manifest of the hosted run (embedder.via hosted-openrouter), not the built-in TEI's."""
    embedder = manifest.get('embedder') if isinstance(manifest, dict) else None
    return isinstance(embedder, dict) and embedder.get('via') == W2_HOSTED_VIA


def load_w2_manifest(path: Path) -> dict:
    """The W2 manifest (README, «Own runs (W2)»: the shared contract the ingest tool writes), checked key by key.
    It must record the exact chunk match (all_match true) and one document per law (22). A hosted run's manifest
    (is_hosted) has the same contract with hosted_embedder in place of tei_wait_patch."""
    try:
        manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f'the W2 manifest {where(path)} is not a readable JSON file') from None
    _need(isinstance(manifest, dict), 'it must be a JSON object')
    hosted = is_hosted(manifest)
    keys = W2_HOSTED_MANIFEST_KEYS if hosted else W2_MANIFEST_KEYS
    extra, missing = sorted(set(manifest) - keys), sorted(keys - set(manifest))
    _need(not extra, f'keys outside the contract: {", ".join(map(str, extra))}')
    _need(not missing, f'missing keys: {", ".join(missing)}')
    m = manifest
    _need(_whole(m['w2']) and m['w2'] == 1, '"w2" must be 1')
    _need(isinstance(m['created_at'], str) and re.match(r'^\d{4}-\d{2}-\d{2}T', m['created_at']) is not None,
          '"created_at" must be an ISO-8601 time')
    _need(m['engine'] in W2_ENGINES, f'"engine" must be one of {", ".join(W2_ENGINES)}')
    embedder = m['embedder']
    if hosted:
        _need(set(embedder) == W2_EMBEDDER_KEYS and isinstance(embedder['name'], str) and embedder['name'].strip()
              and embedder['revision'] is None,
              f'"embedder" of a hosted run must hold its model name, revision null and via {W2_HOSTED_VIA}')
    else:
        _need(isinstance(embedder, dict) and set(embedder) == W2_EMBEDDER_KEYS
              and all(isinstance(embedder[k], str) and embedder[k].strip() for k in W2_EMBEDDER_KEYS),
              '"embedder" must hold name, revision and via, each a non-empty string')
        _need(embedder['via'] == W2_VIA, f'"embedder.via" must be {W2_VIA}: the server\'s built-in TEI')
        _need(_HEX40.fullmatch(embedder['revision']) is not None,
              '"embedder.revision" must be the 40 lower-case hex commit the model files were fetched at')
    _need(m['ragflow_version'] == RAGFLOW_VERSION, f'"ragflow_version" must be exactly {RAGFLOW_VERSION}')
    _need(isinstance(m['ragflow_image_digest'], str) and _DIGEST.search(m['ragflow_image_digest']) is not None,
          '"ragflow_image_digest" must hold a sha256:<64 hex> digest')
    _need(isinstance(m['dataset_id'], str) and _HEX32.match(m['dataset_id']) is not None,
          '"dataset_id" must be 32 lower-case hex characters')
    _need(isinstance(m['language'], str) and bool(m['language'].strip()), '"language" must be a non-empty string')
    _need(_whole(m['document_count']) and m['document_count'] == W2_DOCUMENTS,
          f'"document_count" must be {W2_DOCUMENTS}: one generated file per law')
    _need(_whole(m['chunk_count']) and m['chunk_count'] > 0, '"chunk_count" must be a whole number above 0')
    _need(_whole(m['predicted_chunk_count']) and m['predicted_chunk_count'] >= 0,
          '"predicted_chunk_count" must be a whole number')
    _need(m['all_match'] is True, '"all_match" is not true: the dataset\'s chunks did not match the predictor exactly, '
                                  'so it is not the pinned dataset; nothing is scored')
    _need(m['predicted_chunk_count'] == m['chunk_count'],
          '"predicted_chunk_count" differs from "chunk_count", yet "all_match" is true')
    for name in ('canvas_sha256', 'upload_manifest_sha256'):
        _need(isinstance(m[name], str) and _HEX64.match(m[name]) is not None,
              f'"{name}" must be 64 lower-case hex characters')
    _need(m['file_shape'] == W2_FILE_SHAPE, f'"file_shape" must be {W2_FILE_SHAPE}, the shape pinned with the rule')
    _need(_whole(m['embedding_batch_size']) and m['embedding_batch_size'] >= 1,
          '"embedding_batch_size" must be a whole number, 1 or more')
    _need(_whole(m['max_concurrent_tasks']) and m['max_concurrent_tasks'] >= 1,
          '"max_concurrent_tasks" must be a whole number, 1 or more')
    if hosted:
        _check_hosted_embedder(m['hosted_embedder'], embedder['name'])
        return manifest
    patch = m['tei_wait_patch']
    _need(isinstance(patch, dict) and set(patch) == W2_TEI_WAIT_KEYS,
          f'"tei_wait_patch" must hold exactly {", ".join(sorted(W2_TEI_WAIT_KEYS))}')
    _need(patch['file'] == W2_TEI_WAIT_FILE, f'"tei_wait_patch.file" must be {W2_TEI_WAIT_FILE}')
    for name in ('image_sha256', 'patched_sha256'):
        _need(isinstance(patch[name], str) and _HEX64.fullmatch(patch[name]) is not None,
              f'"tei_wait_patch.{name}" must be 64 lower-case hex characters')
    _need(patch['image_sha256'] != patch['patched_sha256'],
          '"tei_wait_patch": the patched file has the image file\'s sha256, so nothing was changed')
    lines = patch['changed_lines']
    _need(isinstance(lines, list) and len(lines) == 2 and all(_whole(n) and n > 0 for n in lines),
          '"tei_wait_patch.changed_lines" must be two line numbers')
    _need(_whole(patch['wait_s']) and patch['wait_s'] > W2_TEI_WAIT_SHIPPED,
          f'"tei_wait_patch.wait_s" must be a whole number above {W2_TEI_WAIT_SHIPPED}')
    rows = patch['diff'].split('\n') if isinstance(patch['diff'], str) else []
    _need(rows[:2] == [f'--- a/{W2_TEI_WAIT_FILE}', f'+++ b/{W2_TEI_WAIT_FILE}'],
          f'"tei_wait_patch.diff" must be the unified diff of {W2_TEI_WAIT_FILE} (a/ and b/)')
    removed, added = [r for r in rows[2:] if r.startswith('-')], [r for r in rows[2:] if r.startswith('+')]
    _need(len(removed) == len(added) == len(lines)
          and all(r.endswith(f'timeout={W2_TEI_WAIT_SHIPPED})') for r in removed)
          and all(r.endswith(f'timeout={patch["wait_s"]})') for r in added),
          f'"tei_wait_patch.diff" must change only its changed lines, each timeout={W2_TEI_WAIT_SHIPPED} to the wait')
    return manifest


def _check_hosted_embedder(hosted, name: str) -> None:
    """The hosted run's hosted_embedder: exactly W2_HOSTED_KEYS, OpenRouter at its one base URL (the one host the
    proxy allows), the manifest embedder's model, an instance RAGFlow accepts, the owner's data-policy note."""
    _need(isinstance(hosted, dict) and set(hosted) == W2_HOSTED_KEYS,
          f'"hosted_embedder" must hold exactly {", ".join(sorted(W2_HOSTED_KEYS))}')
    _need(hosted['factory'] == W2_HOSTED_FACTORY, f'"hosted_embedder.factory" must be {W2_HOSTED_FACTORY}')
    _need(hosted['base_url'] == W2_HOSTED_BASE_URL, f'"hosted_embedder.base_url" must be {W2_HOSTED_BASE_URL}')
    _need(hosted['model'] == name, '"hosted_embedder.model" must be the embedder\'s name')
    _need(isinstance(hosted['instance'], str) and re.fullmatch(r'[0-9A-Za-z_-]+', hosted['instance']) is not None
          and hosted['instance'] != 'default', '"hosted_embedder.instance" must be a RAGFlow instance name, not default')
    order = hosted['provider_order']
    _need(order is None or (isinstance(order, str) and bool(order.strip())),
          '"hosted_embedder.provider_order" must be null or a provider slug')
    _need(isinstance(hosted['data_policy'], str) and bool(hosted['data_policy'].strip()),
          '"hosted_embedder.data_policy" must be the owner\'s note')


def tei_wait_warning(patch: dict) -> str | None:
    """A warning when the manifest's TEI-wait patch is not the owner's approved one (W2_TEI_WAIT_APPROVED)."""
    off = [k for k, v in W2_TEI_WAIT_APPROVED.items() if patch[k] != v]
    if not off:
        return None
    a = W2_TEI_WAIT_APPROVED
    return (f'the TEI-wait patch is not the approved one ({", ".join(off)} not as approved: image file '
            f'{a["image_sha256"][:12]}, patched file {a["patched_sha256"][:12]}, lines {a["changed_lines"]}, '
            f'{a["wait_s"]} s); it is operational, so no deciding gap, and check_tei_wait.py refuses such a patch '
            'before any parse')


def registry_slugs(registry: Path = REGISTRY) -> set:
    """The law slugs of the registry (laws.json): the W2 corpus is one file <slug>.md per law."""
    return {law.slug for law in load_registry(registry)}


def open_own_run(results_path: Path, manifest_path: Path, package: Path = DEFAULT_PACKAGE,
                 root: Path = OWN_ROOT, registry: Path = REGISTRY, hosted_root: Path | None = HOSTED_ROOT) -> tuple:
    """(OwnRun, Results) for a results file of our own W2 run, else Refused. It replaces the third-party gates
    (the quarantine copy, the person's screen) with one that ties the file to our dataset: the file sits directly
    in `root`/<engine>/ beside its W2 manifest; the manifest passes load_w2_manifest; the header names exactly the
    manifest's dataset, with its document and chunk counts; its hashes are the package's run_w1.py and
    w1-queries.jsonl; its settings are the arm's; every returned chunk's document name is one of the registry's
    <slug>.md files, the only files the ingest tool uploads. Every read_results screen runs. Refusals quote no
    header or chunk value. The hosted run's files sit under `hosted_root` instead, and each root takes only its own
    kind of manifest (is_hosted)."""
    given = Path(results_path)
    resolved = Path(os.path.realpath(given))
    local = Path(os.path.realpath(root))
    hosted_base = Path(os.path.realpath(hosted_root)) if hosted_root is not None else None
    under_hosted = hosted_base is not None and resolved.is_relative_to(hosted_base)
    base = hosted_base if under_hosted else local
    if not resolved.is_relative_to(base):
        raise Refused(f'--own-run scores only a file under {where(local)}/<engine>/'
                      + (f' or, for the hosted run, {where(hosted_base)}/<engine>/' if hosted_base else '')
                      + f' (this one resolves to {resolved}). A file from Walid is scored from quarantine, without '
                      '--own-run')
    if resolved.parent.parent != base:
        raise Refused(f'--own-run scores only a file directly in {where(base)}/<engine>/, not in a folder below it')
    if resolved.name != given.name:
        raise Refused(f'{given} is a link to another file; score the file itself')
    match = OWN_RESULTS.match(resolved.name)
    if not match:
        raise Refused(f'an own run\'s results file is named w2-results-v3.jsonl or w2-results-rt.jsonl, not {given.name}')
    beside = resolved.parent / W2_MANIFEST
    manifest_resolved = Path(os.path.realpath(manifest_path))
    if manifest_resolved != beside:
        raise Refused(f'--manifest must be the {W2_MANIFEST} beside the results file ({where(beside)})')
    if not manifest_resolved.is_file():
        raise Refused(f'no {W2_MANIFEST} beside the results file ({where(beside)}): the ingest tool writes it when it '
                      'creates the dataset; without it nothing ties this file to our dataset')
    manifest = load_w2_manifest(manifest_resolved)
    if is_hosted(manifest) and not under_hosted:
        raise Refused(f'a hosted W2 manifest is scored only under {where(hosted_base or HOSTED_ROOT)}/<engine>/, '
                      'not beside the local runs')
    if under_hosted and not is_hosted(manifest):
        raise Refused(f'a built-in W2 manifest is scored only under {where(local)}/<engine>/, not beside the hosted run')
    if resolved.parent.name != manifest['engine']:
        raise Refused(f'the results sit in {resolved.parent.name}/, but the manifest\'s engine is {manifest["engine"]}')
    results = read_results(resolved)  # every screen of the W1 contract
    header = results.header
    datasets = header['datasets']
    if len(datasets) != 1 or datasets[0]['id'] != manifest['dataset_id']:
        raise Refused(f'the header does not name exactly the manifest\'s dataset {manifest["dataset_id"]}: this file '
                      'was not run on our W2 dataset')
    for name in ('document_count', 'chunk_count'):
        if datasets[0][name] != manifest[name]:
            raise Refused(f'the header\'s datasets[1].{name} differs from the manifest\'s {manifest[name]}')
    for name, file in (('script_sha256', 'run_w1.py'), ('queries_sha256', 'w1-queries.jsonl')):
        ours = Path(package) / file
        if not ours.is_file():
            raise Refused(f'the package has no {file} ({where(ours)}) to compare the header\'s {name} with')
        if header[name] != sha256_file(ours):
            raise Refused(f'the header\'s {name} is not the package\'s {file}: the run did not use the frozen file')
    if header['ragflow_version'] != manifest['ragflow_version']:
        raise Refused(f'the header\'s ragflow_version is not the manifest\'s {manifest["ragflow_version"]}')
    arm = match.group(1)
    if header['settings'] != OWN_ARMS[arm]:
        raise Refused(f'the header\'s settings are not the {arm} arm\'s: {OWN_ARM_LABELS[arm]}')
    names = {f'{slug}.md' for slug in registry_slugs(registry)}
    if len(names) != manifest['document_count']:
        raise Refused(f'the registry has {len(names)} laws, not the manifest\'s {manifest["document_count"]} documents')
    other = sum(1 for line in results.lines for chunk in line['chunks'] if chunk['document_name'] not in names)
    if other:
        raise Refused(f'{other} returned chunks carry a document name that is not <registry slug>.md, the only files '
                      'the ingest tool uploads: this file was not run on our W2 dataset')
    return OwnRun(manifest, sha256_file(manifest_resolved), where(manifest_resolved), sha256_file(resolved), arm,
                  resolved), results


def load_fallback(path: Path, own: OwnRun, results) -> dict:
    """w2-fallback-<arm>.json beside the results: {field: [ids answered only by the dense-only fallback]}, one key
    per field of the results file. Each id must have an ok line with chunks in that field."""
    resolved = Path(os.path.realpath(path))
    name = OWN_FALLBACK.format(arm=own.arm)
    if resolved != own.path.parent / name:
        raise Refused(f'--fallback must be the {name} beside the results file ({where(own.path.parent / name)})')
    try:
        data = json.loads(resolved.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f'--fallback: {where(resolved)} is not a readable JSON file') from None
    fields = results.header['fields']
    if not isinstance(data, dict) or sorted(data) != sorted(fields):
        raise Refused(f'--fallback: the file must hold one list of item ids per field of the results file '
                      f'({", ".join(fields)}), and nothing else')
    answered = {(line['field'], line['id']) for line in results.lines if line['status'] == 'ok' and line['chunks']}
    for field, ids in data.items():
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise Refused(f'--fallback: {field} must be a list of distinct item ids')
        unknown = [i for i in ids if (field, i) not in answered]
        if unknown:
            raise Refused(f'--fallback: {len(unknown)} {field} ids have no ok line with chunks in the results file '
                          f'({", ".join(i for i in unknown[:10] if re.fullmatch(r"[a-z0-9-]{1,64}", i))})')
    return {'path': where(resolved), 'sha256': sha256_file(resolved),
            'fields': {field: sorted(data[field]) for field in fields}}


def field_lines(results, field: str, items: list) -> dict:
    """The result lines of one field by item id; refuses ids outside the set and text other than the frozen set's."""
    by_id = {item.id: item for item in items}
    lines, unknown, differs = {}, 0, []
    for line in results.lines:
        if line['field'] != field:
            continue
        item = by_id.get(line['id'])
        if item is None:
            unknown += 1
        elif line['sent'] != getattr(item, field):
            differs.append(line['id'])
        lines[line['id']] = line
    if unknown or differs:
        raise Refused(f'{field}: {unknown} lines name an id outside the eval set, and {len(differs)} sent other text '
                      f'than the frozen set ({", ".join(differs[:10])}); he did not run the frozen queries')
    return lines


def open_results(path: Path) -> tuple:
    """The manifest and the checked results of a quarantined file whose screen is recorded clear."""
    manifest = check_cleared(path)
    return manifest, read_results(path)


_ARTICLE = re.compile(r'^([a-z0-9]+(?:-[a-z0-9]+)*):([0-9]+)(?: (\S.*))?$')


def articles_lacking(text: str | None, texts: dict) -> frozenset:
    """--articles-lacking: comma-separated article labels, law:number or «law:number suffix» (the form the report
    prints), each one an article of our library."""
    keys = set()
    for part in (text or '').split(','):
        part = part.strip()
        if not part:
            continue
        match = _ARTICLE.match(part)
        key = (match.group(1), int(match.group(2)), match.group(3) or '') if match else None
        if key not in texts:
            raise Refused(f'--articles-lacking: {part!r} is not an article of our library (write law:number)')
        keys.add(key)
    return frozenset(keys)


def _header_facts(header: dict) -> dict:
    settings = header['settings']
    return {'fields': header['fields'], 'counts': {k: header['counts'][k] for k in sorted(COUNTS_KEYS)},
            'datasets': len(header['datasets']),
            # only run_w1.py's own setting names, and only numbers and flags: no free text from the file
            'settings': {k: v for k, v in sorted(settings.items())
                         if k in SETTING_KEYS and isinstance(v, (int, float, bool))},
            'rerank_id_sent': 'rerank_id' in settings}


def _score_fields(results, context: Context, held_laws: set, lacking_articles: frozenset = frozenset(),
                  lines_of=None) -> dict:
    """Each field present in the file, scored against the arms of that field. `lines_of(field)` may replace the
    file's lines of a field (the fallback sensitivity)."""
    scored = {}
    for field in FIELDS:
        if field in results.header['fields']:
            arms = [arm for arm in context.arms if arm.spec.field == field]
            lines = lines_of(field) if lines_of else field_lines(results, field, context.items)
            scored[field] = score_field(field, context.items, lines, arms, context.mapper, context.texts,
                                        context.strata, held_laws, lacking_articles=lacking_articles,
                                        halves=context.halves or None)
            scored[field]['best_arm'] = best_arm(context.arms, field)
    return scored


def score_results(manifest: dict, results, laws_given: list | None, context: Context,
                  lacking_articles: frozenset = frozenset(), allow_unevidenced: bool = False) -> dict:
    held = laws_held(laws_given, context.mapper, results.lines, context.slugs, allow_unevidenced)
    report = {
        'w1_score': 1,
        'results': {'sha256': manifest['files'][0]['sha256'], 'handover_id': manifest['handover_id'],
                    **_header_facts(results.header),
                    'ragflow_version': manifest['contract']['ragflow_version'],
                    'script_matches_ours': manifest['contract']['script_matches_ours'],
                    'queries_matches_ours': manifest['contract']['queries_match_ours']},
        **_common(context),
        'laws_held': held,
        'articles_lacking': {'given': [label(key) for key in sorted(lacking_articles)],
                             'items_left_out': [i.id for i in context.items
                                                if lacks(i, set(held['laws']), lacking_articles) == 'articles']},
        'fields': _score_fields(results, context, set(held['laws']), lacking_articles),
    }
    return report


# The W2 readings: the deciding one, fixed by the amendment, and the exploratory ones ------------------------------

SCOPE_NAMES = {'held': 'all', 'half_A': 'half A', 'half_B': 'half B'}  # in an own run every item is held


def _side(interval: dict | None) -> str:
    if not interval:
        return 'cannot be read'
    return ('above zero' if interval['excludes_zero_above'] else
            'below zero' if interval['excludes_zero_below'] else 'includes zero')


def w2_reading(scored: dict, against: str, scope: str, by: str = 'rule') -> dict:
    """W2 minus one arm on one scope, recall within the arm's budget: through the mapping rule (both sides' served
    text mapped the same way, the amendment's like with like) or by the arm's ranked keys."""
    arm = scored['arms'][against]
    cell = arm['scopes'][scope]
    interval = arm['intervals'].get(f'{scope}_recall_vs_rule' if by == 'rule' else f'{scope}_recall')
    return {'against': against, 'scope': scope, 'by': by, 'items': cell['items'],
            'w2_recall': cell['w1_recall'], 'w2_reached': cell['w1_reached'],
            'arm_recall': cell['arm_rule_recall' if by == 'rule' else 'arm_recall'],
            'arm_reached': cell['arm_rule_reached' if by == 'rule' else 'arm_reached'],
            'interval': interval, 'side': _side(interval)}


def server_embedder(model) -> tuple:
    """(kind, model name, provider) of the header's datasets[1].embedding_model: the server's own fact, which
    run_w1.py reads (embedding_model(): the composite name, else the stored value). v0.27.3 parses a composite
    name from the right: the last '@' field is the provider, the one before it the instance when there are three,
    the rest the model (tenant_model_service.py:206-230). kind is 'name'; 'opaque' for a 32-hex tenant-model id
    (common/misc_utils.py:50-51), which names no model; or 'none' when the server gave nothing."""
    if not isinstance(model, str) or not model.strip():
        return 'none', None, None
    if _HEX32.fullmatch(model):
        return 'opaque', None, None
    parts = model.rsplit('@', 2)
    return 'name', parts[0], parts[-1] if len(parts) > 1 else ''


def deciding_gaps(own: OwnRun, header: dict, split_sha256: str, against: dict) -> list:
    """Why an own run is not the pre-registered deciding cell; empty when it is. `header` is the results file's,
    `against` T-B2's source ({'sha256', 'durable'}: t_b2_source, or Context.sources). (embedder.via is checked by
    the manifest, and each arm's settings by open_own_run.)"""
    m, gaps = own.manifest, []
    if is_hosted(m):
        gaps.append(f'the embedder is hosted ({m["embedder"]["name"]} via {m["hosted_embedder"]["factory"]}): '
                    f'exploratory only; the deciding cell is the local {DECIDING["engine"]} run with the built-in '
                    f'{DECIDING["embedder"]}')
    if m['engine'] != DECIDING['engine']:
        gaps.append(f'the engine is {m["engine"]}, not {DECIDING["engine"]}')
    if not is_hosted(m) and m['embedder']['name'] != DECIDING['embedder']:
        gaps.append(f'the embedder is {m["embedder"]["name"]}, not {DECIDING["embedder"]}')
    if not is_hosted(m) and m['embedder']['revision'] != DECIDING['revision']:
        gaps.append(f'the embedder revision is {m["embedder"]["revision"][:12]}, not the pinned '
                    f'{DECIDING["revision"][:12]}')
    kind, name, provider = server_embedder(header['datasets'][0]['embedding_model'])
    if kind == 'none':
        gaps.append('the server reported no embedding model for the dataset, so only the unsigned manifest names it')
    elif kind == 'name' and (name != DECIDING['embedder'] or provider not in ('', DECIDING['provider'])):
        gaps.append(f'the embedding model the server reports for the dataset is not {DECIDING["embedder"]} via '
                    f'{DECIDING["provider"]}')
    if m['canvas_sha256'] != DECIDING['canvas_sha256']:
        gaps.append(f'the canvas is {m["canvas_sha256"][:12]}, not Walid\'s indexing pipeline as it is '
                    f'{DECIDING["canvas_sha256"][:12]}')
    if own.arm != DECIDING['arm']:
        gaps.append(f'the arm is {own.arm} ({OWN_ARM_LABELS[own.arm]}), not {DECIDING["arm"]}')
    if DECIDING['field'] not in header['fields']:
        gaps.append(f'the file has no {DECIDING["field"]} field')
    if split_sha256 != SPLIT_SHA256:
        gaps.append(f'split.json {split_sha256[:12]} is not the bench split {SPLIT_SHA256[:12]}')
    if not against.get('durable'):
        gaps.append(f'{DECIDING["against"]}\'s rows were not read from the durable p3-evidence copy')
    elif against.get('sha256') != T_B2_ROWS_SHA256:
        gaps.append(f'{DECIDING["against"]}\'s rows are {(against.get("sha256") or "missing")[:12]}, not the pinned '
                    f'{T_B2_ROWS_SHA256[:12]}')
    return gaps


def w2_decision(scored_query: dict | None, own: OwnRun, gaps: list, split_sha256: str) -> dict:
    """The pre-registered reading: W2 vs T-B2, query field, half B, both through the mapping rule at T-B2's budget,
    paired bootstrap 95% (seed 20261106, 10,000 resamples). «wins» only if the interval lies above zero; else
    «not shown», with a note on what that means: an interval that includes zero cannot detect a smaller effect,
    one below zero has W2 behind."""
    if gaps:
        return {'deciding_cell': False, 'why_not': gaps, 'rule': DECIDING_RULE}
    scope = f'half_{DECIDING["half"]}'
    reading = w2_reading(scored_query, DECIDING['against'], scope)
    verdict = {'above zero': 'wins', 'cannot be read': 'cannot be read'}.get(reading['side'], 'not shown')
    note = {'includes zero': f'a smaller effect cannot be detected on {reading["items"]} items',
            'below zero': f'W2 is behind {DECIDING["against"]} on half B: the whole interval lies below zero'
            }.get(reading['side'])
    m = own.manifest
    return {'deciding_cell': True, 'rule': DECIDING_RULE,
            'cell': {'engine': m['engine'], 'embedder': m['embedder']['name'], 'revision': m['embedder']['revision'],
                     'via': m['embedder']['via'], 'arm': own.arm, 'settings': OWN_ARM_LABELS[own.arm],
                     'field': DECIDING['field'], 'against': f'{DECIDING["against"]} (Tantivy r2|b2|t0.5|h1.0)',
                     'split_sha256': split_sha256, 'against_rows_sha256': T_B2_ROWS_SHA256,
                     'canvas_sha256': m['canvas_sha256'], 'ragflow_image_digest': m['ragflow_image_digest'],
                     'image_digest_pinned': False},
            **reading, 'verdict': verdict, 'note': note,
            'not_ok_in_scope': [row['id'] for row in scored_query['items']
                                if row.get('half') == DECIDING['half'] and row['status'] != 'ok']}


def w2_exploratory(fields: dict, deciding: bool) -> list:
    """Every other reading worth printing: all 80 and half A, T-B2's keys, the other arms, the question field."""
    out = []
    query, question = fields.get('query'), fields.get('question')
    if query and 'T-B2' in query['arms']:
        scopes = ('held', 'half_A') if deciding else ('half_B', 'held', 'half_A')
        out += [{'field': 'query', **w2_reading(query, 'T-B2', scope)} for scope in scopes]
        out.append({'field': 'query', **w2_reading(query, 'T-B2', 'half_B', by='keys')})
        out += [{'field': 'query', **w2_reading(query, name, 'half_B')} for name in query['arms'] if name != 'T-B2']
    if question and 'T-B2q' in question['arms']:
        out += [{'field': 'question', **w2_reading(question, 'T-B2q', scope)} for scope in ('half_B', 'held', 'half_A')]
        if question['best_arm'] != 'T-B2q':
            out.append({'field': 'question', **w2_reading(question, question['best_arm'], 'half_B')})
    return out


def fallback_sensitivity(fallback: dict, results, context: Context) -> dict:
    """The same scoring with the items answered only by the dense-only fallback emptied (his agent turns that
    fallback off; the HTTP route keeps it on). Exploratory only: it never decides."""
    def lines_of(field):
        emptied = set(fallback['fields'][field])
        return {i: ({**line, 'chunks': []} if i in emptied else line)
                for i, line in field_lines(results, field, context.items).items()}
    scored = _score_fields(results, context, set(context.slugs), lines_of=lines_of)
    out = {'path': fallback['path'], 'sha256': fallback['sha256'], 'fields': {}}
    for field, against in (('query', 'T-B2'), ('question', 'T-B2q')):
        if field in scored and against in scored[field]['arms']:
            out['fields'][field] = {
                'items_emptied': fallback['fields'][field],
                'readings': [w2_reading(scored[field], against, scope) for scope in ('half_B', 'held', 'half_A')]}
    return out


def score_own_run(own: OwnRun, results, context: Context, fallback: dict | None = None) -> dict:
    """An own run (W2): all 22 laws held, no article lacking, the deciding reading when the file is the deciding
    cell, the exploratory readings, and the fallback sensitivity when its evidence is given."""
    held = own_laws_held(context.mapper, results.lines, context.slugs)
    header, m = results.header, own.manifest
    kind, name, _ = server_embedder(header['datasets'][0]['embedding_model'])
    warnings = {'none': ['the header reports no embedding model: only the manifest names the embedder'],
                'opaque': ['the header\'s embedding model is an opaque tenant-model id: only the manifest names the '
                           'embedder']}.get(kind, [])
    if kind == 'name' and name != m['embedder']['name']:
        warnings.append(f'the header\'s embedding model does not name the manifest\'s embedder {m["embedder"]["name"]}')
    if not is_hosted(m):  # a hosted stack mounts no TEI-wait patch
        warnings += [w for w in (tei_wait_warning(m['tei_wait_patch']),) if w]
    split_sha = context.sources.get('split', {}).get('sha256', '')
    report = {
        'w1_score': 1, 'w2': 1,
        'results': {'sha256': own.results_sha256, 'handover_id': OWN_LABEL, 'own_run': OWN_LABEL, 'arm': own.arm,
                    'arm_settings': OWN_ARM_LABELS[own.arm], **_header_facts(header),
                    'ragflow_version': header['ragflow_version'],
                    'script_matches_ours': True, 'queries_matches_ours': True,  # open_own_run refuses otherwise
                    'gates_skipped': ['the quarantine copy', 'the person\'s screen'],
                    'warnings': warnings},
        'w2_manifest': {'path': own.manifest_path, 'sha256': own.manifest_sha256, **m},
        **_common(context, who='W2'),
        'laws_held': held,
        'articles_lacking': {'given': [], 'items_left_out': []},
        'fields': _score_fields(results, context, set(context.slugs)),
    }
    gaps = deciding_gaps(own, header, split_sha, context.sources.get('arms', {}).get(DECIDING['against'], {}))
    report['w2_decision'] = w2_decision(report['fields'].get('query'), own, gaps, split_sha)
    report['w2_exploratory'] = w2_exploratory(report['fields'], not gaps)
    if fallback is not None:
        report['fallback_sensitivity'] = fallback_sensitivity(fallback, results, context)
    return report


def _common(context: Context, who: str = 'W1') -> dict:
    return {
        'eval_set_sha256': context.set_sha256, 'corpus_sha256': context.corpus_sha256,
        'rules': {'mapping': 'a chunk retrieves an n-token article when some '
                             f'{"n" if WINDOW_FACTOR == 1 else f"{WINDOW_FACTOR}n"} consecutive chunk '
                             'tokens hold ceil(n/2) of its tokens in order (LCS of that stretch and the article); '
                             'tokens = legal_search.normalize.tokens; an article with no token never maps',
                  'mapping_owner_call': 'the stretch limit is an agent\'s reading of «in order» (‡); without it, '
                                        'runs of neighbouring articles map articles they do not hold',
                  'budget': f'characters of article text in the arm\'s top {TOP}; {who} chunks count in rank order '
                            'until their characters reach it',
                  'crossing_rule': RULES[0], 'other_rules_reported': list(RULES[1:]),
                  'bootstrap': {'resamples': RESAMPLES, 'seed': SEED, 'source': 'rag-bench py/report.py:21-26',
                                'order': 'each scope\'s items in split.json key order, as report.py:22 takes them '
                                         '(the eval set\'s order only when no split is loaded)',
                                'zero_tolerance': ZERO_TOLERANCE},
                  'decision_c': 'beats when the 95% interval of W1 minus the arm lies above zero on recall within '
                                'budget, on the held items or on the held under-half stratum'},
        'strata': {'under': [i for i, s in context.strata.items() if s['stratum'] == 'under'],
                   'never_reached': list(NEVER_REACHED), 'tracked': TRACKED,
                   'sizes': dict(Counter(s['stratum'] for s in context.strata.values()))},
        'halves': {'sizes': dict(sorted(Counter(context.halves.values()).items())),
                   'note': 'split.json: T-B2\'s settings were tuned on half A; the held-out half is B'},
        'sources': context.sources,
        'source_warnings': context.warnings,
    }


def split_half(text: str) -> list:
    """Two chunks at the first whitespace after which the first holds ceil(n/2) tokens; they join back to `text`."""
    want = need(len(tokens(text)))
    cuts = [match.start() for match in re.finditer(r'\s', text)]
    lo, hi = 0, len(cuts)
    while lo < hi:
        mid = (lo + hi) // 2
        if len(tokens(text[:cuts[mid]])) >= want:
            hi = mid
        else:
            lo = mid + 1
    return [text] if lo == len(cuts) else [text[:cuts[lo]], text[cuts[lo]:]]


def synthetic_lines(arm: Arm, items: list, texts: dict, variant: str) -> dict:
    """Result lines whose chunks are our own served texts of the arm's ranked list: whole, each split in two
    halves, or merged in pairs (1+2, 3+4, ...) joined by a newline."""
    lines = {}
    for item in items:
        pieces = [texts[key] for key in arm.ranked[item.id]]
        if variant == 'halves':
            pieces = [half for piece in pieces for half in split_half(piece)]
        elif variant == 'pairs':
            pieces = ['\n'.join(pieces[i:i + 2]) for i in range(0, len(pieces), 2)]
        lines[item.id] = {'id': item.id, 'field': arm.spec.field, 'sent': getattr(item, arm.spec.field),
                          'status': 'ok', 'chunks': [{'rank': r, 'content': c} for r, c in enumerate(pieces, 1)]}
    return lines


def _differ(scored: dict, name: str, w1: str, arm: str) -> list:
    return [row['id'] for row in scored['items'] if (row['arms'][name][w1 + 'recall'], row['arms'][name][w1 + 'reached'])
            != (row['arms'][name][arm + 'recall'], row['arms'][name][arm + 'reached'])]


NEIGHBOUR_TARGETS = (1200, 2300, 4700)  # characters: shorter than, the median and the 90th percentile of the
# synthetic five-law file's chunks (README, «Time on a file of the real run's shape»)


def neighbour_runs(context: Context, target: int) -> dict:
    """The null control for the mapping rule. For each expected article of the 80 items, two chunks of about
    `target` characters: the same law's articles after it and before it, in order, the article itself left out.
    A run «maps through a single article» when one article of the run maps the expected one on its own (shared
    wording, which the arms scored through the rule also earn), and «only as a run» when none does: the credit a
    long chunk of neighbours gets for text it does not hold."""
    by_law: dict = defaultdict(list)
    for key in sorted(context.texts):
        by_law[key[0]].append(key)

    def run(keys):
        out, size = [], 0
        for key in keys:
            if size >= target:
                break
            out.append(key)
            size += len(context.texts[key]) + 1
        return out
    tested, single, only_run = 0, [], []
    for item in context.items:
        for key in sorted(item.expected):
            law = by_law[key[0]]
            at = law.index(key)
            for side, keys in (('after', run(law[at + 1:])), ('before', run(law[:at][::-1])[::-1])):
                if not keys:
                    continue
                tested += 1
                if key not in context.mapper.articles('\n'.join(context.texts[k] for k in keys)):  # in law order
                    continue
                alone = any(key in context.mapper.articles(context.texts[k]) for k in keys)
                (single if alone else only_run).append(f'{item.id} {label(key)} {side}')
    return {'target_chars': target, 'runs': tested, 'map_through_a_single_article': single,
            'map_only_as_a_run': only_run}


def self_check(context: Context, names=None, targets: tuple = NEIGHBOUR_TARGETS) -> tuple[list, list]:
    """Score each arm's own served texts as if they were W1 chunks, at that arm's budget: whole articles for every
    arm, and for A0 also each article split in two halves and articles merged in pairs. Then the neighbour-run
    control at each of `targets`: no run may map an expected article only as a run.

    Strict reading (each chunk counts only for articles of the arm's top 5): W1 must equal the arm on every item,
    so the recorded figures (A0 recall@5 0.5625) come back. This checks the budget, the order, the cut and the
    metrics. Rule reading (the rule as W1 is scored): W1 may not fall below the arm on any item; where it rises,
    a served article holds at least half of an expected article's tokens in order. With whole articles it must
    equal the arm scored through the rule. Those items are listed: the rule credits them, for W1 and for us."""
    report, failures = [], []
    held = {i.law for i in context.items}
    for arm in context.arms:
        name = arm.spec.name
        if names is not None and name not in names:
            continue
        for variant in ('whole', 'halves', 'pairs') if name == 'A0' else ('whole',):
            lines = synthetic_lines(arm, context.items, context.texts, variant)
            common = (arm.spec.field, context.items, lines, [arm], context.mapper, context.texts, context.strata, held)
            strict = score_field(*common, intervals=False, strict=True)
            rule = score_field(*common, intervals=(name == 'A0' and variant == 'whole'))
            s_all, r_all = strict['arms'][name]['scopes']['all'], rule['arms'][name]['scopes']['all']
            strict_differ = _differ(strict, name, '', 'arm_')
            below = [row['id'] for row in rule['items'] if row['arms'][name]['recall'] < row['arms'][name]['arm_recall']]
            rule_differ = _differ(rule, name, '', 'arm_rule_') if variant == 'whole' else []
            rises = [row['id'] for row in rule['items'] if row['arms'][name]['recall'] > row['arms'][name]['arm_recall']]
            line = (f'{name:6} {variant:6} strict: W1 recall {s_all["w1_recall"]:.4f}, reached {s_all["w1_reached"]}/80, '
                    f'stratum {strict["arms"][name]["scopes"]["stratum"]["w1_reached"]}/17; arm {s_all["arm_recall"]:.4f} '
                    f'(recorded {arm.spec.recorded[0]:.4f}), {s_all["arm_reached"]}/80, '
                    f'{strict["arms"][name]["scopes"]["stratum"]["arm_reached"]}/17; items that differ '
                    f'{len(strict_differ)}. Rule: W1 recall {r_all["w1_recall"]:.4f}, reached {r_all["w1_reached"]}/80; '
                    f'arm through the rule {r_all["arm_rule_recall"]:.4f}; rises on {len(rises)}'
                    + (f' ({", ".join(rises)})' if rises else ''))
            interval = rule['arms'][name]['intervals'].get('all_recall')
            if interval:
                line += f'; W1 minus arm {interval["mean"]:+.4f} [{interval["lo"]:+.4f}, {interval["hi"]:+.4f}]'
            report.append(line)
            if strict_differ or s_all['arm_recall'] != arm.spec.recorded[0] or s_all['w1_recall'] != arm.spec.recorded[0]:
                failures.append(f'{name} {variant} strict: {", ".join(strict_differ) or "recall differs from recorded"}')
            if below or rule_differ:
                failures.append(f'{name} {variant} rule: below the arm on {below}, unlike the arm through the rule '
                                f'on {rule_differ}')
    for target in targets:
        control = neighbour_runs(context, target)
        single, only_run = control['map_through_a_single_article'], control['map_only_as_a_run']
        report.append(f'neighbour runs of about {target} characters, the expected article left out: {control["runs"]} '
                      f'runs; map it through a single article {len(single)}'
                      + (f' ({", ".join(single)})' if single else '') + f'; only as a run {len(only_run)}'
                      + (f' ({", ".join(only_run)})' if only_run else ''))
        if only_run:
            failures.append(f'neighbour runs of {target} characters map {len(only_run)} articles only as a run')
    return report, failures


# Writing ---------------------------------------------------------------------------------------------------------

def _f(value) -> str:
    return '—' if value is None else f'{value:.4f}' if isinstance(value, float) else str(value)


def _interval(interval: dict | None) -> str:
    if not interval:
        return '—'
    return f'{interval["mean"]:+.4f} [{interval["lo"]:+.4f}, {interval["hi"]:+.4f}] ({interval["up"]} up, {interval["down"]} down)'


def _held(row: dict) -> str:
    return 'yes' if row['held'] else f'no ({row["lacks"]})'


def _scope_name(scope: str, own: bool) -> str:
    return SCOPE_NAMES[scope] if own else {'held': 'held', 'half_A': 'half A ∩ held', 'half_B': 'half B ∩ held'}[scope]


def reading_line(reading: dict, own: bool = True) -> str:
    how = 'through the rule' if reading['by'] == 'rule' else 'by its keys'
    return (f'{reading["field"]}, against {reading["against"]} {how}, {_scope_name(reading["scope"], own)} '
            f'({reading["items"]} items): W2 recall {_f(reading["w2_recall"])}, arm {_f(reading["arm_recall"])}; '
            f'W2 minus arm {_interval(reading["interval"])}')


_SIDES = {'above zero': 'lies above zero', 'below zero': 'lies below zero', 'includes zero': 'includes zero',
          'cannot be read': 'cannot be read (no item in the scope)'}


def decision_text(decision: dict) -> list:
    """The deciding reading, line by line, as the terminal and the report print it."""
    if not decision['deciding_cell']:
        return ['This file is not the deciding cell, so nothing in it decides: ' + '; '.join(decision['why_not']) + '.']
    d, c = decision, decision['cell']
    out = [f'Rule: {d["rule"]}',
           f'Cell: {c["engine"]}, {c["embedder"]} (revision {c["revision"]}, {c["via"]}), {c["settings"]}, '
           f'the {c["field"]} field.',
           f'Pins checked: the model revision {c["revision"][:12]}, Walid\'s indexing canvas {c["canvas_sha256"][:12]}, '
           f'T-B2\'s rows {c["against_rows_sha256"][:12]}, the split {c["split_sha256"][:12]}. The RAGFlow image '
           f'digest {c["ragflow_image_digest"]} is recorded from the run, not pinned (a known limit).',
           f'Against: {c["against"]}. Both are scored through the mapping rule, at T-B2\'s served-text budget.',
           f'Scope: the held-out half B, {d["items"]} items in split.json key order (split.json '
           f'{c["split_sha256"][:12]}).',
           f'W2 recall {_f(d["w2_recall"])}, reached {d["w2_reached"]} of {d["items"]}; T-B2 through the rule '
           f'{_f(d["arm_recall"])}, reached {d["arm_reached"]}.',
           f'W2 minus T-B2: {_interval(d["interval"])}. Paired bootstrap, {RESAMPLES:,} resamples, seed {SEED}. '
           f'The interval {_SIDES[d["side"]]}.',
           f'Verdict: {d["verdict"]}.' + (f' {d["note"][0].upper()}{d["note"][1:]}.' if d['note'] else '')]
    if d['not_ok_in_scope']:
        out.append(f'{len(d["not_ok_in_scope"])} half-B items have no ok line ({", ".join(d["not_ok_in_scope"])}); '
                   'they count as W2 misses.')
    return out


def exploratory_text(report: dict) -> list:
    out = [reading_line(r) for r in report['w2_exploratory']]
    fallback = report.get('fallback_sensitivity')
    if fallback:
        for field, row in fallback['fields'].items():
            out += [f'dense-only fallback treated as empty ({len(row["items_emptied"])} {field} items emptied): '
                    + reading_line({'field': field, **r}) for r in row['readings']]
    out.append('Other cells (Infinity on a fresh stack, the rt arm at vector weight 0.4) are scored from their own '
               'files; every reading of them is exploratory.')
    return out


def _source_lines(report: dict) -> list:
    sources, out = report.get('sources') or {}, []
    if sources:
        parts = [f'{name} `{s["path"]}` ({s["sha256"][:12]}{"" if s["durable"] else ", scratch bench"})'
                 for name, s in sources['arms'].items()]
        split, terms = sources['split'], sources['strata_terms']
        sizes = ', '.join(f'{half} {n}' for half, n in report['halves']['sizes'].items())
        parts.append(f'split `{split["path"]}` ({split["sha256"][:12]}'
                     f'{"" if split["pinned"] else ", not the pinned split"}; halves {sizes})')
        parts.append(f'strata terms `{terms["path"]}` ({terms["sha256"][:12]}'
                     f'{"" if terms.get("durable") else ", scratch bench"})')
        out.append('Sources: ' + '; '.join(parts) + '.')
    out += [f'**Warning (sources):** {warning}.' for warning in report.get('source_warnings', [])]
    return out


def _w1_head(report: dict) -> list:
    results, held = report['results'], report['laws_held']
    out = ['# W1 score', '',
           f'Results `{results["sha256"][:12]}` (handover `{results["handover_id"]}`), fields '
           f'{", ".join(results["fields"])}, {results["datasets"]} dataset(s), RAGFlow '
           f'{results["ragflow_version"] or "version not reported"}. Script as sent: {results["script_matches_ours"]}; '
           f'queries as sent: {results["queries_matches_ours"]}.',
           f'Settings sent: {", ".join(f"{k}={v}" for k, v in sorted(results["settings"].items())) or "none"}.',
           f'Eval set `{report["eval_set_sha256"][:12]}`, corpus `{report["corpus_sha256"][:12]}`.', '',
           f'**Laws his corpus holds** ({held["source"]}): {", ".join(held["laws"]) or "none"}.',
           'Evidence: his chunks, each counted for the law of the article it matches most tokens of, when that is '
           f'{INFER_MIN_TOKENS} tokens or more (inference needs {INFER_MIN_CHUNKS}): ' +
           (', '.join(f'{law} {n}' for law, n in held['evidence'].items()) or 'none') +
           f'; inferred: {", ".join(held["inferred"]) or "none"}.']
    out += [f'**Warning (laws held):** {warning}.' for warning in held['warnings']]
    lacking = report['articles_lacking']
    if lacking['given']:
        out.append(f'**Articles his copy lacks** (--articles-lacking, ‡): {", ".join(lacking["given"])}. Items whose '
                   f'expected articles are all among them, left out of the held scopes: '
                   f'{", ".join(lacking["items_left_out"]) or "none"}.')
    return out


def _tei_wait_text(patch: dict) -> str:
    return (f'`{patch["file"]}` lines {", ".join(map(str, patch["changed_lines"]))}: TEI wait {patch["wait_s"]} s, '
            f'not {W2_TEI_WAIT_SHIPPED} (image file {patch["image_sha256"]}, patched {patch["patched_sha256"]})')


def _embedder_text(m: dict) -> str:
    e = m['embedder']
    if not is_hosted(m):
        return f'{e["name"]} (revision {e["revision"]}, via {e["via"]})'
    h = m['hosted_embedder']
    return (f'{e["name"]} (hosted: {h["factory"]} instance {h["instance"]}, {h["base_url"]}, provider order '
            f'{h["provider_order"] or "none"})')


def _own_head(report: dict) -> list:
    results, held, m = report['results'], report['laws_held'], report['w2_manifest']
    hosted = is_hosted(m)
    rows = [('engine', m['engine']), ('embedder', _embedder_text(m)),
            ('RAGFlow', f'{m["ragflow_version"]}, image {m["ragflow_image_digest"]}'), ('dataset id', m['dataset_id']),
            ('language', m['language']), ('documents', m['document_count']),
            ('chunks', f'{m["chunk_count"]} (predicted {m["predicted_chunk_count"]}, all match: {m["all_match"]})'),
            ('canvas sha256', m['canvas_sha256']), ('upload manifest sha256', m['upload_manifest_sha256']),
            ('file shape', m['file_shape']), ('embedding batch size', m['embedding_batch_size']),
            ('max concurrent tasks', m['max_concurrent_tasks']),
            ('data policy', m['hosted_embedder']['data_policy']) if hosted
            else ('TEI wait patch', _tei_wait_text(m['tei_wait_patch'])),
            ('created at', m['created_at']), ('manifest', f'`{m["path"]}` ({m["sha256"][:12]})')]
    out = ['# W2 score', '',
           '**Own run (W2).** Our served articles, one generated file per law, in our own throwaway RAGFlow, queried '
           'by run_w1.py. Scored with `--own-run`: every screen of the results contract ran; the third-party gates '
           '(the quarantine copy and the person\'s screen) were skipped. The W2 manifest below ties the file to the '
           'dataset: its id, documents and chunks equal the header\'s.', '',
           *(['**Hosted run: exploratory only.** The embedder is hosted on OpenRouter (the owner\'s one hosted run, '
              'spec-rag-system.md:472); the deciding cell is the local Elasticsearch run with the built-in embedder, so '
              'nothing below decides.', ''] if hosted else []),
           '| W2 manifest | value |', '|---|---|', *(f'| {k} | {v} |' for k, v in rows), '',
           f'Results `{results["sha256"][:12]}`, arm `{results["arm"]}` ({results["arm_settings"]}), fields '
           f'{", ".join(results["fields"])}, RAGFlow {results["ragflow_version"]}. Script and queries equal to the '
           f'package: {results["script_matches_ours"]}; {results["queries_matches_ours"]}.',
           f'Settings sent: {", ".join(f"{k}={v}" for k, v in sorted(results["settings"].items())) or "none"}.',
           f'Eval set `{report["eval_set_sha256"][:12]}`, corpus `{report["corpus_sha256"][:12]}`.', '',
           f'**Laws held:** all {len(held["laws"])}, our whole corpus. Articles lacking: none. Every item is held, so '
           '«held» and «all» below are the same items.',
           'Evidence, reported only (it decides nothing here): the returned chunks, each counted for the law of the '
           f'article it matches most tokens of, when that is {INFER_MIN_TOKENS} tokens or more: '
           + (', '.join(f'{law} {n}' for law, n in held['evidence'].items()) or 'none') + '.']
    out += [f'Note (laws): {note}.' for note in held['notes']]
    out += [f'**Warning:** {warning}.' for warning in results['warnings']]
    return out


def markdown(report: dict) -> str:
    own = 'w2_manifest' in report
    out = _own_head(report) if own else _w1_head(report)
    out += ['', '**Rules.** ' + report['rules']['mapping'] + ' (‡: ' + report['rules']['mapping_owner_call'] +
            '). Budget: ' + report['rules']['budget'] +
            f'; the crossing chunk is cut at the budget («{report["rules"]["crossing_rule"]}»). '
            f'Intervals: paired bootstrap, {RESAMPLES} resamples, seed {SEED}, {report["rules"]["bootstrap"]["order"]}; '
            f'an end within {report["rules"]["bootstrap"]["zero_tolerance"]:g} of zero counts as zero. '
            + (f'The deciding rule (pre-registered): {DECIDING_RULE} An own run holds every law: no item is left out.'
               if own else 'Decision rule (c): ' + report['rules']['decision_c'] + '. Items on a law he lacks, or '
               'whose expected articles his copy lacks, are left out of the held scopes, not counted as failures.'),
            *_source_lines(report), '']
    if own:
        out += ['## Deciding reading (pre-registered: spec-rag-system.md, «Owner decision 2026-11-08»)', '',
                *(f'- {line}' for line in decision_text(report['w2_decision'])), '',
                '## Exploratory (reported, never deciding)', '',
                *(f'- {line}' for line in exploratory_text(report)), '']
    for field, scored in report['fields'].items():
        out += _field_section(field, scored, own)
    return '\n'.join(out) + '\n'


def _field_section(field: str, scored: dict, own: bool) -> list:
    who, level = ('W2', '###') if own else ('W1', '##')
    rule_c, col_c = ("W1's rule (c), read on this run (exploratory)", 'rule (c)') if own else \
        ('Decision rule (c)', 'decision (c)')
    best = scored['best_arm']
    out = [f'{level} The `{field}` field', '',
           f'Lines: {", ".join(f"{k} {v}" for k, v in sorted(scored["lines"].items()))}'
           + (f' (not ok: {", ".join(scored["not_ok"])})' if scored['not_ok'] else '') + '.',
           f'Our best arm on this field (highest recorded all-80 recall@5): **{best}**.', '',
           f'| arm | median budget (chars) | held items | {who} reached | arm reached | {who} recall | arm recall | '
           f'{who} − arm recall [95%] | stratum ∩ held | {who} / arm reached | {who} − arm recall [95%] | {col_c} |',
           '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, arm in scored['arms'].items():
        h, s = arm['scopes']['held'], arm['scopes']['stratum_held']
        out.append(f'| {"**" + name + "**" if name == best else name} | {arm["budget_chars_median"]:.0f} | '
                   f'{h["items"]} | {h["w1_reached"]} | {h["arm_reached"]} | {_f(h["w1_recall"])} | '
                   f'{_f(h["arm_recall"])} | {_interval(arm["intervals"].get("held_recall"))} | {s["items"]} | '
                   f'{s["w1_reached"]} / {s["arm_reached"]} | {_interval(arm["intervals"].get("stratum_held_recall"))}'
                   f' | {arm["decision_c"]["reading"]} |')
    reading = scored['arms'][best]['decision_c']
    out += ['', f'**{rule_c}, `{field}` field, against {best}: {who} {reading["reading"]}**'
            + (f' ({", ".join(reading["basis"])}).' if reading['basis'] else '.'),
            f'Against {best} scored through the same rule (its served text mapped as {who}\'s chunks are): {who} '
            f'{reading["reading_through_rule"]}'
            + (f' ({", ".join(reading["basis_through_rule"])}).' if reading['basis_through_rule'] else '.')
            + (' **The two readings differ: report both to the owner.**'
               if reading['beats'] != reading['beats_through_rule'] else ''), '',
            'Like with like: each arm scored through the same rule (held items):', '',
            f'| arm | {who} recall | arm recall through the rule | {who} − arm [95%] | stratum ∩ held: {who} − arm [95%] | '
            f'{col_c} |', '|---|---|---|---|---|---|']
    for name, arm in scored['arms'].items():
        h = arm['scopes']['held']
        out.append(f'| {name} | {_f(h["w1_recall"])} | {_f(h["arm_rule_recall"])} | '
                   f'{_interval(arm["intervals"].get("held_recall_vs_rule"))} | '
                   f'{_interval(arm["intervals"].get("stratum_held_recall_vs_rule"))} | '
                   f'{arm["decision_c"]["reading_through_rule"]} |')
    if not own:  # in an own run every item is held: all 80 and the stratum are the held scopes above
        out += ['',
                'All 80 and the whole stratum, with items on laws he lacks counted as misses (reported, not decisive):',
                '', '| arm | all 80: W1 / arm recall | W1 − arm [95%] | stratum (17): W1 / arm reached | '
                'W1 − arm reached [95%] | lacking-law items: W1 reached |', '|---|---|---|---|---|---|']
        for name, arm in scored['arms'].items():
            a, s, lack = arm['scopes']['all'], arm['scopes']['stratum'], arm['scopes']['lacking']
            out.append(f'| {name} | {_f(a["w1_recall"])} / {_f(a["arm_recall"])} | '
                       f'{_interval(arm["intervals"].get("all_recall"))} | {s["w1_reached"]} / {s["arm_reached"]} | '
                       f'{_interval(arm["intervals"].get("stratum_reached"))} | {lack["w1_reached"]} of {lack["items"]} |')
    if all('half_B' in arm['scopes'] for arm in scored['arms'].values()):
        out += ['', ('Halves (split.json; T-B2 was tuned on half A, so half B is held out). The deciding reading is '
                     'T-B2 on half B through the rule, above; these are reported:') if own else
                ('Halves (split.json; T-B2 was tuned on half A), the held items of each half (reported, not '
                 'decisive):'), '',
                f'| arm | scope | items | {who} reached | arm reached (rule) | {who} recall | arm recall (rule) | '
                f'{who} − arm, rule [95%] | arm recall (keys) | {who} − arm, keys [95%] |',
                '|---|---|---|---|---|---|---|---|---|---|']
        for name, arm in scored['arms'].items():
            for scope in ('half_A', 'half_B', 'held'):
                c = arm['scopes'][scope]
                out.append(f'| {name} | {_scope_name(scope, own)} | {c["items"]} | {c["w1_reached"]} | '
                           f'{c["arm_rule_reached"]} | {_f(c["w1_recall"])} | {_f(c["arm_rule_recall"])} | '
                           f'{_interval(arm["intervals"].get(f"{scope}_recall_vs_rule"))} | {_f(c["arm_recall"])} | '
                           f'{_interval(arm["intervals"].get(f"{scope}_recall"))} |')
    out += ['', f'The crossing chunk, three ways (held items: {who} recall; reached):', '',
            '| arm | cut at the budget | counted whole | left out |', '|---|---|---|---|']
    for name, arm in scored['arms'].items():
        h = arm['scopes']['held']
        out.append(f'| {name} | {_f(h["w1_recall"])}; {h["w1_reached"]} | {_f(h["w1_recall_include"])}; '
                   f'{h["w1_reached_include"]} | {_f(h["w1_recall_exclude"])}; {h["w1_reached_exclude"]} |')
    names = list(scored['arms'])
    rows = {row['id']: row for row in scored['items']}
    named = [item_id for item_id in (*NEVER_REACHED, TRACKED) if item_id in rows]
    out += ['', f'The six never-reached under-half items and {TRACKED} ({who} reached at each arm\'s budget / the arm):',
            '', '| item | held | ' + ' | '.join(names) + ' |', '|---|---|' + '---|' * len(names)]
    for item_id in named:
        row = rows[item_id]
        out.append(f'| {item_id} | {_held(row)} | ' + ' | '.join(
            f'{int(row["arms"][n]["reached"])} / {int(row["arms"][n]["arm_reached"])}' for n in names) + ' |')
    law_rows = scored['arms'][best]['per_law']
    out += ['', f'Per law, against {best} (reached; recall):', '',
            f'| law | items | held | {who} | arm |', '|---|---|---|---|---|']
    for law, row in law_rows.items():
        out.append(f'| {law} | {row["items"]} | {"yes" if row["held"] else "no"} | {row["w1_reached"]}; '
                   f'{_f(row["w1_recall"])} | {row["arm_reached"]}; {_f(row["arm_recall"])} |')
    halves = all('half' in row for row in scored['items'])
    out += ['', f'Items, against {best} (first chunk rank that maps each expected article; — when none does):', '',
            '| item | stratum |' + (' half |' if halves else '') + ' held | status | budget | chunks counted | '
            f'expected article: rank | {who} recall | arm recall |',
            '|---|---|' + ('---|' if halves else '') + '---|---|---|---|---|---|---|']
    for row in scored['items']:
        cell = row['arms'][best]
        ranks = ', '.join(f'{k} {"—" if r is None else r}' for k, r in cell['expected_first_rank'].items())
        out.append(f'| {row["id"]} | {row["stratum"]} |' + (f' {row["half"]} |' if halves else '') +
                   f' {_held(row)} | {row["status"]} | {cell["budget_chars"]} | {cell["chunks_counted"]} | {ranks} | '
                   f'{_f(cell["recall"])} | {_f(cell["arm_recall"])} |')
    out.append('')
    return out


def write_outputs(report: dict, out_dir: Path, stem: str = 'w1-score') -> list:
    out_dir = Path(out_dir)
    if not out_dir.parent.is_dir():
        raise Refused(f'the parent of {out_dir} does not exist')
    targets = [out_dir / f'{stem}.json', out_dir / f'{stem}.md']
    existing = [p.name for p in targets if p.exists()]
    if existing:
        raise Refused(f'{", ".join(existing)} already in {out_dir}; choose a new --out-dir')
    out_dir.mkdir(exist_ok=True)
    targets[0].write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    targets[1].write_text(markdown(report), encoding='utf-8', newline='\n')
    return targets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--results', type=Path, help='the quarantined w1-results.jsonl, or with --own-run our own '
                      'w2-results-<arm>.jsonl')
    mode.add_argument('--self-check', action='store_true', help="score the arms' own lists as W1 chunks")
    parser.add_argument('--out-dir', type=Path, help='where w1-score.json and w1-score.md (own run: w2-score.*) '
                        'are written')
    parser.add_argument('--laws-held', help='comma-separated law slugs his corpus holds (default: inferred)')
    parser.add_argument('--allow-unevidenced-laws', action='store_true',
                        help='keep a --laws-held law that none of his chunks comes from (refused otherwise)')
    parser.add_argument('--articles-lacking', help='comma-separated articles his copy lacks, law:number '
                        '(for example civil-code:107); an item whose expected articles are all listed is not decisive')
    parser.add_argument('--own-run', action='store_true',
                        help=f'the results are our own W2 run, under {OWN_ROOT}/<engine>/ (needs --manifest)')
    parser.add_argument('--manifest', type=Path, help=f'with --own-run: the {W2_MANIFEST} beside the results')
    parser.add_argument('--w2-decide', action='store_true',
                        help='with --own-run: print the pre-registered W2 reading (refused unless the file is the '
                             'deciding cell)')
    parser.add_argument('--fallback', type=Path, help='with --own-run: the w2-fallback-<arm>.json beside the results, '
                        'for the dense-only fallback sensitivity reading (exploratory)')
    parser.add_argument('--split', type=Path, help=f'split.json (default {SPLIT}, else the bench copy, with a warning)')
    parser.add_argument('--package', type=Path, default=DEFAULT_PACKAGE,
                        help=f'with --own-run: the package whose run_w1.py and w1-queries.jsonl the header hashes '
                             f'must equal (default {DEFAULT_PACKAGE})')
    parser.add_argument('--bench', type=Path, default=BENCH, help=f'the bench folder (default {BENCH})')
    parser.add_argument('--baseline', type=Path, default=BASELINE, help=f'eval-final.json (default {BASELINE})')
    return parser


def _check_options(args) -> None:
    """Options that belong to one kind of run only."""
    if args.own_run:
        if not args.manifest:
            raise Refused(f'--own-run needs --manifest (the {W2_MANIFEST} beside the results)')
        given = [name for name, value in (('--laws-held', args.laws_held), ('--articles-lacking', args.articles_lacking),
                                          ('--allow-unevidenced-laws', args.allow_unevidenced_laws)) if value]
        if given:
            raise Refused(f'{", ".join(given)}: an own run holds our whole corpus (all {W2_DOCUMENTS} laws, no article '
                          'lacking); these options describe Walid\'s corpus')
        if args.self_check:
            raise Refused('--own-run needs --results, not --self-check')
    else:
        given = [name for name, value in (('--manifest', args.manifest), ('--w2-decide', args.w2_decide),
                                          ('--fallback', args.fallback)) if value]
        if given:
            raise Refused(f'{", ".join(given)}: only with --own-run')


def _print_own(report: dict, decide: bool) -> None:
    m, held = report['w2_manifest'], report['laws_held']
    how = (f'hosted: {m["hosted_embedder"]["factory"]} instance {m["hosted_embedder"]["instance"]}' if is_hosted(m)
           else f'revision {m["embedder"]["revision"]}')
    print(f'{OWN_LABEL}: {m["engine"]}, {m["embedder"]["name"]} ({how}), arm '
          f'{report["results"]["arm"]}, dataset {m["dataset_id"]}, {m["document_count"]} documents, '
          f'{m["chunk_count"]} chunks (predicted {m["predicted_chunk_count"]}, all match)')
    print(f'laws held: all {len(held["laws"])} (our whole corpus); articles lacking: none')
    for note in held['notes']:
        print(f'note: laws: {note}')
    for warning in report['results']['warnings']:
        print(f'warning: {warning}')
    decision = report['w2_decision']
    if decide:
        print('Deciding reading (pre-registered: spec-rag-system.md, «Owner decision 2026-11-08»):')
        for line in decision_text(decision):
            print(f'  {line}')
    elif decision['deciding_cell']:
        print('this file is the deciding cell: pass --w2-decide to print its pre-registered reading (also in the report)')
    else:
        print('not the deciding cell: ' + '; '.join(decision['why_not']))
    print('Exploratory (reported, never deciding):')
    for line in exploratory_text(report):
        print(f'  {line}')


def main(argv: list | None = None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    args = _parser().parse_args(argv)
    own = fallback = None
    try:
        _check_options(args)
        split_path, _ = resolve_split(args.split, args.bench)
        if args.results:
            if not args.out_dir:
                raise Refused('--out-dir is required with --results')
            if args.own_run:
                own, results = open_own_run(args.results, args.manifest, args.package, OWN_ROOT,
                                            hosted_root=HOSTED_ROOT)
                if args.w2_decide:  # every fact read here without loading the library
                    gaps = deciding_gaps(own, results.header, sha256_file(split_path),
                                         t_b2_source(args.bench, args.baseline))
                    if gaps:
                        raise Refused('--w2-decide reads only the pre-registered deciding cell, and this file is not '
                                      'it: ' + '; '.join(gaps) + '. Score it without --w2-decide: every reading of it '
                                      'is exploratory')
                if args.fallback:
                    fallback = load_fallback(args.fallback, own, results)
            else:
                opened = open_results(args.results)  # before anything else reads the file
        context = load_context(args.bench, args.baseline, split=args.split)
    except Refused as error:
        print(f'refused: {error}', file=sys.stderr)
        return 2
    print(f'eval set {context.set_sha256[:12]}, corpus {context.corpus_sha256[:12]}, {len(context.texts)} articles; '
          f'strata {dict(Counter(s["stratum"] for s in context.strata.values()))}; '
          f'halves {dict(sorted(Counter(context.halves.values()).items()))}')
    for arm in context.arms:
        print(f'arm {arm.spec.name:7} {arm.spec.field:8} recall@5 {arm.recomputed["recall@5"]:.4f} '
              f'hit@5 {arm.recomputed["hit@5"]:.4f} mrr {arm.recomputed["mrr"]:.4f} (as recorded) '
              f'from {arm.source_path}')
    for warning in context.warnings:
        print(f'warning: sources: {warning}')
    if args.self_check:
        lines, failures = self_check(context)
        print('\n'.join(lines))
        for failure in failures:
            print(f'FAILED {failure}')
        print('self-check passed' if not failures else 'self-check FAILED')
        return 1 if failures else 0
    try:
        if own is not None:
            report = score_own_run(own, results, context, fallback)
            written = write_outputs(report, args.out_dir, 'w2-score')
        else:
            laws = [law.strip() for law in args.laws_held.split(',') if law.strip()] if args.laws_held else None
            lacking = articles_lacking(args.articles_lacking, context.texts)
            report = score_results(*opened, laws, context, lacking, args.allow_unevidenced_laws)
            written = write_outputs(report, args.out_dir)
    except Refused as error:
        print(f'refused: {error}', file=sys.stderr)
        return 2
    if own is not None:
        _print_own(report, args.w2_decide)
    else:
        for warning in report['laws_held']['warnings']:
            print(f'warning: laws held: {warning}')
        for field, scored in report['fields'].items():
            best = scored['arms'][scored['best_arm']]
            print(f'{field}: against {scored["best_arm"]}, W1 {best["decision_c"]["reading"]}')
    print('wrote ' + ', '.join(str(path) for path in written))
    return 0


if __name__ == '__main__':
    sys.exit(main())
