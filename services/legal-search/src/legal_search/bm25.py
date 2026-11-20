"""The BM25 index of the keyword engine (recall plan Task 2.2): pure, in memory, no I/O.

Ported from the bench's engine (.hq/scratch/rag-bench/engine/src/engine.rs: search, field_clause, term_clause,
phrase_clause, apply_proximity) and its checked Python re-scoring (.hq/scratch/recall-gap-2026-11-09/anatomy/
tb2_bm25.py, 80/80 top-10 lists identical to the bench's T-B2), with Tantivy's BM25: k1 1.2, b 0.75,
idf ln(1 + (N − df + 0.5)/(df + 0.5)) over the whole index, field lengths quantised as Tantivy's fieldnorms are,
the average length over every document. Python 3.11 syntax only: the host tools import this module.

One search, in the bench's order:
    df-drop     a term whose body document frequency (summed over its prefix expansions) is above df_drop · N is
                dropped, except the rarest term with a frequency above zero (engine.rs:457-466);
    score       per term, per weighted field (body 1, title, heading): the term's expansions (exact or prefix)
                scored by BM25, a non-exact one boosted by prefix_weight, combined by dis-max (max) or sum, times
                the field's weight; fields and terms add. A synonym member adds as a term (one word) or as body
                phrases over its words' expansions (multi-word);
    law         the law filter keeps only that law's documents; idf stays the whole index's;
    cut         the best CANDIDATES by score (CANDIDATES_RERANK with proximity), ties by document order;
    proximity   per pair of query terms within proximity_window body positions, min(idf)/distance × weight;
    order       score, then article number, then law slug and suffix in code-point order (Postgres's tie order).
"""

import bisect
import math
from collections import Counter
from dataclasses import dataclass

K1, B = 1.2, 0.75
CANDIDATES = 50
CANDIDATES_RERANK = 200
MAX_PHRASE_COMBINATIONS = 64


def fieldnorm_table() -> list[int]:
    """Tantivy's 256 fieldnorm values: 0-40 exact, then steps doubling every eight values."""
    table = list(range(41))
    step, value = 2, 40
    while len(table) < 256:
        for _ in range(8):
            value += step
            table.append(value)
            if len(table) == 256:
                break
        step *= 2
    return table


_TABLE = fieldnorm_table()


def quantise(length: int) -> int:
    """The fieldnorm Tantivy stores for a field of `length` tokens: the largest table value not above it."""
    return _TABLE[bisect.bisect_right(_TABLE, length) - 1]


def idf(df: int, n: int) -> float:
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


@dataclass(frozen=True)
class Doc:
    id: int
    law_slug: str
    number: int
    suffix: str
    body: tuple[str, ...]
    heading: tuple[str, ...]
    title: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    """The ranker's levers (built from SearchConfig by keyword_engine.settings_of)."""

    prefix_mode: str          # 'exact', 'sum' or 'dismax'
    prefix_weight: float      # a non-exact expansion's boost
    title_weight: float
    heading_weight: float
    proximity_weight: float
    proximity_window: int
    df_drop: float
    stoplist: bool            # read when the query terms are built, before search
    synonyms: bool


class _Field:
    """One indexed field: term frequencies, quantised lengths, document frequencies and a sorted vocabulary, and a
    memo of each term's BM25 score per document, filled on a term's first use (review 2026-11-11 (b)1)."""

    def __init__(self, token_lists: list[tuple[str, ...]]) -> None:
        self.tf = [Counter(tokens) for tokens in token_lists]
        self.norm = [quantise(len(tokens)) for tokens in token_lists]
        self.avg = sum(len(tokens) for tokens in token_lists) / len(token_lists) if token_lists else 0.0
        self.df: Counter[str] = Counter()
        self.postings: dict[str, list[int]] = {}
        for doc, counts in enumerate(self.tf):
            self.df.update(counts.keys())
            for term in counts:
                self.postings.setdefault(term, []).append(doc)
        self.vocab = sorted(self.df)
        self.memo: dict[str, list[float]] = {}

    def expansions(self, term: str, mode: str) -> list[str]:
        """The field's terms a query term reaches: itself only ('exact'), or every term it prefixes, in order."""
        if mode == 'exact':
            return [term] if term in self.df else []
        found = []
        at = bisect.bisect_left(self.vocab, term)
        while at < len(self.vocab) and self.vocab[at].startswith(term):
            found.append(self.vocab[at])
            at += 1
        return found

    def bm25(self, term: str, doc: int, n: int) -> float:
        tf = self.tf[doc].get(term, 0)
        if not tf:
            return 0.0
        return idf(self.df[term], n) * (1 + K1) * tf / (tf + K1 * (1 - B + B * self.norm[doc] / self.avg))

    def scores(self, term: str, n: int) -> list[float]:
        """bm25(term, doc, n) for each doc of postings[term], in that order: computed once, then read from the memo.
        The scores carry no boost or weight, and n is the index's document count, the same on every call. A whole
        list is stored at once, so concurrent searches fill it idempotently: a reader meets the list or nothing."""
        found = self.memo.get(term)
        if found is None:
            found = [self.bm25(term, doc, n) for doc in self.postings[term]]
            self.memo[term] = found
        return found


