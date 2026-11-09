"""score_w1.py: the mapping rule, the candidate restriction, the budget, the scopes, the bootstrap, the self-check.

Most tests use small invented Arabic fixtures. The tests marked «real data» load our library and the recorded
arms; they need p3-evidence/eval-final.json, the split, and every arm's and the strata's source (the durable
p3-evidence copies, else the bench folder .hq/scratch/rag-bench)."""

import contextlib
import dataclasses
import functools
import hashlib
import io
import json
import random
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import intake_w1
import run_w1
import score_w1 as s
from intake_w1 import Refused
from tests.test_intake_w1 import chunk, header, line, make_results

LEASE = ('lease-law', 1, '')
SALE = ('sale-law', 2, '')
CONTRACT = ('civil', 3, '')
REPEALED = ('civil', 4, '')
EMPTY = ('civil', 5, '')
TEXTS = {
    LEASE: 'يلتزم المؤجر بتسليم العين المؤجرة للمستأجر',  # 6 tokens: half is 3
    SALE: 'يحق للمشتري فسخ العقد خلال مدة الخيار',  # 7 tokens: half is 4
    CONTRACT: 'ينعقد العقد بمجرد ارتباط الإيجاب بالقبول',  # 6 tokens
    REPEALED: 'ملغاة',  # 1 token
    EMPTY: '—',  # no token
}
MAPPER = s.Mapper(TEXTS)
REAL_DATA = s.BASELINE.is_file() and s.SPLIT.is_file() and not s.missing_sources()


def maps(text: str) -> tuple:
    return MAPPER.articles(text)


def dp_lcs(a, b) -> int:
    """The textbook dynamic programme, as the oracle for the bit-parallel one."""
    row = [0] * (len(b) + 1)
    for x in a:
        previous = 0
        for j, y in enumerate(b, 1):
            previous, row[j] = row[j], previous + 1 if x == y else max(row[j], row[j - 1])
    return row[-1]


def full_scan(sequences: dict, chunk: list) -> tuple:
    """Every article the rule maps, by testing every article on every stretch: no index, no bound, no skipped
    stretch. lcs_length is checked against dp_lcs. A stretch can hold no more than the whole chunk, so an article
    the whole chunk does not map is not tested stretch by stretch."""
    found = []
    for key, seq in sequences.items():
        n = len(seq)
        if not n:
            continue
        masks, width = s.masks_of(seq), s.window(n)
        if s.lcs_length(masks, n, chunk) < s.need(n):
            continue
        stretches = [chunk] if len(chunk) <= width else [chunk[i:i + width] for i in range(len(chunk) - width + 1)]
        if any(s.lcs_length(masks, n, stretch) >= s.need(n) for stretch in stretches):
            found.append(key)
    return tuple(sorted(found))


@functools.lru_cache(maxsize=1)
def real_context():
    return s.load_context()


class FixtureTests(unittest.TestCase):
    def test_the_fixture_has_the_token_counts_the_tests_rely_on(self):
        self.assertEqual([6, 7, 6, 1, 0], [len(s.tokens(TEXTS[k])) for k in (LEASE, SALE, CONTRACT, REPEALED, EMPTY)])


class LcsTests(unittest.TestCase):
    def test_bit_parallel_lcs_equals_the_dynamic_programme(self):
        rng = random.Random(7)
        for _ in range(400):
            a = [rng.choice('abcde') for _ in range(rng.randint(1, 30))]
            b = [rng.choice('abcdef') for _ in range(rng.randint(0, 40))]

            got = s.lcs_length(s.masks_of(a), len(a), b)

            self.assertEqual(dp_lcs(a, b), got, (a, b))

    def test_the_stretch_lcs_equals_the_dynamic_programme_on_every_stretch(self):
        # The skipped stretches and the sliding bound may only skip stretches that cannot hold more.
        rng = random.Random(13)
        for _ in range(600):
            a = [rng.choice('abcde') for _ in range(rng.randint(1, 20))]
            b = [rng.choice('abcdef') for _ in range(rng.randint(0, 60))]
            width = rng.randint(1, 2 * len(a))
            enough = rng.randint(1, len(a))
            brute = dp_lcs(a, b) if len(b) <= width else max(dp_lcs(a, b[i:i + width])
                                                               for i in range(len(b) - width + 1))

            best = s.window_lcs(s.masks_of(a), Counter(a), len(a), b, width)
            reaches = s.window_lcs(s.masks_of(a), Counter(a), len(a), b, width, enough) >= enough

            self.assertEqual((brute, brute >= enough), (best, reaches), (a, b, width, enough))


class MappingRuleTests(unittest.TestCase):
    def test_exactly_half_of_the_tokens_in_order_maps(self):
        self.assertIn(LEASE, maps('نص يلتزم فيه بتسليم كامل العين'))  # يلتزم، تسليم، عين: 3 of 6

    def test_just_under_half_does_not_map(self):
        self.assertNotIn(LEASE, maps('نص يلتزم فيه كامل العين'))  # 2 of 6

    def test_an_odd_count_needs_the_larger_half(self):
        self.assertNotIn(SALE, maps('يحق فسخ العقد'))  # 3 of 7
        self.assertIn(SALE, maps('يحق فسخ العقد مدة'))  # 4 of 7

    def test_every_token_out_of_order_does_not_map(self):
        reversed_lease = ' '.join(reversed(TEXTS[LEASE].split()))  # all 6 tokens, longest run in order is 1

        self.assertNotIn(LEASE, maps(reversed_lease))

    def test_one_chunk_can_retrieve_two_articles(self):
        self.assertEqual((CONTRACT, LEASE), maps(TEXTS[LEASE] + ' ' + TEXTS[CONTRACT]))

    def test_an_article_split_across_two_chunks_counts_for_each_half_that_holds_half_its_tokens(self):
        # The rule tests each chunk on its own. Split 3 + 3, both halves map; split 4 + 3, only the first does.
        self.assertIn(LEASE, maps('يلتزم المؤجر بتسليم'))
        self.assertIn(LEASE, maps('العين المؤجرة للمستأجر'))
        self.assertIn(SALE, maps('يحق للمشتري فسخ العقد'))
        self.assertNotIn(SALE, maps('خلال مدة الخيار'))

    def test_an_article_split_in_three_is_retrieved_by_no_chunk(self):
        # The whole text is served, yet no single chunk holds half of it: the rule then says «not retrieved».
        pieces = ['يلتزم المؤجر', 'بتسليم العين', 'المؤجرة للمستأجر']

        self.assertEqual([], [p for p in pieces if LEASE in maps(p)])

    def test_tokens_are_normalised_before_matching(self):
        # diacritics dropped, hamza folded (المؤجر = الموجر), the article and one clitic stripped (normalize.stem)
        self.assertIn(LEASE, maps('يَلتزمُ الموجر بتسليمِ'))

    def test_the_matched_half_must_lie_within_a_stretch_as_long_as_the_article(self):
        # LEASE has 6 tokens: 3 of them in order within 6 consecutive chunk tokens map, within 7 they do not.
        self.assertIn(LEASE, maps('يلتزم نص بتسليم نص نص المؤجرة'))
        self.assertNotIn(LEASE, maps('يلتزم نص بتسليم نص نص نص المؤجرة'))

    def test_tokens_scattered_through_a_long_chunk_do_not_map(self):
        # The whole chunk holds 3 of LEASE's 6 tokens in order, as a run of neighbouring articles can.
        noise = ' نص' * 5

        self.assertNotIn(LEASE, maps('يلتزم' + noise + ' بتسليم' + noise + ' المؤجرة' + noise))

    def test_half_an_article_inside_a_long_chunk_maps(self):
        noise = ' نص' * 20

        self.assertIn(LEASE, maps(noise + ' يلتزم المؤجر بتسليم' + noise))

    def test_a_one_token_article_maps_on_its_word_and_an_empty_article_never_maps(self):
        self.assertIn(REPEALED, maps('هذه المادة ملغاة'))
        self.assertNotIn(EMPTY, maps('— هذه المادة ملغاة —'))
        self.assertEqual((), maps(''))


