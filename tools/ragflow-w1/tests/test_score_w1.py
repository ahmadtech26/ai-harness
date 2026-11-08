"""score_w1.py: the mapping rule, the candidate restriction, the budget, the scopes, the bootstrap, the self-check.

Most tests use small invented Arabic fixtures. The tests marked «real data» load our library and the recorded
arms; they need the bench folder (.hq/scratch/rag-bench) and p3-evidence/eval-final.json."""

import dataclasses
import functools
import json
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import intake_w1
import score_w1 as s
from intake_w1 import Refused
from tests.test_intake_w1 import chunk, header, make_results

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
REAL_DATA = s.BENCH.is_dir() and s.BASELINE.is_file()


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

    @unittest.skipUnless(REAL_DATA, 'real data: the bench folder or eval-final.json is missing')
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
        diffs = [1.0, 0.0, -0.5, 0.5, 0.0, 1.0, 0.0, 0.0, -1.0, 0.5] * 4
        rng = random.Random(20261106)  # rag-bench py/report.py:21-26, copied as the oracle
        means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(10000))

        got = s.bootstrap(diffs)

        self.assertEqual((round(means[250], 4), round(means[9749], 4)), (got['lo'], got['hi']))
        self.assertEqual(got, s.bootstrap(diffs))  # seeded: the same every run

    def test_the_interval_excludes_zero_only_when_it_lies_wholly_on_one_side(self):
        self.assertTrue(s.bootstrap([1.0, 0.5, 1.0])['excludes_zero_above'])
        self.assertFalse(s.bootstrap([0.0, 0.0, 0.0])['excludes_zero_above'])
        self.assertTrue(s.bootstrap([-1.0, -0.5])['excludes_zero_below'])
        self.assertIsNone(s.bootstrap([]))


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


@unittest.skipUnless(REAL_DATA, 'real data: the bench folder or eval-final.json is missing')
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


if __name__ == '__main__':
    unittest.main()