class Index:
    def __init__(self, docs: list[Doc]) -> None:
        self.docs = docs
        self.n = len(docs)
        self.fields = {
            'body': _Field([d.body for d in docs]),
            'title': _Field([d.title for d in docs]),
            'heading': _Field([d.heading for d in docs]),
        }
        laws = sorted({d.law_slug for d in docs})
        suffixes = sorted({d.suffix for d in docs})
        self._law_ord = {slug: i for i, slug in enumerate(laws)}
        self._suf_ord = {suffix: i for i, suffix in enumerate(suffixes)}

    @classmethod
    def build(cls, docs: list[Doc]) -> 'Index':
        return cls(list(docs))

    def _weighted_fields(self, settings: Settings) -> list[tuple[_Field, float]]:
        weights = (('body', 1.0), ('title', settings.title_weight), ('heading', settings.heading_weight))
        return [(self.fields[name], weight) for name, weight in weights if weight > 0.0]

    def _field_clause(self, field: _Field, term: str, weight: float, settings: Settings) -> dict[int, float] | None:
        """engine.rs field_clause: the expansions, a non-exact one boosted, combined by dis-max or sum, times `weight`."""
        expansions = field.expansions(term, settings.prefix_mode)
        if not expansions:
            return None
        scores: dict[int, float] = {}
        for expansion in expansions:
            boost = 1.0 if expansion == term else settings.prefix_weight
            for doc, plain in zip(field.postings[expansion], field.scores(expansion, self.n)):
                score = boost * plain
                if settings.prefix_mode == 'dismax':
                    scores[doc] = max(scores.get(doc, 0.0), score)
                else:
                    scores[doc] = scores.get(doc, 0.0) + score
        return {doc: weight * score for doc, score in scores.items()}

    def _term_clause(self, term: str, settings: Settings) -> dict[int, float] | None:
        """engine.rs term_clause: the term's field clauses, added."""
        total: dict[int, float] | None = None
        for field, weight in self._weighted_fields(settings):
            clause = self._field_clause(field, term, weight, settings)
            if clause is None:
                continue
            total = {} if total is None else total
            for doc, score in clause.items():
                total[doc] = total.get(doc, 0.0) + score
        return total

    def _phrase_clause(self, member: list[str], settings: Settings) -> dict[int, float] | None:
        """engine.rs phrase_clause: body phrases over the words' expansions, at most MAX_PHRASE_COMBINATIONS of them,
        the most frequent first; each scored by BM25 with the phrase count as tf and the summed idf."""
        body = self.fields['body']
        combinations: list[tuple[list[str], float]] = [([], math.inf)]
        for word in member:
            expanded = sorted(((e, body.df[e]) for e in body.expansions(word, settings.prefix_mode)), key=lambda x: -x[1])
            following = [(terms + [e], min(df, edf)) for terms, df in combinations for e, edf in expanded]
            following.sort(key=lambda x: -x[1])
            combinations = following[:MAX_PHRASE_COMBINATIONS]
        phrases = [terms for terms, _ in combinations if len(terms) > 1]
        if not phrases:
            return None
        scores: dict[int, float] = {}
        for terms in phrases:
            weight = sum(idf(body.df[t], self.n) for t in terms) * (1 + K1)
            candidates = set(body.postings[terms[0]])
            for t in terms[1:]:
                candidates &= set(body.postings[t])
            size = len(terms)
            for doc in candidates:
                tokens = self.docs[doc].body
                count = sum(1 for i in range(len(tokens) - size + 1) if list(tokens[i:i + size]) == terms)
                if count:
                    norm = K1 * (1 - B + B * body.norm[doc] / body.avg)
                    scores[doc] = scores.get(doc, 0.0) + weight * count / (count + norm)
        return scores

    def _body_df(self, term: str, settings: Settings) -> int:
        body = self.fields['body']
        return min(sum(body.df[e] for e in body.expansions(term, settings.prefix_mode)), self.n)

    def search(self, terms: list[str], synonym_members: list[list[str]], settings: Settings, law: str | None,
               depth: int) -> list[tuple[int, float]]:
        """(doc id, score), best first, at most `depth`. `terms` are the analysed query terms; `synonym_members`
        the analysed members a synonym group adds (empty when synonyms are off)."""
        terms = list(terms)
        rarity: dict[str, float] = {}
        if settings.df_drop > 0.0 or settings.proximity_weight > 0.0:
            shares = [(term, self._body_df(term, settings)) for term in terms]
            rarity = {term: idf(df, self.n) for term, df in shares}
            if settings.df_drop > 0.0 and terms:
                limit = int(settings.df_drop * self.n)
                attested = [(term, df) for term, df in shares if df > 0]
                rarest = min(attested, key=lambda x: x[1])[0] if attested else None   # the first minimum, as Rust's
                terms = [term for term, df in shares if df <= limit or term == rarest]

        clauses = [self._term_clause(term, settings) for term in terms]
        if settings.synonyms:
            for member in synonym_members:
                clauses.append(self._term_clause(member[0], settings) if len(member) == 1
                               else self._phrase_clause(member, settings))
        total: dict[int, float] = {}
        for clause in clauses:
            for doc, score in (clause or {}).items():
                total[doc] = total.get(doc, 0.0) + score
        candidates = [doc for doc in total if law is None or self.docs[doc].law_slug == law]
        limit = CANDIDATES_RERANK if settings.proximity_weight > 0.0 else CANDIDATES
        pool = sorted(candidates, key=lambda doc: (-total[doc], doc))[:limit]
        scores = {doc: total[doc] for doc in pool}

        if settings.proximity_weight > 0.0 and len(terms) > 1:
            self._apply_proximity(scores, terms, rarity, settings)

        def order(doc: int) -> tuple:
            d = self.docs[doc]
            return (-scores[doc], d.number, self._law_ord[d.law_slug], self._suf_ord[d.suffix])

        return [(self.docs[doc].id, scores[doc]) for doc in sorted(scores, key=order)[:depth]]

    def _apply_proximity(self, scores: dict[int, float], terms: list[str], rarity: dict[str, float],
                         settings: Settings) -> None:
        """engine.rs apply_proximity: for every pair of query terms, the closest distance between their body
        positions; a pair within the window adds min(idf)/distance, and the sum is weighted."""
        body = self.fields['body']
        expansions = [set(body.expansions(term, settings.prefix_mode)) for term in terms]
        weights = [rarity[term] for term in terms]
        m = len(terms)
        for doc in scores:
            occurrences = sorted(
                (position, j)
                for j, reached in enumerate(expansions)
                for position, token in enumerate(self.docs[doc].body)
                if token in reached
            )
            if len(occurrences) < 2:
                continue
            closest: dict[tuple[int, int], int] = {}
            last: list[int | None] = [None] * m
            for position, j in occurrences:
                for i in range(m):
                    if i != j and last[i] is not None:
                        pair = (min(i, j), max(i, j))
                        distance = position - last[i]
                        if distance < closest.get(pair, math.inf):
                            closest[pair] = distance
                last[j] = position
            bonus = 0.0
            for a in range(m):
                for b in range(a + 1, m):
                    distance = closest.get((a, b))
                    if distance is not None and 0 < distance <= settings.proximity_window:
                        bonus += min(weights[a], weights[b]) / distance
            scores[doc] += settings.proximity_weight * bonus