class CandidateRestrictionTests(unittest.TestCase):
    """The pigeonhole index may only skip articles the rule could never map."""

    WORDS = [a + b + c for a in 'سمعرد' for b in 'جحخصط' for c in 'قنهتث']  # letters no clitic rule strips

    def test_the_index_maps_exactly_what_a_full_scan_maps_on_a_random_corpus(self):
        rng = random.Random(11)
        weights = [1 / (rank + 1) for rank in range(len(self.WORDS))]  # a few common words, many rare ones
        texts = {('law', number, ''): ' '.join(rng.choices(self.WORDS, weights, k=rng.randint(1, 40)))
                 for number in range(400)}
        mapper = s.Mapper(texts)
        sequences = {key: s.tokens(text) for key, text in texts.items()}
        checked = mapped = 0
        for _ in range(300):
            source = sequences[rng.choice(list(texts))]
            kept = [w for w in source if rng.random() < rng.choice((0.3, 0.6, 0.9))]
            noise = rng.choices(self.WORDS, weights, k=rng.randint(0, 60))
            chunk_words = kept + noise if rng.random() < 0.5 else noise[:10] + kept + noise[10:]
            chunk_text = ' '.join(chunk_words)

            full = full_scan(sequences, chunk_words)

            self.assertEqual(full, mapper.articles(chunk_text))
            checked += 1
            mapped += len(full)
        self.assertGreater(mapped, checked)  # the corpus is not trivial: chunks do map articles

    @unittest.skipUnless(REAL_DATA, 'real data: eval-final.json, the split or a source is missing')
    def test_the_index_maps_exactly_what_a_full_scan_maps_on_our_library(self):
        context = real_context()
        keys = sorted(context.texts)
        rng = random.Random(5)
        chunks = []
        for _ in range(6):
            a, b = rng.sample(keys, 2)
            text_a, text_b = context.texts[a], context.texts[b]
            chunks.append(text_a[len(text_a) // 3:] + ' ' + text_b[: len(text_b) // 2])
        chunks += [context.texts[('civil-code', 107, '')], context.texts[('evidence', 2, '')]]
        for chunk_text in chunks:
            full = full_scan(context.mapper.tokens, s.tokens(chunk_text))

            self.assertEqual(full, context.mapper.articles(chunk_text))


class BudgetTests(unittest.TestCase):
    CHUNKS = ['كلمة ' * 20, 'جملة ' * 20, 'فقرة ' * 20]  # 100 characters each

    def test_the_budget_is_the_text_of_the_arms_top_five(self):
        ranked = (LEASE, SALE, CONTRACT, REPEALED, EMPTY, LEASE, SALE)

        self.assertEqual(sum(len(TEXTS[k]) for k in ranked[:5]), s.served_chars(ranked, TEXTS))

    def test_the_crossing_chunk_is_cut_counted_whole_or_left_out(self):
        cut = s.counted(self.CHUNKS, 250, 'truncate')
        self.assertEqual(self.CHUNKS[:2], cut[:2])
        self.assertEqual('فقرة ' * 9 + 'فقرة', cut[2])  # cut back to the last whole word within 50 characters
        self.assertEqual(self.CHUNKS, s.counted(self.CHUNKS, 250, 'include'))
        self.assertEqual(self.CHUNKS[:2], s.counted(self.CHUNKS, 250, 'exclude'))

    def test_a_chunk_that_starts_at_the_budget_never_counts(self):
        for rule in s.RULES:
            self.assertEqual(self.CHUNKS[:2], s.counted(self.CHUNKS, 200, rule))
            self.assertEqual([], s.counted(self.CHUNKS, 0, rule))

    def test_a_space_exactly_at_the_budget_keeps_the_word_before_it(self):
        self.assertEqual('كلمة', s.cut('كلمة أخرى', 4))

    def test_a_cut_inside_the_first_word_leaves_nothing(self):
        self.assertEqual('', s.cut('كلمةطويلةجدا وكلمة', 5))

    def test_the_cut_can_drop_an_article_below_half(self):
        filler = 'نص ' * 30
        text = filler + TEXTS[LEASE]
        budget = len(filler + 'يلتزم المؤجر ')  # the cut keeps only 2 of the 6 tokens

        truncated = s.score_chunks(MAPPER, [text], budget, 'truncate', frozenset({LEASE}))
        whole = s.score_chunks(MAPPER, [text], budget, 'include', frozenset({LEASE}))

        self.assertEqual((0.0, 1.0), (truncated['reached'], whole['reached']))
        self.assertEqual(1, truncated['cut_rank'])

    def test_a_cut_piece_maps_what_a_full_scan_of_it_maps(self):
        whole = TEXTS[SALE] + ' ' + TEXTS[LEASE] + ' ' + TEXTS[CONTRACT] + ' ملغاة'
        fresh = s.Mapper(TEXTS)
        for left in range(0, len(whole) + 1, 3):
            piece = s.cut(whole, left)

            self.assertEqual(fresh.articles(piece), MAPPER.articles(piece, MAPPER.articles(whole)), left)

    def test_mapped_articles_take_the_rank_of_the_first_chunk_that_maps_them(self):
        result = s.score_chunks(MAPPER, ['نص', TEXTS[LEASE], TEXTS[LEASE] + ' ' + TEXTS[SALE]], 10_000, 'truncate',
                                frozenset({LEASE, SALE}))

        self.assertEqual({'lease-law:1': 2, 'sale-law:2': 3}, result['expected_first_rank'])
        self.assertEqual(1.0, result['recall'])


def arm(name: str, field: str, ranked: dict) -> s.Arm:
    return s.Arm(s.ArmSpec(name, field, name, 'baseline', None, (0.0, 0.0, 0.0)), ranked, {}, '')


class ScopeTests(unittest.TestCase):
    ITEMS = [s.Item('lease-law-01', 'ايجار', 'ايجار؟', frozenset({LEASE}), 'lease-law'),
             s.Item('sale-law-01', 'فسخ', 'فسخ؟', frozenset({SALE}), 'sale-law'),
             s.Item('civil-01', 'عقد', 'عقد؟', frozenset({CONTRACT}), 'civil')]
    STRATA = {'lease-law-01': {'stratum': 'under'}, 'sale-law-01': {'stratum': 'half'}, 'civil-01': {'stratum': 'all'}}
    ARM = arm('X', 'query', {'lease-law-01': (LEASE,), 'sale-law-01': (CONTRACT,), 'civil-01': (CONTRACT,)})
    LINES = {'lease-law-01': {'status': 'ok', 'chunks': [{'content': TEXTS[LEASE]}]},
             'sale-law-01': {'status': 'ok', 'chunks': [{'content': TEXTS[SALE]}]},
             'civil-01': {'status': 'error', 'chunks': []}}

    def score(self, held):
        return s.score_field('query', self.ITEMS, self.LINES, [self.ARM], MAPPER, TEXTS, self.STRATA, held)

    def test_items_on_a_law_he_lacks_are_left_out_of_the_held_scopes(self):
        scopes = self.score({'lease-law', 'sale-law'})['arms']['X']['scopes']

        self.assertEqual((2, 2, 1), (scopes['held']['items'], scopes['held']['w1_reached'], scopes['held']['arm_reached']))
        self.assertEqual((1, 0), (scopes['lacking']['items'], scopes['lacking']['w1_reached']))
        self.assertEqual(1, scopes['stratum_held']['items'])
        self.assertEqual((3, 2, 2), (scopes['all']['items'], scopes['all']['w1_reached'], scopes['all']['arm_reached']))

    def test_a_missing_or_failed_line_counts_as_a_miss_and_is_listed(self):
        scored = self.score({'lease-law', 'sale-law', 'civil'})

        self.assertEqual(['civil-01'], scored['not_ok'])
        self.assertEqual({'ok': 2, 'error': 1}, scored['lines'])

    def test_no_held_item_gives_no_reading(self):
        decision = self.score(set())['arms']['X']['decision_c']

        self.assertEqual('cannot be read: no item is on a law his corpus holds', decision['reading'])
        self.assertFalse(decision['beats'])

    def test_the_arm_is_also_scored_through_the_rule(self):
        cells = {row['id']: row['arms']['X'] for row in self.score({'civil'})['items']}

        self.assertEqual((1.0, 1.0), (cells['lease-law-01']['arm_recall'], cells['lease-law-01']['arm_rule_recall']))
        self.assertEqual((0.0, 0.0), (cells['sale-law-01']['arm_recall'], cells['sale-law-01']['arm_rule_recall']))

    def test_an_under_half_item_on_a_law_he_lacks_is_left_out_of_stratum_held(self):
        scopes = self.score({'sale-law', 'civil'})['arms']['X']['scopes']

        self.assertEqual((1, 0), (scopes['stratum']['items'], scopes['stratum_held']['items']))

    def test_an_item_whose_expected_articles_his_copy_lacks_is_left_out_of_the_held_scopes(self):
        scored = s.score_field('query', self.ITEMS, self.LINES, [self.ARM], MAPPER, TEXTS, self.STRATA,
                               {'lease-law', 'sale-law'}, lacking_articles=frozenset({LEASE}))
        scopes = scored['arms']['X']['scopes']
        rows = {row['id']: row for row in scored['items']}

        self.assertEqual((1, 0, 2), (scopes['held']['items'], scopes['stratum_held']['items'], scopes['lacking']['items']))
        self.assertEqual(('articles', 'law'), (rows['lease-law-01']['lacks'], rows['civil-01']['lacks']))

    def test_an_item_with_only_some_expected_articles_lacking_stays_held(self):
        item = s.Item('lease-law-02', 'ايجار وفسخ', 'ايجار وفسخ؟', frozenset({LEASE, SALE}), 'lease-law')

        self.assertIsNone(s.lacks(item, {'lease-law'}, frozenset({LEASE})))
        self.assertEqual('articles', s.lacks(item, {'lease-law'}, frozenset({LEASE, SALE})))


class ArticlesLackingTests(unittest.TestCase):
    def test_labels_are_read_as_articles_of_our_library(self):
        self.assertEqual(frozenset({LEASE, SALE}), s.articles_lacking('lease-law:1, sale-law:2', TEXTS))
        self.assertEqual(frozenset(), s.articles_lacking(None, TEXTS))

    def test_an_article_our_library_does_not_have_is_refused(self):
        for text in ('lease-law:99', 'lease-law', 'nowhere:1'):
            with self.assertRaisesRegex(Refused, 'not an article of our library'):
                s.articles_lacking(text, TEXTS)


ECHO = ('echo-law', 9, '')
DECISION_TEXTS = {**TEXTS, ECHO: 'يلتزم المؤجر بتسليم'}  # LEASE's first 3 of 6 tokens: it maps LEASE
DECISION_MAPPER = s.Mapper(DECISION_TEXTS)


class DecisionTests(unittest.TestCase):
    """Decision rule (c): the sign of W1 minus the arm, the side of zero, the decisive scopes, the reading."""
    ITEMS = ScopeTests.ITEMS
    STRATA = {'lease-law-01': {'stratum': 'half'}, 'sale-law-01': {'stratum': 'half'}, 'civil-01': {'stratum': 'under'}}

    def decide(self, ranked: dict, chunks: dict, held: set) -> dict:
        lines = {item_id: {'status': 'ok', 'chunks': [{'content': text} for text in texts]}
                 for item_id, texts in chunks.items()}
        return s.score_field('query', self.ITEMS, lines, [arm('X', 'query', ranked)], DECISION_MAPPER,
                             DECISION_TEXTS, self.STRATA, held)['arms']['X']

    def test_w1_beats_when_its_held_interval_lies_above_zero(self):
        # held items: W1 maps both, the arm neither; the item on the law he lacks would pull the all-80 reading down
        result = self.decide({'lease-law-01': (CONTRACT,), 'sale-law-01': (CONTRACT,), 'civil-01': (CONTRACT,)},
                             {'lease-law-01': [TEXTS[LEASE]], 'sale-law-01': [TEXTS[SALE]], 'civil-01': ['نص']},
                             {'lease-law', 'sale-law'})

        decision = result['decision_c']

        self.assertEqual((True, ['held_recall'], 'beats with an interval excluding zero'),
                         (decision['beats'], decision['basis'], decision['reading']))

    def test_w1_does_not_beat_when_the_arm_does_better(self):
        result = self.decide({'lease-law-01': (LEASE,), 'sale-law-01': (SALE,), 'civil-01': (CONTRACT,)},
                             {'lease-law-01': ['نص'], 'sale-law-01': ['نص'], 'civil-01': ['نص']},
                             {'lease-law', 'sale-law'})

        decision = result['decision_c']

        self.assertEqual((False, [], 'does not beat: no decisive interval excludes zero'),
                         (decision['beats'], decision['basis'], decision['reading']))
        self.assertTrue(result['intervals']['held_recall']['excludes_zero_below'])

    def test_the_through_rule_reading_credits_the_arm_for_served_text_that_holds_an_expected_article(self):
        # The arm serves ECHO, not LEASE: by keys it misses LEASE; through the rule its text maps LEASE, as W1's does.
        result = self.decide({'lease-law-01': (ECHO,), 'sale-law-01': (SALE,), 'civil-01': (CONTRACT,)},
                             {'lease-law-01': [DECISION_TEXTS[ECHO]], 'sale-law-01': [], 'civil-01': []},
                             {'lease-law'})
        cell = result['scopes']['held']
        decision = result['decision_c']

        self.assertEqual((1.0, 0.0, 1.0), (cell['w1_recall'], cell['arm_recall'], cell['arm_rule_recall']))
        self.assertEqual((True, False), (decision['beats'], decision['beats_through_rule']))


class LawsHeldTests(unittest.TestCase):
    LAWS = {('kept', n, ''): f'يلتزم الطرف رقم {n} بأداء الثمن كاملا في الموعد المتفق عليه' for n in range(1, 4)}
    # «echo» shares wording: each of its articles is held, in order, inside a «kept» article.
    LAWS.update({('echo', n, ''): f'يلتزم الطرف رقم {n} بأداء الثمن كاملا في الموعد' for n in range(1, 4)})
    LAWS.update({('other', n, ''): f'تختص المحكمة رقم {n} بالنظر في الدعوى المرفوعة أمامها وفق القانون'
                 for n in range(1, 3)})
    LAWS[('tiny', 1, '')] = 'ملغاة'

    def test_each_chunk_counts_only_for_the_law_of_its_best_source(self):
        mapper = s.Mapper(self.LAWS)
        chunks = [self.LAWS[('kept', n, '')] + ' ملغاة' for n in range(1, 4)] + \
                 [self.LAWS[('other', n, '')] for n in range(1, 3)] + \
                 ['هذه المادة ملغاة'] * 3  # best source «tiny», one token matched: not evidence
        self.assertTrue(all(('echo', n, '') in mapper.articles(chunks[n - 1]) for n in range(1, 4)))

        held = s.laws_held(None, mapper, [{'chunks': [{'content': c} for c in chunks]}], set())

        self.assertEqual(['kept'], held['laws'])  # «echo» is mapped by 3 chunks but is never their best source
        self.assertEqual('inferred', held['source'])
        self.assertEqual({'kept': 3, 'other': 2}, held['evidence'])

    def test_the_best_source_is_the_article_the_chunk_holds_most_of_within_one_stretch(self):
        # Over the whole chunk the scattered article matches 12 tokens and the whole one 10; within one stretch,
        # 6 and 10. The chunk came from the whole one.
        scattered = ' '.join(f'x{i}' for i in range(1, 13))
        whole = ' '.join(f'y{i}' for i in range(1, 11))
        filler = ' f' * 20
        chunk_text = ' '.join(f'x{i}' for i in range(1, 7)) + ' ' + whole + ''.join(f'{filler} x{i}' for i in range(7, 13))
        mapper = s.Mapper({('scattered', 1, ''): scattered, ('whole', 1, ''): whole})

        source = mapper.best_source(chunk_text)

        self.assertEqual((('whole', 1, ''), 10), source)

    def test_given_laws_are_checked_against_the_registry(self):
        with self.assertRaisesRegex(Refused, 'does not have: nowhere'):
            s.laws_held(['kept', 'nowhere'], s.Mapper(self.LAWS), [], {'kept'})

    def lines(self, laws: dict) -> list:
        """One line whose chunks are whole articles: `laws` maps law -> how many of its articles."""
        return [{'chunks': [{'content': self.LAWS[(law, n, '')]} for law, count in laws.items()
                            for n in range(1, count + 1)]}]

    def test_a_given_law_that_none_of_his_chunks_comes_from_is_refused(self):
        with self.assertRaisesRegex(Refused, 'none of his chunks comes from: other'):
            s.laws_held(['kept', 'other'], s.Mapper(self.LAWS), self.lines({'kept': 3}), {'kept', 'other'})

    def test_the_override_keeps_an_unevidenced_given_law_with_a_warning(self):
        held = s.laws_held(['kept', 'other'], s.Mapper(self.LAWS), self.lines({'kept': 3}), {'kept', 'other'},
                           allow_unevidenced=True)

        self.assertEqual(['kept', 'other'], held['laws'])
        self.assertIn('given, but no chunk of his comes from it: other', held['warnings'])

    def test_given_laws_are_checked_against_the_evidence_and_an_inferred_law_not_given_is_warned_about(self):
        held = s.laws_held(['kept'], s.Mapper(self.LAWS), self.lines({'kept': 3, 'other': 2}), {'kept', 'other'})

        self.assertEqual(('given', ['kept'], {'kept': 3, 'other': 2}), (held['source'], held['laws'], held['evidence']))
        self.assertEqual([], held['warnings'])  # «other» is below the inference floor of 3 chunks
        warned = s.laws_held(['other'], s.Mapper(self.LAWS), self.lines({'kept': 3, 'other': 2}), {'kept', 'other'})
        self.assertEqual(['given, but the best source of only 2 of his chunks (inference needs 3): other',
                          'not given, but inferred from his chunks: kept (its items count as «lacking», not as his '
                          'failures)'], warned['warnings'])


class BestArmTests(unittest.TestCase):
    def test_our_best_arm_is_the_one_with_the_highest_recorded_recall_on_that_field(self):
        arms = [s.Arm(s.ArmSpec(name, field, name, 'baseline', None, recorded), {}, {}, '') for name, field, recorded in (
            ('more-hits', 'query', (0.70, 0.80, 0.5)), ('more-recall', 'query', (0.75, 0.70, 0.5)),
            ('other-field', 'question', (0.90, 0.90, 0.9)))]

        self.assertEqual('more-recall', s.best_arm(arms, 'query'))


class BootstrapTests(unittest.TestCase):
    def test_the_interval_is_the_bench_report_py_bootstrap(self):
        spread = random.Random(1)
        fixtures = {'steps of 0.5': [1.0, 0.0, -0.5, 0.5, 0.0, 1.0, 0.0, 0.0, -1.0, 0.5] * 4,
                    # each end differs from its neighbours at 4 places, so an off-by-one index shows
                    'spread values': [round(spread.uniform(-1, 1), 3) for _ in range(40)]}
        for name, diffs in fixtures.items():
            with self.subTest(name):
                rng = random.Random(20261106)  # rag-bench py/report.py:21-26, copied as the oracle
                means = [round(m, 4) for m in
                         sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(10000))]

                got = s.bootstrap(diffs)

                self.assertEqual((means[250], means[9749]), (got['lo'], got['hi']))
                self.assertEqual(got, s.bootstrap(diffs))  # seeded: the same every run
        self.assertTrue(len({*means[249:252]}) == 3 and len({*means[9748:9751]}) == 3)  # the spread fixture's

    def test_the_interval_excludes_zero_only_when_it_lies_wholly_on_one_side(self):
        self.assertTrue(s.bootstrap([1.0, 0.5, 1.0])['excludes_zero_above'])
        self.assertFalse(s.bootstrap([0.0, 0.0, 0.0])['excludes_zero_above'])
        self.assertTrue(s.bootstrap([-1.0, -0.5])['excludes_zero_below'])
        self.assertIsNone(s.bootstrap([]))

    def test_an_end_that_is_zero_in_exact_arithmetic_is_not_off_zero(self):
        # +1 on 5 items, -1/3 on 3 (an item with 3 expected articles), 0 on 32: the 2.5% resample's thirds cancel
        # exactly, but its float mean is 2.8e-18. That must read «not shown» / «does not beat», not «wins».
        ahead = [1.0] * 5 + [0.0 - 1 / 3] * 3 + [0.0] * 32
        rng = random.Random(s.SEED)
        raw_lo = sorted(sum(rng.choice(ahead) for _ in ahead) / len(ahead) for _ in range(s.RESAMPLES))[250]
        self.assertTrue(0 < raw_lo < 1e-15)  # the residue this test is about

        above, below = s.bootstrap(ahead), s.bootstrap([-d for d in ahead])

        self.assertEqual((0.0, False), (above['lo'], above['excludes_zero_above']))
        self.assertEqual((0.0, False), (abs(below['hi']), below['excludes_zero_below']))


class SentTextTests(unittest.TestCase):
    ITEMS = [s.Item('civil-code-01', 'العربون', 'هل أسترد العربون؟', frozenset({LEASE}), 'lease-law')]

    def results(self, **line):
        row = {'id': 'civil-code-01', 'field': 'query', 'sent': 'العربون', 'status': 'ok', 'chunks': []}
        row.update(line)
        return intake_w1.Results({}, [row], [2])

    def test_the_frozen_text_is_accepted(self):
        self.assertEqual(['civil-code-01'], list(s.field_lines(self.results(), 'query', self.ITEMS)))

    def test_other_text_than_the_frozen_set_is_refused(self):
        with self.assertRaisesRegex(Refused, 'sent other text'):
            s.field_lines(self.results(sent='العربون والاسترداد'), 'query', self.ITEMS)

    def test_an_id_outside_the_set_is_refused(self):
        with self.assertRaisesRegex(Refused, 'outside the eval set'):
            s.field_lines(self.results(id='penal-code-99'), 'query', self.ITEMS)

    def test_each_field_is_read_from_its_own_lines(self):
        both = intake_w1.Results({}, [
            {'id': 'civil-code-01', 'field': 'query', 'sent': 'العربون', 'status': 'ok', 'chunks': []},
            {'id': 'civil-code-01', 'field': 'question', 'sent': 'هل أسترد العربون؟', 'status': 'error', 'chunks': []}],
            [2, 3])

        query, question = (s.field_lines(both, field, self.ITEMS)['civil-code-01'] for field in ('query', 'question'))

        self.assertEqual(('query', 'question'), (query['field'], question['field']))


@unittest.skipUnless(REAL_DATA, 'real data: eval-final.json, the split or a source is missing')
class RealDataTests(unittest.TestCase):
    UNDER_HALF = ['civil-code-01', 'civil-code-02', 'civil-code-memo-03', 'majalla-01', 'majalla-03', 'penal-code-02',
                  'penal-code-07', 'penal-code-08', 'civil-procedure-01', 'civil-procedure-03', 'criminal-procedure-02',
                  'criminal-procedure-03', 'criminal-procedure-05', 'execution-02', 'sales-tax-02',
                  'investment-fund-01', 'bar-association-02']

    def test_the_strata_derived_from_the_recorded_terms_are_the_spec_s(self):
        strata = real_context().strata

        self.assertEqual(self.UNDER_HALF, [i for i, row in strata.items() if row['stratum'] == 'under'])
        self.assertEqual('half', strata['civil-code-08']['stratum'])

    def test_the_self_check_gives_back_the_baseline_figures(self):
        lines, failures = s.self_check(real_context(), names={'A0'}, targets=())

        self.assertEqual([], failures)
        self.assertEqual(3, len(lines))
        self.assertTrue(all('strict: W1 recall 0.5625, reached 51/80, stratum 4/17' in line for line in lines), lines)

    def test_no_run_of_neighbouring_articles_maps_an_article_it_does_not_hold(self):
        control = s.neighbour_runs(real_context(), 1200)

        self.assertEqual([], control['map_only_as_a_run'])
        self.assertEqual(207, control['runs'])

    def test_without_the_stretch_limit_runs_of_neighbours_do_map(self):
        # The control can fail: with a stretch as long as any chunk, the rule is the whole-chunk LCS again.
        context = real_context()
        with mock.patch.object(s, 'WINDOW_FACTOR', 10 ** 6):
            control = s.neighbour_runs(dataclasses.replace(context, mapper=s.Mapper(context.texts)), 1200)

        self.assertGreater(len(control['map_only_as_a_run']), 5)

    def test_a_scored_file_writes_ids_ranks_and_metrics_but_no_chunk_text(self):
        report, outputs, marker = real_scored()

        for text in outputs:
            self.assertNotIn(marker, text)
            self.assertNotIn(real_context().texts[('civil-code', 107, '')][:40], text)
        scored = json.loads(outputs[0])['fields']['query']
        self.assertEqual('T-B2', scored['best_arm'])
        self.assertIn('Decision rule (c), `query` field, against T-B2', outputs[1])

    def test_a_second_write_to_the_same_out_dir_is_refused(self):
        report, _, _ = real_scored()
        with tempfile.TemporaryDirectory() as tmp:
            s.write_outputs(report, Path(tmp) / 'out')

            with self.assertRaisesRegex(Refused, 'already in'):
                s.write_outputs(report, Path(tmp) / 'out')

    def test_civil_code_107_lacking_leaves_civil_code_01_out_of_the_held_scopes(self):
        report, _, _ = real_scored()

        held = report['fields']['query']['arms']['A0']['scopes']['held']['items']

        self.assertEqual((16, ['civil-code-01']), (held, report['articles_lacking']['items_left_out']))  # 14 + 3 - 1

    def test_rule_c_intervals_resample_in_the_split_s_order(self):
        # W1 (A0's own text) minus T-B2 on all 80, recall within budget, in split.json's key order. In the eval set's
        # order, which the scorer used before W2, the same differences give [-0.3937, -0.1875]. (On the 16 held
        # items here both orders happen to give the same ends.)
        interval = real_scored()[0]['fields']['query']['arms']['T-B2']['intervals']['all_recall']

        self.assertEqual((-0.2896, -0.3875, -0.1896), (interval['mean'], interval['lo'], interval['hi']))


@functools.lru_cache(maxsize=1)
def real_scored():
    """A file of A0's own top-6 articles, each with a marker word, taken in, screened clear, scored with civil-code
    and evidence held and civil-code 107 lacking, and written. Returns (report, the two outputs, the marker)."""
    context = real_context()
    a0 = next(a for a in context.arms if a.spec.name == 'A0')
    marker = 'نصسريللاختبارفقط'
    rows = []
    for item in context.items:
        chunks = [chunk(r, content=context.texts[k] + f' {marker}') for r, k in enumerate(a0.ranked[item.id][:6], 1)]
        rows.append({'id': item.id, 'field': 'query', 'sent': item.query, 'status': 'ok', 'error': None,
                     'chunks': chunks})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'quarantine'
        root.mkdir()
        make_results(Path(tmp) / 'in.jsonl', header(fields=['query']), rows)
        intake_w1.intake(Path(tmp) / 'in.jsonl', 'real-1', 'no', 'test', 'test', '2026-11-08', root, Path(tmp))
        intake_w1.record_screening('real-1', 'test', 'clear', root)
        report = s.score_results(*s.open_results(root / 'real-1' / 'w1-results.jsonl'), ['civil-code', 'evidence'],
                                 context, frozenset({('civil-code', 107, '')}))
        written = s.write_outputs(report, Path(tmp) / 'out')
        outputs = [path.read_text(encoding='utf-8') for path in written]
    return report, outputs, marker


# W2: own runs, halves, the deciding reading, the fallback sensitivity -----------------------------------------------

W2_DATASET = 'e' * 32
OUR_DOCUMENT = 'evidence.md'  # one of the 22 <registry slug>.md files the ingest tool uploads


def w2_manifest(**changes) -> dict:
    """The manifest of the deciding cell: its revision and canvas are the pinned ones."""
    value = {'w2': 1, 'created_at': '2026-11-08T13:00:00+00:00', 'engine': 'elasticsearch',
             'embedder': {'name': 'Qwen/Qwen3-Embedding-0.6B', 'revision': s.DECIDING['revision'], 'via': 'builtin-tei'},
             'ragflow_version': 'v0.27.3', 'ragflow_image_digest': 'sha256:' + '1' * 64,
             'dataset_id': W2_DATASET, 'language': 'English', 'document_count': 22, 'chunk_count': 6600,
             'predicted_chunk_count': 6600, 'all_match': True, 'canvas_sha256': s.DECIDING['canvas_sha256'],
             'upload_manifest_sha256': '3' * 64, 'file_shape': 'slug-title-served-v1', 'embedding_batch_size': 4,
             'max_concurrent_tasks': 1, 'tei_wait_patch': tei_wait_patch()}
    value.update(changes)
    return value


TEI_WAIT_DIFF = ('--- a/rag/llm/embedding_model.py\n+++ b/rag/llm/embedding_model.py\n@@ -1244,13 +1244,13 @@\n'
                 '     def encode(self, texts: list):\n'
                 '-        response = requests.post(url, json={"inputs": texts}, timeout=30)\n'
                 '+        response = requests.post(url, json={"inputs": texts}, timeout=900)\n'
                 ' \n'
                 '     def encode_queries(self, text: str):\n'
                 '-        response = requests.post(url, json={"inputs": text}, timeout=30)\n'
                 '+        response = requests.post(url, json={"inputs": text}, timeout=900)\n')


def tei_wait_patch(**changes) -> dict:
    """The manifest's tei_wait_patch, as rf_ingest.py writes it from patch_tei_wait.py's patch.json and diff: the
    approved patch."""
    return {'file': 'rag/llm/embedding_model.py', 'image_sha256': s.W2_TEI_WAIT_APPROVED['image_sha256'],
            'patched_sha256': s.W2_TEI_WAIT_APPROVED['patched_sha256'], 'changed_lines': [1247, 1253], 'wait_s': 900,
            'diff': TEI_WAIT_DIFF, **changes}


def own_chunk(rank: int, **changes) -> dict:
    return chunk(rank, **{'document_name': OUR_DOCUMENT, **changes})


def own_line(item_id: str = 'civil-code-01', field: str = 'query', sent: str = 'العربون', chunks=None, **changes):
    """A result line whose chunks come from one of our uploaded files."""
    return line(item_id, field, sent, chunks=[own_chunk(1), own_chunk(2)] if chunks is None else chunks, **changes)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OwnRunFolder:
    """A temporary out/ root with an engine folder, and a package whose two files the header hashes name."""

    def __init__(self, tmp: Path, engine: str = 'elasticsearch'):
        self.root = tmp / 'out'
        self.folder = self.root / engine
        self.folder.mkdir(parents=True)
        self.package = tmp / 'package'
        self.package.mkdir()
        (self.package / 'run_w1.py').write_bytes(b'# a stand-in for run_w1.py\n')
        (self.package / 'w1-queries.jsonl').write_bytes(b'{"w1": 1}\n')

    def own_header(self, **changes) -> dict:
        value = header(script_sha256=sha(self.package / 'run_w1.py'),
                       queries_sha256=sha(self.package / 'w1-queries.jsonl'),
                       datasets=[{'id': W2_DATASET, 'document_count': 22, 'chunk_count': 6600,
                                  'embedding_model': 'Qwen/Qwen3-Embedding-0.6B@Builtin', 'chunk_method': None,
                                  'parser_config': {}}],
                       settings=dict(s.OWN_ARMS['v3']), fields=['query'])
        value.update(changes)
        return value

    def write(self, head: dict, rows: list, arm: str = 'v3', manifest: dict | None = None) -> Path:
        if manifest is not None:
            (self.folder / s.W2_MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
        return make_results(self.folder / f'w2-results-{arm}.jsonl', head, rows)

    def open(self, path: Path | None = None, manifest: Path | None = None) -> tuple:
        return s.open_own_run(path or self.folder / 'w2-results-v3.jsonl', manifest or self.folder / s.W2_MANIFEST,
                              self.package, self.root)


class OwnRunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.run = OwnRunFolder(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()


class OwnRunGateTests(OwnRunCase):
    """--own-run takes our own file only: under out/<engine>/, beside a W2 manifest naming its dataset."""

    def test_an_own_run_beside_its_manifest_is_accepted(self):
        self.run.write(self.run.own_header(), [own_line()], manifest=w2_manifest())

        own, results = self.run.open()

        self.assertEqual(('v3', W2_DATASET, 1), (own.arm, own.manifest['dataset_id'], len(results.lines)))

    def test_a_walid_shaped_file_without_a_manifest_is_refused(self):
        self.run.write(header(), [line()])  # his header: another dataset, 5 documents, 900 chunks

        with self.assertRaisesRegex(Refused, 'no w2-manifest.json beside the results file'):
            self.run.open()

    def test_a_walid_shaped_file_beside_our_manifest_is_refused(self):
        self.run.write(header(), [line()], manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'does not name exactly the manifest\'s dataset'):
            self.run.open()

    def test_a_file_outside_the_own_run_folder_is_refused(self):
        inbox = self.tmp / 'inbox'
        inbox.mkdir()
        path = make_results(inbox / 'w2-results-v3.jsonl', self.run.own_header(), [own_line()])
        (inbox / s.W2_MANIFEST).write_text(json.dumps(w2_manifest()), encoding='utf-8')

        with self.assertRaisesRegex(Refused, 'scores only a file under'):
            self.run.open(path, inbox / s.W2_MANIFEST)

    def test_a_dataset_id_other_than_the_manifest_s_is_refused(self):
        head = self.run.own_header()
        head['datasets'][0]['id'] = 'a' * 32
        self.run.write(head, [own_line()], manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'does not name exactly the manifest\'s dataset'):
            self.run.open()

    def test_a_header_naming_a_second_dataset_beside_ours_is_refused(self):
        head = self.run.own_header()
        head['datasets'].append({**head['datasets'][0], 'id': 'a' * 32})
        self.run.write(head, [own_line()], manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'does not name exactly the manifest\'s dataset'):
            self.run.open()

    def test_a_manifest_whose_all_match_is_anything_but_true_is_refused(self):
        for value in (False, 'false', 'true', 1):  # the JSON boolean true only, not a truthy value
            with self.subTest(all_match=value):
                self.run.write(self.run.own_header(), [own_line()], manifest=w2_manifest(all_match=value))

                with self.assertRaisesRegex(Refused, '"all_match" is not true'):
                    self.run.open()

    def test_document_or_chunk_counts_other_than_the_manifest_s_are_refused(self):
        for name, value in (('document_count', 21), ('chunk_count', 6599)):
            with self.subTest(name=name):
                head = self.run.own_header()
                head['datasets'][0][name] = value
                self.run.write(head, [own_line()], manifest=w2_manifest())

                with self.assertRaisesRegex(Refused, f'datasets\\[1\\].{name} differs'):
                    self.run.open()

    def test_header_hashes_other_than_the_package_s_are_refused(self):
        for name in ('script_sha256', 'queries_sha256'):
            with self.subTest(name=name):
                self.run.write(self.run.own_header(**{name: '9' * 64}), [own_line()], manifest=w2_manifest())

                with self.assertRaisesRegex(Refused, f'header\'s {name} is not the package\'s'):
                    self.run.open()

    def test_settings_other_than_the_arm_s_are_refused(self):
        rt = dict(s.OWN_ARMS['rt'])
        self.run.write(self.run.own_header(settings=rt), [own_line()], manifest=w2_manifest())  # named v3, sent rt

        with self.assertRaisesRegex(Refused, 'not the v3 arm\'s'):
            self.run.open()
        path = self.run.write(self.run.own_header(settings=rt), [own_line()], arm='rt')
        self.assertEqual('rt', self.run.open(path)[0].arm)

    def test_settings_that_differ_from_the_arm_s_in_any_one_key_are_refused(self):
        for name, value in (('similarity_threshold', 0.1), ('top_k', 512), ('rerank_id', 'a-reranker')):
            with self.subTest(name=name):
                settings = {**s.OWN_ARMS['v3'], name: value}  # rerank_id is not sent by v3 at all
                self.run.write(self.run.own_header(settings=settings), [own_line()], manifest=w2_manifest())

                with self.assertRaisesRegex(Refused, 'not the v3 arm\'s'):
                    self.run.open()

    def test_a_server_version_other_than_the_manifest_s_is_refused(self):
        self.run.write(self.run.own_header(ragflow_version='v0.27.2'), [own_line()], manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'ragflow_version is not the manifest\'s'):
            self.run.open()

    def test_the_results_contract_screens_still_run(self):
        rows = [line(chunks=[chunk(1, content='see https://example.org')])]
        self.run.write(self.run.own_header(), rows, manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'looks like it holds a URL'):
            self.run.open()

    def test_a_manifest_that_is_not_beside_the_results_or_names_another_engine_is_refused(self):
        self.run.write(self.run.own_header(), [own_line()], manifest=w2_manifest(engine='infinity'))
        elsewhere = self.tmp / s.W2_MANIFEST
        elsewhere.write_text(json.dumps(w2_manifest()), encoding='utf-8')

        with self.assertRaisesRegex(Refused, 'must be the w2-manifest.json beside the results file'):
            self.run.open(manifest=elsewhere)
        with self.assertRaisesRegex(Refused, 'the manifest\'s engine is infinity'):
            self.run.open()

    def test_a_results_file_not_named_for_an_arm_is_refused(self):
        path = make_results(self.run.folder / 'w1-results.jsonl', self.run.own_header(), [own_line()])

        with self.assertRaisesRegex(Refused, 'named w2-results-v3.jsonl or w2-results-rt.jsonl'):
            self.run.open(path)

    def test_a_manifest_that_breaks_the_contract_is_refused(self):
        revision = s.DECIDING['revision']
        broken = {'an extra key': ({**w2_manifest(), 'note': 'x'}, 'keys outside the contract'),
                  'a missing key': ({k: v for k, v in w2_manifest().items() if k != 'canvas_sha256'}, 'missing keys'),
                  'another contract version': (w2_manifest(w2=2), '"w2" must be 1'),
                  'a time that is not ISO-8601': (w2_manifest(created_at='8 November 2026'), '"created_at"'),
                  '21 documents': (w2_manifest(document_count=21), '"document_count"'),
                  'another file shape': (w2_manifest(file_shape='slug-demoted'), '"file_shape"'),
                  'another embedder route': (w2_manifest(embedder={'name': 'bge-m3', 'revision': revision,
                                                                   'via': 'ollama'}), '"embedder.via"'),
                  'a revision that is a branch name': (w2_manifest(embedder={'name': 'Qwen/Qwen3-Embedding-0.6B',
                                                                             'revision': 'main', 'via': 'builtin-tei'}),
                                                       '"embedder.revision"'),
                  'another RAGFlow': (w2_manifest(ragflow_version='v0.20.0'), '"ragflow_version"'),
                  'a version that only contains 0.27.3': (w2_manifest(ragflow_version='v0.27.30'), '"ragflow_version"'),
                  'an image without a digest': (w2_manifest(ragflow_image_digest='infiniflow/ragflow:v0.27.3'),
                                                '"ragflow_image_digest"'),
                  'counts that disagree': (w2_manifest(predicted_chunk_count=6601), '"predicted_chunk_count"'),
                  'a short dataset id': (w2_manifest(dataset_id='e' * 31), '"dataset_id"'),
                  'a canvas sha that is not hex': (w2_manifest(canvas_sha256='G' * 64), '"canvas_sha256"'),
                  'a short upload manifest sha': (w2_manifest(upload_manifest_sha256='3' * 63),
                                                  '"upload_manifest_sha256"'),
                  'a batch size of 0': (w2_manifest(embedding_batch_size=0), '"embedding_batch_size"'),
                  'a stage-2 manifest without the TEI-wait fields': (
                      {k: v for k, v in w2_manifest().items() if k not in ('tei_wait_patch', 'max_concurrent_tasks')},
                      'missing keys: max_concurrent_tasks, tei_wait_patch'),
                  'a concurrency of 0': (w2_manifest(max_concurrent_tasks=0), '"max_concurrent_tasks"'),
                  'a concurrency given as text': (w2_manifest(max_concurrent_tasks='1'), '"max_concurrent_tasks"'),
                  'the whole patch.json, anchors included': (
                      w2_manifest(tei_wait_patch={**tei_wait_patch(), 'anchors': []}), '"tei_wait_patch" must hold'),
                  'a patch of another file': (w2_manifest(tei_wait_patch=tei_wait_patch(file='rag/llm/chat_model.py')),
                                              '"tei_wait_patch.file"'),
                  'the shipped wait': (w2_manifest(tei_wait_patch=tei_wait_patch(wait_s=30)), '"tei_wait_patch.wait_s"'),
                  'a wait given as text': (w2_manifest(tei_wait_patch=tei_wait_patch(wait_s='900')),
                                           '"tei_wait_patch.wait_s"'),
                  'a patched sha that is not hex': (w2_manifest(tei_wait_patch=tei_wait_patch(patched_sha256='Z' * 64)),
                                                    '"tei_wait_patch.patched_sha256"'),
                  'an image sha with a newline': (
                      w2_manifest(tei_wait_patch=tei_wait_patch(image_sha256='4' * 64 + '\n')),
                      '"tei_wait_patch.image_sha256"'),
                  'a patch that changed nothing': (
                      w2_manifest(tei_wait_patch=tei_wait_patch(patched_sha256=s.W2_TEI_WAIT_APPROVED['image_sha256'])),
                      'nothing was changed'),
                  'one changed line': (w2_manifest(tei_wait_patch=tei_wait_patch(changed_lines=[1247])),
                                       '"tei_wait_patch.changed_lines"'),
                  'a patch without its diff': (
                      w2_manifest(tei_wait_patch={k: v for k, v in tei_wait_patch().items() if k != 'diff'}),
                      '"tei_wait_patch" must hold'),
                  'a diff of another file': (
                      w2_manifest(tei_wait_patch=tei_wait_patch(diff=TEI_WAIT_DIFF.replace('embedding_model', 'chat_model'))),
                      '"tei_wait_patch.diff" must be the unified diff'),
                  'a diff that is not text': (w2_manifest(tei_wait_patch=tei_wait_patch(diff=None)),
                                              '"tei_wait_patch.diff" must be the unified diff'),
                  'a diff of another wait than the record\'s': (w2_manifest(tei_wait_patch=tei_wait_patch(wait_s=600)),
                                                                '"tei_wait_patch.diff" must change only'),
                  'a diff that changes a third line': (
                      w2_manifest(tei_wait_patch=tei_wait_patch(diff=TEI_WAIT_DIFF + '-    x = 1\n+    x = 2\n')),
                      '"tei_wait_patch.diff" must change only')}
        for name, (manifest, message) in broken.items():
            with self.subTest(name):
                self.run.write(self.run.own_header(), [own_line()], manifest=manifest)

                with self.assertRaisesRegex(Refused, f'^the W2 manifest: .*{re.escape(message)}'):
                    self.run.open()

    def test_a_results_file_below_the_engine_folder_is_refused(self):
        deep = self.run.root / 'nested' / 'elasticsearch'
        deep.mkdir(parents=True)
        (deep / s.W2_MANIFEST).write_text(json.dumps(w2_manifest()), encoding='utf-8')
        path = make_results(deep / 'w2-results-v3.jsonl', self.run.own_header(), [own_line()])

        with self.assertRaisesRegex(Refused, 'directly in .*<engine>/, not in a folder below it'):
            self.run.open(path, deep / s.W2_MANIFEST)

    def test_a_link_under_another_name_is_refused(self):
        # A file link needs a privilege Windows does not grant by default, so the link is os.path.realpath's answer.
        target = make_results(self.run.folder / 'copied.jsonl', self.run.own_header(), [own_line()])
        (self.run.folder / s.W2_MANIFEST).write_text(json.dumps(w2_manifest()), encoding='utf-8')
        link, realpath = self.run.folder / 'w2-results-v3.jsonl', s.os.path.realpath

        with mock.patch.object(s.os.path, 'realpath', lambda p: realpath(target if Path(p) == link else p)), \
                self.assertRaisesRegex(Refused, 'is a link to another file'):
            self.run.open(link)

    def test_chunks_from_a_document_that_is_not_one_of_our_uploads_are_refused(self):
        # The shape of Walid's document names (intake_w1.py), beside our manifest and header.
        rows = [own_line(chunks=[own_chunk(1), own_chunk(2, document_name='IQRA_LAW_Criminal_Procedure_Articles_'
                                                                         '1-370_REVIEW.md')])]
        self.run.write(self.run.own_header(), rows, manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, '^1 returned chunks carry a document name that is not <registry slug>.md'):
            self.run.open()

    def test_a_registry_without_the_manifest_s_22_laws_is_refused(self):
        laws = json.loads(s.REGISTRY.read_text(encoding='utf-8'))
        laws['laws'] = laws['laws'][:21]
        registry = self.tmp / 'laws.json'
        registry.write_text(json.dumps(laws, ensure_ascii=False), encoding='utf-8')
        self.run.write(self.run.own_header(), [own_line()], manifest=w2_manifest())

        with self.assertRaisesRegex(Refused, 'the registry has 21 laws, not the manifest\'s 22 documents'):
            s.open_own_run(self.run.folder / 'w2-results-v3.jsonl', self.run.folder / s.W2_MANIFEST,
                           self.run.package, self.run.root, registry)

    def test_every_registry_slug_names_an_upload(self):
        rows = [own_line(chunks=[own_chunk(rank, document_name=f'{slug}.md')
                                 for rank, slug in enumerate(sorted(s.registry_slugs()), 1)])]
        self.run.write(self.run.own_header(), rows, manifest=w2_manifest())

        own, results = self.run.open()

        self.assertEqual(22, len(results.lines[0]['chunks']))

    def test_the_arm_settings_are_what_run_w1_sends(self):
        base = ['--base-url', 'http://127.0.0.1:9380', '--api-key-file', 'key']

        v3 = run_w1.retrieval_settings(run_w1.build_parser().parse_args(base))
        rt = run_w1.retrieval_settings(run_w1.build_parser().parse_args(base + ['--vector-similarity-weight', '0.4']))

        self.assertEqual((s.OWN_ARMS['v3'], s.OWN_ARMS['rt']), (v3, rt))


class OwnRunOptionTests(OwnRunCase):
    """The command line keeps W1's options and W2's apart, and --w2-decide reads only the deciding cell."""

    def main(self, *argv) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(s, 'OWN_ROOT', self.run.root):
            code = s.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_w2_options_without_own_run_are_refused(self):
        for option in (['--w2-decide'], ['--manifest', 'm.json'], ['--fallback', 'f.json']):
            with self.subTest(option=option[0]):
                code, _, err = self.main('--results', 'x.jsonl', '--out-dir', 'out', *option)

                self.assertEqual((2, True), (code, f'{option[0]}: only with --own-run' in err))

    def test_own_run_needs_a_manifest_and_refuses_w1_options(self):
        self.assertIn('--own-run needs --manifest', self.main('--results', 'x', '--out-dir', 'o', '--own-run')[2])
        code, _, err = self.main('--results', 'x', '--out-dir', 'o', '--own-run', '--manifest', 'm',
                                 '--laws-held', 'evidence')
        self.assertEqual((2, True), (code, 'an own run holds our whole corpus' in err))

    def test_w2_decide_on_a_file_that_is_not_the_deciding_cell_is_refused(self):
        infinity = OwnRunFolder(self.tmp / 'second', engine='infinity')
        infinity.root = self.run.root  # the same out/ root, another engine folder
        infinity.folder = self.run.root / 'infinity'
        infinity.folder.mkdir()
        path = infinity.write(infinity.own_header(), [own_line()], manifest=w2_manifest(engine='infinity'))

        code, out, err = self.main('--results', str(path), '--own-run', '--manifest', str(infinity.folder / s.W2_MANIFEST),
                                   '--package', str(infinity.package), '--out-dir', str(self.tmp / 'score'), '--w2-decide')

        self.assertEqual(2, code)
        self.assertIn('--w2-decide reads only the pre-registered deciding cell', err)
        self.assertIn('the engine is infinity, not elasticsearch', err)
        self.assertEqual('', out)  # refused before the library is loaded

    def decide(self, head: dict, *extra) -> tuple:
        path = self.run.write(head, [own_line()], manifest=w2_manifest())
        return self.main('--results', str(path), '--own-run', '--manifest', str(self.run.folder / s.W2_MANIFEST),
                         '--package', str(self.run.package), '--out-dir', str(self.tmp / 'score'), '--w2-decide', *extra)

    def test_w2_decide_with_a_split_other_than_the_bench_s_is_refused(self):
        # The same halves with a trailing newline: another sha256, so not the split T-B2 was tuned against.
        split = self.tmp / 'split.json'
        split.write_bytes(s.SPLIT.read_bytes() + b'\n')

        code, out, err = self.decide(self.run.own_header(), '--split', str(split))

        self.assertEqual((2, ''), (code, out))
        self.assertIn(f'split.json {sha(split)[:12]} is not the bench split', err)

    def test_w2_decide_on_a_dataset_the_server_says_has_another_embedder_is_refused(self):
        head = self.run.own_header()
        head['datasets'][0]['embedding_model'] = 'BAAI/bge-m3@Builtin'  # the manifest still says Qwen3

        code, out, err = self.decide(head)

        self.assertEqual((2, ''), (code, out))
        self.assertIn('the embedding model the server reports for the dataset is not Qwen/Qwen3-Embedding-0.6B', err)


class SplitTests(unittest.TestCase):
    ITEMS = [s.Item(f'lease-law-{n:02d}', 'ايجار', 'ايجار؟', frozenset({LEASE}), 'lease-law') for n in range(1, 5)]

    def write(self, value) -> Path:
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        with handle:
            json.dump(value, handle)
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_the_split_maps_each_item_to_its_half(self):
        split = {'lease-law-01': 'A', 'lease-law-02': 'B', 'lease-law-03': 'B', 'lease-law-04': 'A'}

        self.assertEqual(split, s.load_split(self.write(split), self.ITEMS))

    def test_the_split_keeps_the_file_s_key_order_not_the_eval_set_s(self):
        split = {'lease-law-03': 'B', 'lease-law-01': 'A', 'lease-law-04': 'A', 'lease-law-02': 'B'}

        self.assertEqual(list(split), list(s.load_split(self.write(split), self.ITEMS)))

    def test_only_the_bench_split_s_sha256_is_recorded_as_pinned(self):
        other = self.write({'lease-law-01': 'A'})

        self.assertEqual((True, False), (s.split_source(s.SPLIT)['pinned'], s.split_source(other)['pinned']))

    def test_a_split_that_is_not_two_equal_halves_of_the_eval_set_is_refused(self):
        bad = {'an id outside the set': {'lease-law-01': 'A', 'lease-law-02': 'B', 'lease-law-03': 'B',
                                         'other-law-01': 'A'},
               'a missing id': {'lease-law-01': 'A', 'lease-law-02': 'B', 'lease-law-03': 'B'},
               'a third half': {'lease-law-01': 'A', 'lease-law-02': 'B', 'lease-law-03': 'C', 'lease-law-04': 'A'},
               'unequal halves': {'lease-law-01': 'A', 'lease-law-02': 'B', 'lease-law-03': 'B', 'lease-law-04': 'B'}}
        for name, split in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                s.load_split(self.write(split), self.ITEMS)

    def test_the_durable_split_is_read_first_and_the_bench_s_only_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench_split = Path(tmp) / 'bench' / 'data' / 'split.json'
            bench_split.parent.mkdir(parents=True)
            bench_split.write_text('{}', encoding='utf-8')
            with mock.patch.object(s, 'SPLIT', Path(tmp) / 'missing.json'):
                path, warning = s.resolve_split(None, Path(tmp) / 'bench')

            self.assertEqual(bench_split, path)
            self.assertIn('the durable copy', warning)
        self.assertEqual((s.SPLIT, None), s.resolve_split(None))
        with self.assertRaisesRegex(Refused, '--split: no file'):
            s.resolve_split(Path('no-such-split.json'))

    def test_no_split_at_all_is_refused_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(s, 'SPLIT', Path(tmp) / 'missing.json'):
            with self.assertRaisesRegex(Refused, 'neither the durable copy .* nor the bench\'s'):
                s.resolve_split(None, Path(tmp) / 'bench')

    def test_without_the_durable_copies_or_the_bench_folder_the_command_refuses_naming_each_file(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(s.DURABLE, clear=True):
            code = s.main(['--self-check', '--bench', str(Path(tmp) / 'bench')])

        self.assertEqual(2, code)
        self.assertRegex(err.getvalue(), r'^refused: missing: .*bench/results/rows-round2\.jsonl, '
                                         r'.*bench/results/perf/pg-rows-question\.jsonl, .*bench/data/eval\.jsonl\.')

    def test_without_the_bench_folder_every_source_has_its_durable_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = s.missing_sources(Path(tmp) / 'bench')

        self.assertEqual([], missing)

    def test_the_strata_terms_prefer_the_durable_copy_and_warn_when_it_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            durable, bench = Path(tmp) / 'evidence', Path(tmp) / 'bench'
            durable.mkdir()
            (durable / 'rag-bench-eval.jsonl').write_text('', encoding='utf-8')

            found = s.strata_source(bench, durable)
            missing = s.strata_source(bench, Path(tmp) / 'nowhere')

        self.assertEqual((durable / 'rag-bench-eval.jsonl', True, None), found)
        self.assertEqual((bench / 'data/eval.jsonl', False), missing[:2])
        self.assertIn('data/eval.jsonl: the durable copy', missing[2])

    def test_arm_sources_prefer_the_durable_copy_and_warn_when_it_is_missing(self):
        t_b2 = next(spec for spec in s.ARMS if spec.name == 'T-B2')
        a0q = next(spec for spec in s.ARMS if spec.name == 'A0q')
        with tempfile.TemporaryDirectory() as tmp:
            durable, bench = Path(tmp) / 'evidence', Path(tmp) / 'bench'
            durable.mkdir()
            (durable / 'rag-bench-rows-round2.jsonl').write_text('', encoding='utf-8')
            (durable / 'rag-bench-pg-rows-question.jsonl').write_text('', encoding='utf-8')

            found = s.arm_source(t_b2, bench, s.BASELINE, durable)
            missing = s.arm_source(t_b2, bench, s.BASELINE, Path(tmp) / 'nowhere')
            a0q_found = s.arm_source(a0q, bench, s.BASELINE, durable)
            a0q_missing = s.arm_source(a0q, bench, s.BASELINE, Path(tmp) / 'nowhere')

        self.assertEqual((durable / 'rag-bench-rows-round2.jsonl', True, None), found)
        self.assertEqual((bench / 'results/rows-round2.jsonl', False), missing[:2])
        self.assertIn('the durable copy', missing[2])
        self.assertEqual((durable / 'rag-bench-pg-rows-question.jsonl', True, None), a0q_found)
        self.assertEqual((bench / 'results/perf/pg-rows-question.jsonl', False), a0q_missing[:2])
        self.assertIn('results/perf/pg-rows-question.jsonl: the durable copy', a0q_missing[2])

    def test_t_b2_s_source_for_the_deciding_gate_is_the_file_arm_source_picks(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / 'bench'
            (bench / 'results').mkdir(parents=True)
            (bench / 'results' / 'rows-round2.jsonl').write_bytes(b'{}\n')

            from_bench = s.t_b2_source(bench, s.BASELINE, Path(tmp) / 'no-evidence')
            nowhere = s.t_b2_source(Path(tmp) / 'no-bench', s.BASELINE, Path(tmp) / 'no-evidence')
        durable = s.t_b2_source()

        self.assertEqual((False, hashlib.sha256(b'{}\n').hexdigest()), (from_bench['durable'], from_bench['sha256']))
        self.assertEqual((False, None), (nowhere['durable'], nowhere['sha256']))
        self.assertEqual((True, s.T_B2_ROWS_SHA256), (durable['durable'], durable['sha256']))


class HalfScopeTests(unittest.TestCase):
    def test_halves_add_the_held_items_of_each_half(self):
        halves = {'lease-law-01': 'B', 'sale-law-01': 'B', 'civil-01': 'A'}

        scored = s.score_field('query', ScopeTests.ITEMS, ScopeTests.LINES, [ScopeTests.ARM], MAPPER, TEXTS,
                               ScopeTests.STRATA, {'lease-law', 'civil'}, halves=halves)
        scopes = scored['arms']['X']['scopes']

        self.assertEqual((1, 1), (scopes['half_A']['items'], scopes['half_B']['items']))  # sale-law is not held
        self.assertEqual((1, 1), (scopes['half_B']['w1_reached'], scopes['half_B']['arm_reached']))
        self.assertIn('half_B_recall_vs_rule', scored['arms']['X']['intervals'])
        self.assertEqual('B', scored['items'][0]['half'])

    def test_with_a_split_each_scope_is_resampled_in_the_split_s_order(self):
        # The bootstrap resamples by position, so the order of the differences moves the interval's ends
        # (RealDataW2Tests reproduces the bench's interval only in split order). Here: the lists it is handed.
        halves = dict(reversed(list(B_HALVES.items())))  # the same halves, the items in the other order
        reached = set(B_IDS[:7]) | set(A_IDS[:1])
        lines = {i.id: {'status': 'ok', 'chunks': [{'content': TEXTS[LEASE] if i.id in reached else 'نص'}]}
                 for i in B_ITEMS}
        ranked = {i.id: (LEASE,) if i.id in B_IDS[-3:] else (CONTRACT,) for i in B_ITEMS}
        diffs = {i: float((i in reached) - (i in B_IDS[-3:])) for i in halves}

        with mock.patch.object(s, 'bootstrap', wraps=s.bootstrap) as spy:
            s.score_field('query', B_ITEMS, lines, [arm('T-B2', 'query', ranked)], MAPPER, TEXTS,
                          {i.id: {'stratum': 'half'} for i in B_ITEMS}, {'lease-law'}, halves=halves)
        handed = [call.args[0] for call in spy.call_args_list]

        self.assertIn([diffs[i] for i in halves if halves[i] == 'B'], handed)  # half B, in split order
        self.assertIn([diffs[i] for i in halves], handed)  # all held items, in split order
        self.assertNotIn([diffs[i] for i in B_IDS], handed)  # half B in the eval set's order
        self.assertNotIn([diffs[i.id] for i in B_ITEMS], handed)

    def test_without_halves_no_half_scope_is_scored(self):
        scopes = s.score_field('query', ScopeTests.ITEMS, ScopeTests.LINES, [ScopeTests.ARM], MAPPER, TEXTS,
                               ScopeTests.STRATA, {'lease-law'})['arms']['X']['scopes']

        self.assertNotIn('half_B', scopes)


def own(engine: str = 'elasticsearch', arm_name: str = 'v3', **embedder) -> s.OwnRun:
    manifest = w2_manifest(engine=engine)
    manifest['embedder'].update(embedder)
    return s.OwnRun(manifest, '0' * 64, 'out/x/w2-manifest.json', '0' * 64, arm_name, Path('w2-results.jsonl'))


def own_with(**manifest_changes) -> s.OwnRun:
    return dataclasses.replace(own(), manifest=w2_manifest(**manifest_changes))


B_ITEMS = [s.Item(f'lease-law-{n:02d}', 'ايجار', 'ايجار؟', frozenset({LEASE}), 'lease-law') for n in range(1, 45)]
B_HALVES = {item.id: 'A' if n < 4 else 'B' for n, item in enumerate(B_ITEMS)}  # 4 in half A, 40 in half B
B_IDS = [item.id for item in B_ITEMS if B_HALVES[item.id] == 'B']
A_IDS = [item.id for item in B_ITEMS if B_HALVES[item.id] == 'A']


class W2DecisionTests(unittest.TestCase):
    """The pre-registered reading: W2 vs T-B2, half B (40 items), both through the mapping rule, «wins» only
    when the paired-bootstrap interval lies above zero."""

    def decide(self, w2_reaches=(), arm_reaches=(), arm_through_rule=()) -> dict:
        """W2 serves LEASE on the items in `w2_reaches`, nothing on the rest. T-B2 serves LEASE on the items in
        `arm_reaches`, ECHO (which holds half of LEASE: by keys a miss, through the rule a hit) on those in
        `arm_through_rule`, and CONTRACT on the rest."""
        lines = {i.id: {'status': 'ok', 'chunks': [{'content': TEXTS[LEASE] if i.id in w2_reaches else 'نص'}]}
                 for i in B_ITEMS}
        ranked = {i.id: (LEASE,) if i.id in arm_reaches else (ECHO,) if i.id in arm_through_rule else (CONTRACT,)
                  for i in B_ITEMS}
        scored = s.score_field('query', B_ITEMS, lines, [arm('T-B2', 'query', ranked)], DECISION_MAPPER,
                               DECISION_TEXTS, {i.id: {'stratum': 'half'} for i in B_ITEMS}, {'lease-law'},
                               halves=B_HALVES)
        self.scored = scored
        return s.w2_decision(scored, own(), [], s.SPLIT_SHA256)

    def test_w2_wins_when_its_half_b_interval_lies_above_zero(self):
        decision = self.decide(w2_reaches=B_IDS)

        self.assertEqual(('wins', 'above zero', None, 40), (decision['verdict'], decision['side'], decision['note'],
                                                            decision['items']))
        self.assertEqual((1.0, 1.0), (decision['interval']['lo'], decision['interval']['hi']))

    def test_w2_behind_t_b2_on_half_b_is_not_shown_and_says_it_is_behind(self):
        decision = self.decide(arm_reaches=B_IDS)

        self.assertEqual(('not shown', 'below zero', 'W2 is behind T-B2 on half B: the whole interval lies below zero'),
                         (decision['verdict'], decision['side'], decision['note']))

    def test_a_tie_on_half_b_is_not_shown_and_says_what_40_items_cannot_detect(self):
        decision = self.decide(w2_reaches=B_IDS, arm_reaches=B_IDS)

        self.assertEqual(('not shown', 'includes zero', 0.0, 0.0, 'a smaller effect cannot be detected on 40 items'),
                         (decision['verdict'], decision['side'], decision['interval']['lo'], decision['interval']['hi'],
                          decision['note']))

    def test_on_40_items_three_more_reached_are_not_shown_and_four_win(self):
        # The resampled mean is 0 with probability (37/40)^40 = 4.4% for three, (36/40)^40 = 1.5% for four.
        three, four = self.decide(w2_reaches=B_IDS[:3]), self.decide(w2_reaches=B_IDS[:4])

        self.assertEqual(('not shown', 0.0, 0.075), (three['verdict'], three['interval']['lo'], three['interval']['mean']))
        self.assertEqual(('wins', 0.025), (four['verdict'], four['interval']['lo']))

    def test_the_decision_reads_half_b_only(self):
        decision = self.decide(w2_reaches=A_IDS)  # W2 ahead on every half-A item, level on half B

        self.assertEqual(('not shown', 'includes zero'), (decision['verdict'], decision['side']))
        self.assertTrue(self.scored['arms']['T-B2']['intervals']['half_A_recall_vs_rule']['excludes_zero_above'])

    def test_the_decision_scores_t_b2_through_the_rule_not_by_its_keys(self):
        decision = self.decide(w2_reaches=B_IDS, arm_through_rule=B_IDS)
        by_keys = s.w2_reading(self.scored, 'T-B2', 'half_B', by='keys')

        self.assertEqual(('not shown', 'includes zero'), (decision['verdict'], decision['side']))
        self.assertEqual('above zero', by_keys['side'])

    def test_an_expected_article_served_only_past_t_b2_s_budget_is_a_miss(self):
        # T-B2 serves CONTRACT, so its budget is CONTRACT's length. W2's first chunk fills it, and LEASE, its second,
        # starts past the budget: it never counts, so W2 reaches nothing.
        filler = 'نص ' * len(DECISION_TEXTS[CONTRACT])
        lines = {i.id: {'status': 'ok', 'chunks': [{'content': filler}, {'content': TEXTS[LEASE]}]} for i in B_ITEMS}
        scored = s.score_field('query', B_ITEMS, lines, [arm('T-B2', 'query', {i.id: (CONTRACT,) for i in B_ITEMS})],
                               DECISION_MAPPER, DECISION_TEXTS, {i.id: {'stratum': 'half'} for i in B_ITEMS},
                               {'lease-law'}, halves=B_HALVES)

        decision = s.w2_decision(scored, own(), [], s.SPLIT_SHA256)

        self.assertEqual(('not shown', 0, 0.0), (decision['verdict'], decision['w2_reached'], decision['w2_recall']))

    def test_a_failed_half_b_line_is_listed_and_counts_as_a_miss(self):
        lines = {i.id: {'status': 'ok', 'chunks': [{'content': TEXTS[LEASE]}]} for i in B_ITEMS}
        lines[B_IDS[0]] = {'status': 'error', 'chunks': []}
        scored = s.score_field('query', B_ITEMS, lines, [arm('T-B2', 'query', {i.id: (LEASE,) for i in B_ITEMS})],
                               DECISION_MAPPER, DECISION_TEXTS, {i.id: {'stratum': 'half'} for i in B_ITEMS},
                               {'lease-law'}, halves=B_HALVES)

        decision = s.w2_decision(scored, own(), [], s.SPLIT_SHA256)

        self.assertEqual(([B_IDS[0]], 39), (decision['not_ok_in_scope'], decision['w2_reached']))

    def test_a_failed_half_a_line_is_not_listed_in_the_deciding_scope(self):
        lines = {i.id: {'status': 'ok', 'chunks': [{'content': TEXTS[LEASE]}]} for i in B_ITEMS}
        lines[A_IDS[0]] = {'status': 'error', 'chunks': []}
        scored = s.score_field('query', B_ITEMS, lines, [arm('T-B2', 'query', {i.id: (LEASE,) for i in B_ITEMS})],
                               DECISION_MAPPER, DECISION_TEXTS, {i.id: {'stratum': 'half'} for i in B_ITEMS},
                               {'lease-law'}, halves=B_HALVES)

        decision = s.w2_decision(scored, own(), [], s.SPLIT_SHA256)

        self.assertEqual(([], [A_IDS[0]]), (decision['not_ok_in_scope'], scored['not_ok']))

    def test_a_file_that_is_not_the_deciding_cell_gets_no_verdict(self):
        decision = s.w2_decision(None, own(), ['the engine is infinity, not elasticsearch'], s.SPLIT_SHA256)

        self.assertEqual((False, None), (decision['deciding_cell'], decision.get('verdict')))

    T_B2_ROWS = {'sha256': s.T_B2_ROWS_SHA256, 'durable': True}

    def gaps(self, run=None, model='Qwen/Qwen3-Embedding-0.6B@Builtin', fields=('query',), split=s.SPLIT_SHA256,
             against=None) -> list:
        head = {'fields': list(fields), 'datasets': [{'embedding_model': model}]}
        return s.deciding_gaps(run or own(), head, split, self.T_B2_ROWS if against is None else against)

    def test_the_deciding_cell_has_no_gap(self):
        self.assertEqual([], self.gaps(fields=('query', 'question')))
        for model in ('Qwen/Qwen3-Embedding-0.6B', 'Qwen/Qwen3-Embedding-0.6B@default@Builtin'):
            with self.subTest(model):
                self.assertEqual([], self.gaps(model=model))

    def test_each_departure_from_the_deciding_cell_is_a_gap(self):
        cases = {'engine is infinity': {'run': own(engine='infinity')},
                 'embedder is BAAI/bge-m3': {'run': own(name='BAAI/bge-m3')},
                 'embedder revision is cccccccccccc, not the pinned 97b0c614be4d': {'run': own(revision='c' * 40)},
                 'canvas is 222222222222, not Walid\'s indexing pipeline': {'run': own_with(canvas_sha256='2' * 64)},
                 'arm is rt': {'run': own(arm_name='rt')},
                 'no query field': {'fields': ('question',)},
                 'is not the bench split': {'split': '0' * 64},
                 'rows were not read from the durable p3-evidence copy': {'against': {'sha256': s.T_B2_ROWS_SHA256,
                                                                                      'durable': False}},
                 'rows are 000000000000, not the pinned 7bccbab94956': {'against': {'sha256': '0' * 64,
                                                                                    'durable': True}},
                 'rows are missing, not the pinned': {'against': {'sha256': None, 'durable': True}}}
        for gap, change in cases.items():
            with self.subTest(gap):
                self.assertIn(gap, ' '.join(self.gaps(**change)))

    def test_the_server_s_embedding_model_must_name_the_deciding_embedder(self):
        # The manifest says Qwen3 each time; the header is what the server reported (run_w1.py embedding_model()).
        other = 'the embedding model the server reports for the dataset is not Qwen/Qwen3-Embedding-0.6B via Builtin'
        cases = {'another model': ('BAAI/bge-m3@Builtin', other),
                 'a model whose name only starts like it': ('Qwen/Qwen3-Embedding-0.6B-ft@Builtin', other),
                 'the model from another provider': ('Qwen/Qwen3-Embedding-0.6B@SILICONFLOW', other),
                 'nothing': (None, 'the server reported no embedding model')}
        for name, (model, gap) in cases.items():
            with self.subTest(name):
                self.assertIn(gap, ' '.join(self.gaps(model=model)))

    def test_an_opaque_tenant_model_id_from_the_server_is_no_gap(self):
        # A 32-hex tenant_model id names no model: the manifest's name stands, with a warning (OwnRunScoringTests).
        self.assertEqual([], self.gaps(model='a' * 32))

    def test_the_printed_reading_says_not_shown_and_what_40_items_cannot_detect(self):
        text = '\n'.join(s.decision_text(self.decide(w2_reaches=B_IDS[:3])))

        self.assertIn('Verdict: not shown. A smaller effect cannot be detected on 40 items.', text)
        self.assertIn('Scope: the held-out half B, 40 items', text)


def own_context(items: list, ranked: dict, halves: dict) -> s.Context:
    sources = {'arms': {'T-B2': {'path': 'p3/rows.jsonl', 'sha256': s.T_B2_ROWS_SHA256, 'durable': True}},
               'split': {'path': 'p3/split.json', 'sha256': s.SPLIT_SHA256, 'pinned': True},
               'strata_terms': {'path': 'p3/eval.jsonl', 'sha256': '0' * 64, 'durable': True}}
    return s.Context(DECISION_TEXTS, items, 'set', 'corpus', [arm('T-B2', 'query', ranked)],
                     {i.id: {'stratum': 'half'} for i in items}, DECISION_MAPPER, {k[0] for k in DECISION_TEXTS},
                     halves, sources, [])


class OwnRunScoringTests(OwnRunCase):
    ITEMS = B_ITEMS[:4]  # lease-law-01 to -04
    HALVES = {'lease-law-01': 'A', 'lease-law-02': 'A', 'lease-law-03': 'B', 'lease-law-04': 'B'}

    def scored(self, fallback: dict | None = None, embedding_model: str | None = None,
               manifest: dict | None = None) -> tuple:
        rows = [own_line(item.id, 'query', item.query, chunks=[own_chunk(1, content=TEXTS[LEASE])])
                for item in self.ITEMS]
        head = self.run.own_header()
        if embedding_model is not None:
            head['datasets'][0]['embedding_model'] = embedding_model
        self.run.write(head, rows, manifest=w2_manifest() if manifest is None else manifest)
        run, results = self.run.open()
        if fallback is not None:
            (self.run.folder / 'w2-fallback-v3.json').write_text(json.dumps(fallback), encoding='utf-8')
            fallback = s.load_fallback(self.run.folder / 'w2-fallback-v3.json', run, results)
        context = own_context(self.ITEMS, {i.id: (CONTRACT, SALE) for i in self.ITEMS}, self.HALVES)
        return s.score_own_run(run, results, context, fallback), context

    def test_an_own_run_holds_every_law_with_nothing_lacking_and_no_warning(self):
        report, context = self.scored()
        held, scopes = report['laws_held'], report['fields']['query']['arms']['T-B2']['scopes']

        self.assertEqual((sorted(context.slugs), 'own run (W2)', []), (held['laws'], held['source'], held['warnings']))
        self.assertEqual({'given': [], 'items_left_out': []}, report['articles_lacking'])
        self.assertEqual((4, 4, 0), (scopes['held']['items'], scopes['all']['items'], scopes['lacking']['items']))
        self.assertTrue(all('not a missing law' in note for note in held['notes']))  # notes, worded for our corpus
        self.assertEqual([], report['results']['warnings'])

    def test_a_server_embedder_other_than_the_manifest_s_is_warned_about_and_does_not_decide(self):
        report, _ = self.scored(embedding_model='BAAI/bge-m3@Builtin')

        self.assertEqual(['the header\'s embedding model does not name the manifest\'s embedder '
                          'Qwen/Qwen3-Embedding-0.6B'], report['results']['warnings'])
        self.assertFalse(report['w2_decision']['deciding_cell'])
        self.assertIn('**Warning:** the header\'s embedding model does not name', s.markdown(report))

    def test_an_opaque_tenant_model_id_is_warned_about_and_still_decides(self):
        report, _ = self.scored(embedding_model='a' * 32)

        self.assertEqual(['the header\'s embedding model is an opaque tenant-model id: only the manifest names the '
                          'embedder'], report['results']['warnings'])
        self.assertTrue(report['w2_decision']['deciding_cell'])

    def test_the_report_says_own_run_with_the_manifest_s_fields_and_no_third_party_wording(self):
        report, _ = self.scored()
        text = s.markdown(report)

        self.assertEqual(('own run (W2)', W2_DATASET), (report['results']['own_run'], report['w2_manifest']['dataset_id']))
        self.assertTrue(text.startswith('# W2 score\n'))
        self.assertIn(f'| dataset id | {W2_DATASET} |', text)
        self.assertIn('## Deciding reading (pre-registered', text)
        self.assertNotIn('scratch bench', text)  # every source in this fixture is a durable copy
        self.assertIn('## Exploratory (reported, never deciding)', text)
        self.assertIsNone(re.search(r'\b(his|he)\b', text), 'an own run is ours: no wording about Walid\'s corpus')

    def test_a_built_in_run_prints_its_revision_and_builtin_tei_and_no_hosted_banner(self):
        report, _ = self.scored()
        text = s.markdown(report)
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            s._print_own(report, False)

        self.assertIn(f'| embedder | Qwen/Qwen3-Embedding-0.6B (revision {s.DECIDING["revision"]}, via builtin-tei) |',
                      text)
        self.assertNotIn('**Hosted run: exploratory only.**', text)
        self.assertNotIn('| data policy |', text)
        self.assertTrue(out.getvalue().startswith('own run (W2): elasticsearch, Qwen/Qwen3-Embedding-0.6B (revision '
                                                  f'{s.DECIDING["revision"]}), arm v3'), out.getvalue())

    def test_the_what_was_run_header_prints_the_tei_wait_patch_and_the_concurrency(self):
        report, _ = self.scored()
        text = s.markdown(report)

        self.assertEqual((report['w2_manifest']['tei_wait_patch'], report['w2_manifest']['max_concurrent_tasks']),
                         (tei_wait_patch(), 1))
        self.assertIn('| max concurrent tasks | 1 |', text)
        self.assertIn('| TEI wait patch | `rag/llm/embedding_model.py` lines 1247, 1253: TEI wait 900 s, not 30 '
                      f'(image file {s.W2_TEI_WAIT_APPROVED["image_sha256"]}, '
                      f'patched {s.W2_TEI_WAIT_APPROVED["patched_sha256"]}) |', text)
        self.assertEqual(TEI_WAIT_DIFF, report['w2_manifest']['tei_wait_patch']['diff'])  # the JSON keeps the diff

    def test_a_tei_wait_patch_other_than_the_approved_one_is_warned_about_and_still_decides(self):
        report, _ = self.scored(manifest=w2_manifest(tei_wait_patch=tei_wait_patch(image_sha256='4' * 64)))

        self.assertEqual(1, len(report['results']['warnings']), report['results']['warnings'])
        self.assertIn('the TEI-wait patch is not the approved one (image_sha256 not as approved: image file '
                      'c2e46e1cb5d1', report['results']['warnings'][0])
        self.assertTrue(report['w2_decision']['deciding_cell'])
        self.assertIn('**Warning:** the TEI-wait patch is not the approved one', s.markdown(report))

    def test_the_outputs_are_w2_score_files_without_chunk_text(self):
        report, _ = self.scored()

        written = s.write_outputs(report, self.tmp / 'score', 'w2-score')

        self.assertEqual(['w2-score.json', 'w2-score.md'], [path.name for path in written])
        for path in written:
            self.assertNotIn(TEXTS[LEASE][:20], path.read_text(encoding='utf-8'))

    def test_the_fallback_sensitivity_empties_those_items_and_leaves_the_reading_alone(self):
        report, _ = self.scored(fallback={'query': ['lease-law-03', 'lease-law-04']})
        sensitivity = report['fallback_sensitivity']['fields']['query']
        half_b = next(r for r in sensitivity['readings'] if r['scope'] == 'half_B')

        self.assertEqual((['lease-law-03', 'lease-law-04'], 0.0), (sensitivity['items_emptied'], half_b['w2_recall']))
        self.assertEqual((1.0, 'wins'), (report['w2_decision']['w2_recall'], report['w2_decision']['verdict']))
        self.assertIn('dense-only fallback treated as empty (2 query items emptied)', s.markdown(report))

    def test_question_ids_in_the_fallback_empty_only_the_question_field_s_items(self):
        rows = [own_line(item.id, field, getattr(item, field), chunks=[own_chunk(1, content=TEXTS[LEASE])])
                for field in ('query', 'question') for item in self.ITEMS]
        self.run.write(self.run.own_header(fields=['query', 'question']), rows, manifest=w2_manifest())
        run, results = self.run.open()
        (self.run.folder / 'w2-fallback-v3.json').write_text(
            json.dumps({'query': [], 'question': ['lease-law-03', 'lease-law-04']}), encoding='utf-8')
        fallback = s.load_fallback(self.run.folder / 'w2-fallback-v3.json', run, results)
        ranked = {i.id: (CONTRACT, SALE) for i in self.ITEMS}
        context = own_context(self.ITEMS, ranked, self.HALVES)
        context = dataclasses.replace(context, arms=[*context.arms, arm('T-B2q', 'question', ranked)])

        fields = s.score_own_run(run, results, context, fallback)['fallback_sensitivity']['fields']

        half_b = {field: next(r['w2_recall'] for r in fields[field]['readings'] if r['scope'] == 'half_B')
                  for field in ('query', 'question')}
        self.assertEqual({'query': 1.0, 'question': 0.0}, half_b)


class FallbackFileTests(OwnRunCase):
    def opened(self):
        rows = [own_line('civil-code-01'), own_line('civil-code-02', chunks=[])]
        self.run.write(self.run.own_header(), rows, manifest=w2_manifest())
        return self.run.open()

    def fallback(self, value, name: str = 'w2-fallback-v3.json') -> Path:
        path = self.run.folder / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_the_ids_answered_only_by_the_fallback_are_read_per_field(self):
        run, results = self.opened()

        read = s.load_fallback(self.fallback({'query': ['civil-code-01']}), run, results)

        self.assertEqual({'query': ['civil-code-01']}, read['fields'])

    def test_a_fallback_file_that_does_not_fit_the_results_is_refused(self):
        run, results = self.opened()
        cases = {'another arm': ({'query': []}, 'w2-fallback-rt.json', 'must be the w2-fallback-v3.json'),
                 'a field the file lacks': ({'query': [], 'question': []}, None, 'one list of item ids per field'),
                 'an id with no chunks': ({'query': ['civil-code-02']}, None, 'no ok line with chunks'),
                 'an id twice': ({'query': ['civil-code-01', 'civil-code-01']}, None, 'distinct item ids')}
        for name, (value, file_name, message) in cases.items():
            with self.subTest(name):
                path = self.fallback(value, file_name or 'w2-fallback-v3.json')

                with self.assertRaisesRegex(Refused, message):
                    s.load_fallback(path, run, results)


@unittest.skipUnless(REAL_DATA, 'real data: eval-final.json, the split or a source is missing')
class RealDataW2Tests(unittest.TestCase):
    def test_the_arms_and_the_split_are_read_from_the_durable_copies(self):
        sources = real_context().sources

        self.assertTrue(sources['arms']['T-B2']['path'].endswith('p3-evidence/rag-bench-rows-round2.jsonl'))
        self.assertTrue(sources['arms']['B4q']['durable'])
        self.assertTrue(sources['arms']['A0q']['path'].endswith('p3-evidence/rag-bench-pg-rows-question.jsonl'))
        self.assertEqual((True, 'rag-bench-eval.jsonl'), (sources['strata_terms']['durable'],
                                                          sources['strata_terms']['path'].rsplit('/', 1)[-1]))
        self.assertTrue(all(arm['durable'] for arm in sources['arms'].values()))
        self.assertEqual((True, {'A': 40, 'B': 40}), (sources['split']['pinned'],
                                                      dict(Counter(real_context().halves.values()))))
        self.assertEqual([], real_context().warnings)

    def test_a_missing_durable_copy_of_the_strata_terms_is_warned_about_from_the_context_to_the_markdown(self):
        # The bench's copy is read instead, and the report says so: never a silent fallback.
        with tempfile.TemporaryDirectory() as tmp:
            durable, bench = Path(tmp) / 'evidence', Path(tmp) / 'bench'
            durable.mkdir()
            for name in set(s.DURABLE.values()) - {'rag-bench-eval.jsonl'}:
                (durable / name).write_bytes((s.EVIDENCE / name).read_bytes())
            (bench / 'data').mkdir(parents=True)
            (bench / 'data' / 'eval.jsonl').write_bytes((s.EVIDENCE / 'rag-bench-eval.jsonl').read_bytes())
            context = s.load_context(bench, durable=durable)
            run = OwnRunFolder(Path(tmp))
            run.write(run.own_header(), real_own_rows(), manifest=w2_manifest())

            report = s.score_own_run(*run.open(), context)
            text = s.markdown(report)

        self.assertEqual(1, len(context.warnings), context.warnings)
        warning = context.warnings[0]
        self.assertTrue(warning.startswith('data/eval.jsonl: the durable copy '), warning)
        self.assertIn('rag-bench-eval.jsonl is missing; read from the bench folder instead', warning)
        self.assertEqual([warning], report['source_warnings'])
        self.assertIn(f'**Warning (sources):** {warning}.', text)
        self.assertIn(', scratch bench)', text)  # the strata terms' entry in the Sources line

    def test_half_b_in_the_split_s_order_gives_back_the_bench_s_published_interval(self):
        # PROOF-rag-bench.md §1: B2 against Postgres, MRR on half B, +0.132 [+0.019, +0.248] (py/report.py
        # bootstrap()). In the eval set's order the same differences give [+0.0169, +0.2506].
        from legal_search.metrics import reciprocal_rank
        context = real_context()
        arms, by_id = {a.spec.name: a for a in context.arms}, {i.id: i for i in context.items}
        half_b = [i for i, half in context.halves.items() if half == 'B']  # the order score_field resamples in

        got = s.bootstrap([reciprocal_rank(by_id[i].expected, arms['T-B2'].ranked[i])
                           - reciprocal_rank(by_id[i].expected, arms['A0'].ranked[i]) for i in half_b])

        self.assertEqual((0.1319, 0.0187, 0.2479), (got['mean'], got['lo'], got['hi']))

    def test_a_w1_report_gives_the_held_items_of_each_half(self):
        report, _, _ = real_scored()
        scopes = report['fields']['query']['arms']['T-B2']['scopes']

        self.assertEqual((9, 7, 16), (scopes['half_A']['items'], scopes['half_B']['items'], scopes['held']['items']))

    def test_t_b2_s_own_text_as_an_own_run_ties_t_b2_on_half_b_and_is_not_shown(self):
        report, outputs = real_own_scored()
        decision = report['w2_decision']

        self.assertEqual(('not shown', 40, 0.0, 0.0), (decision['verdict'], decision['items'],
                                                       decision['interval']['lo'], decision['interval']['hi']))
        self.assertEqual((22, [], 80), (len(report['laws_held']['laws']), report['laws_held']['warnings'],
                                        report['fields']['query']['arms']['T-B2']['scopes']['held']['items']))
        for text in outputs:
            self.assertNotIn(real_context().texts[('civil-code', 107, '')][:40], text)

    def test_w2_decide_prints_the_deciding_reading_then_the_exploratory_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, rows = OwnRunFolder(Path(tmp)), real_own_rows()
            path = run.write(run.own_header(), rows, manifest=w2_manifest())
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch.object(s, 'OWN_ROOT', run.root), \
                    mock.patch.object(s, 'load_context', lambda *a, **k: real_context()):
                code = s.main(['--results', str(path), '--own-run', '--manifest', str(run.folder / s.W2_MANIFEST),
                               '--package', str(run.package), '--out-dir', str(Path(tmp) / 'score'), '--w2-decide'])
        text = out.getvalue()

        self.assertEqual(0, code)
        self.assertLess(text.index('Deciding reading (pre-registered'), text.index('Exploratory (reported, never deciding):'))
        self.assertIn('Verdict: not shown. A smaller effect cannot be detected on 40 items.', text)
        self.assertIn('laws held: all 22 (our whole corpus); articles lacking: none', text)


def real_own_rows() -> list:
    """T-B2's own top 5 served texts as the chunks of every query line: W2 then equals T-B2 through the rule."""
    context = real_context()
    t_b2 = next(a for a in context.arms if a.spec.name == 'T-B2')
    return [{'id': i.id, 'field': 'query', 'sent': i.query, 'status': 'ok', 'error': None,
             'chunks': [chunk(r, content=context.texts[k], document_name=f'{k[0]}.md')
                        for r, k in enumerate(t_b2.ranked[i.id][:s.TOP], 1)]} for i in context.items]


@functools.lru_cache(maxsize=1)
def real_own_scored():
    with tempfile.TemporaryDirectory() as tmp:
        run = OwnRunFolder(Path(tmp))
        run.write(run.own_header(), real_own_rows(), manifest=w2_manifest())
        report = s.score_own_run(*run.open(), real_context())
        written = s.write_outputs(report, Path(tmp) / 'score', 'w2-score')
        outputs = [path.read_text(encoding='utf-8') for path in written]
    return report, outputs


# The hosted run (tools/ragflow-w2/README.md, «Hosted run (owner, 2026-11-09)»): exploratory only ------------------

HOSTED_MODEL = 'qwen/qwen3-embedding-8b'
HOSTED_POLICY = 'owner set on 2026-11-09: no training, ZDR only, guardrail on Nebius only, $2 budget'


def hosted_embedder(**changes) -> dict:
    """The manifest's hosted_embedder, as rf_ingest.py writes it from register_hosted.py's record."""
    return {'model': HOSTED_MODEL, 'instance': 'w2or', 'factory': 'OpenRouter',
            'base_url': 'https://openrouter.ai/api/v1', 'provider_order': 'nebius', 'data_policy': HOSTED_POLICY,
            **changes}


def hosted_manifest(**changes) -> dict:
    """The manifest of the hosted run: the hosted embedder in place of the TEI-wait patch."""
    value = {k: v for k, v in w2_manifest().items() if k != 'tei_wait_patch'}
    value.update(embedder={'name': HOSTED_MODEL, 'revision': None, 'via': 'hosted-openrouter'},
                 embedding_batch_size=16, hosted_embedder=hosted_embedder())
    value.update(changes)
    return value


class HostedRunFolder(OwnRunFolder):
    """Under its own out/ root, as .hq/scratch/w2-hosted/out is beside .hq/scratch/w2-run/out."""

    def __init__(self, tmp: Path, engine: str = 'elasticsearch'):
        super().__init__(tmp / 'hosted', engine)

    def own_header(self, **changes) -> dict:
        value = super().own_header(**changes)
        if 'datasets' not in changes:
            value['datasets'][0]['embedding_model'] = f'{HOSTED_MODEL}@w2or@OpenRouter'
        return value


class HostedOwnRunTests(OwnRunCase):
    """A hosted manifest is read under its own root, holds the hosted embedder in place of the TEI-wait patch, is
    printed in the W2 manifest table, and never decides: --w2-decide refuses it."""

    def setUp(self):
        super().setUp()
        self.hosted = HostedRunFolder(self.tmp)

    def open(self, folder, path=None):
        return s.open_own_run(path or folder.folder / 'w2-results-v3.jsonl', folder.folder / s.W2_MANIFEST,
                              folder.package, self.run.root, hosted_root=self.hosted.root)

    def test_a_hosted_run_under_the_hosted_root_is_accepted(self):
        self.hosted.write(self.hosted.own_header(), [own_line()], manifest=hosted_manifest())

        own, results = self.open(self.hosted)

        self.assertEqual((own.arm, own.manifest['hosted_embedder']['model'], len(results.lines)),
                         ('v3', HOSTED_MODEL, 1))

    def test_a_manifest_under_the_other_kind_s_root_is_refused(self):
        self.hosted.write(self.hosted.own_header(), [own_line()], manifest=w2_manifest())
        self.run.write(self.run.own_header(), [own_line()], manifest=hosted_manifest())

        with self.assertRaisesRegex(Refused, 'a built-in W2 manifest is scored only under'):
            self.open(self.hosted)
        with self.assertRaisesRegex(Refused, 'a hosted W2 manifest is scored only under'):
            self.open(self.run)

    def test_the_local_root_alone_still_takes_only_its_own_files(self):
        self.hosted.write(self.hosted.own_header(), [own_line()], manifest=hosted_manifest())

        with self.assertRaisesRegex(Refused, 'scores only a file under'):
            s.open_own_run(self.hosted.folder / 'w2-results-v3.jsonl', self.hosted.folder / s.W2_MANIFEST,
                           self.hosted.package, self.run.root, hosted_root=None)

    def test_a_hosted_manifest_that_breaks_its_contract_is_refused(self):
        hosted = {k: v for k, v in hosted_manifest().items() if k != 'hosted_embedder'}
        broken = {'the TEI-wait patch kept': ({**hosted_manifest(), 'tei_wait_patch': tei_wait_patch()},
                                              'keys outside the contract: tei_wait_patch'),
                  'no hosted embedder': (hosted, 'missing keys: hosted_embedder'),
                  'a revision': (hosted_manifest(embedder={'name': HOSTED_MODEL, 'revision': 'a' * 40,
                                                           'via': 'hosted-openrouter'}), '"embedder" of a hosted run'),
                  'another factory': (hosted_manifest(hosted_embedder=hosted_embedder(factory='OpenAI')),
                                      '"hosted_embedder.factory"'),
                  'another base url': (hosted_manifest(hosted_embedder=hosted_embedder(base_url='http://openrouter.ai')),
                                       '"hosted_embedder.base_url"'),
                  'another model than the embedder': (
                      hosted_manifest(hosted_embedder=hosted_embedder(model='qwen/qwen3-embedding-4b')),
                      '"hosted_embedder.model"'),
                  'the instance default': (hosted_manifest(hosted_embedder=hosted_embedder(instance='default')),
                                           '"hosted_embedder.instance"'),
                  'an instance with a space': (hosted_manifest(hosted_embedder=hosted_embedder(instance='w2 or')),
                                               '"hosted_embedder.instance"'),
                  'an instance with a slash': (hosted_manifest(hosted_embedder=hosted_embedder(instance='w2/or')),
                                               '"hosted_embedder.instance"'),
                  'an empty data policy': (hosted_manifest(hosted_embedder=hosted_embedder(data_policy=' ')),
                                           '"hosted_embedder.data_policy"'),
                  'a provider order that is no text': (hosted_manifest(hosted_embedder=hosted_embedder(provider_order=5)),
                                                       '"hosted_embedder.provider_order"'),
                  'a key field': (hosted_manifest(hosted_embedder={**hosted_embedder(), 'key': {'length': 73}}),
                                  '"hosted_embedder" must hold exactly')}
        for name, (manifest, message) in broken.items():
            with self.subTest(name):
                self.hosted.write(self.hosted.own_header(), [own_line()], manifest=manifest)

                with self.assertRaisesRegex(Refused, f'^the W2 manifest: .*{re.escape(message)}'):
                    self.open(self.hosted)

    def test_w2_decide_on_a_hosted_run_is_refused_naming_the_local_deciding_cell(self):
        path = self.hosted.write(self.hosted.own_header(), [own_line()], manifest=hosted_manifest())
        out, err = io.StringIO(), io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(s, 'OWN_ROOT', self.run.root), mock.patch.object(s, 'HOSTED_ROOT', self.hosted.root):
            code = s.main(['--results', str(path), '--own-run', '--manifest', str(self.hosted.folder / s.W2_MANIFEST),
                           '--package', str(self.hosted.package), '--out-dir', str(self.tmp / 'score'), '--w2-decide'])

        self.assertEqual((2, ''), (code, out.getvalue()))
        self.assertIn('the embedder is hosted (qwen/qwen3-embedding-8b via OpenRouter): exploratory only; the '
                      'deciding cell is the local elasticsearch run with the built-in Qwen/Qwen3-Embedding-0.6B',
                      err.getvalue())

    def scored(self) -> dict:
        rows = [own_line(item.id, 'query', item.query, chunks=[own_chunk(1, content=TEXTS[LEASE])])
                for item in OwnRunScoringTests.ITEMS]
        self.hosted.write(self.hosted.own_header(), rows, manifest=hosted_manifest())
        run, results = self.open(self.hosted)
        context = own_context(OwnRunScoringTests.ITEMS, {i.id: (CONTRACT, SALE) for i in OwnRunScoringTests.ITEMS},
                              OwnRunScoringTests.HALVES)
        return s.score_own_run(run, results, context)

    def test_a_hosted_run_is_scored_and_never_decides(self):
        report = self.scored()

        self.assertFalse(report['w2_decision']['deciding_cell'])
        self.assertIn('the embedder is hosted (qwen/qwen3-embedding-8b via OpenRouter)',
                      report['w2_decision']['why_not'][0])
        self.assertEqual([], report['results']['warnings'])  # no TEI-wait warning: there is no patch
        self.assertTrue(report['w2_exploratory'])

    def test_the_w2_manifest_table_prints_the_hosted_embedder(self):
        text = s.markdown(self.scored())

        self.assertIn('| embedder | qwen/qwen3-embedding-8b (hosted: OpenRouter instance w2or, '
                      'https://openrouter.ai/api/v1, provider order nebius) |', text)
        self.assertIn(f'| data policy | {HOSTED_POLICY} |', text)
        self.assertNotIn('| TEI wait patch |', text)
        self.assertIn('**Hosted run: exploratory only.**', text)

    def test_the_terminal_line_names_the_hosted_embedder(self):
        report = self.scored()
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            s._print_own(report, False)

        self.assertTrue(out.getvalue().startswith('own run (W2): elasticsearch, qwen/qwen3-embedding-8b (hosted: '
                                                  'OpenRouter instance w2or), arm v3'), out.getvalue())


if __name__ == '__main__':
    unittest.main()
