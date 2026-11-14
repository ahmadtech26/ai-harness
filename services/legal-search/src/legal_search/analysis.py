"""Analysers of the BM25 keyword engine (recall plan Task 2.1), ported from the bench's engine
(.hq/scratch/rag-bench/engine/src/analyser.rs). Each is applied identically at index and query time.

    Today       normalize.tokens: a clitic or article goes whenever 3 letters remain (the live search's analyser).
    GuardLight  the O-111 fix (a one-letter clitic goes only when the corpus attests the remainder at least as
                often as the word), then at most one light10 suffix if 3 letters remain.

Stopwords and synonym groups are analysed with the same analyser as the text (analyser.rs:184-185), so a GuardLight
query never compares a GuardLight token with a Today-tokenised stopword or synonym member.
Python 3.11 syntax only: the host tools import this module (recall plan, Chunk 2).
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from legal_search import synonyms
from legal_search.normalize import folded_words
from legal_search.normalize import stem as stem_today
from legal_search.synonyms import RAW_GROUPS

# Copied from analyser.rs:34-42.
ARTICLES = ('وال', 'بال', 'كال', 'فال', 'لل', 'ال')
ONE_LETTER = ('و', 'ف', 'ب', 'ك', 'ل')
# Folded forms of light10's suffixes (ة→ه, so «ية» is «يه» and «ة» is «ه»), in Larkey's order.
SUFFIXES = ('ها', 'ان', 'ات', 'ون', 'ين', 'يه', 'ه', 'ي')
# O-111 names «بدون»: its remainder «دون» is a common word, so the corpus test alone would still strip it.
PROTECTED = frozenset({'بدون'})
MIN_STEM = 3
RAW_STOPWORDS = 'في من على الى إلى عن ان أن إن ما هل او أو ثم قد لا لم لن هو هي هذا هذه ذلك التي الذي كان مع اذا إذا عند'


@dataclass(frozen=True)
class Lexicon:
    """Document frequency of each folded, unstemmed word over the served texts: GuardLight's evidence (analyser.rs:166-175)."""

    df: Mapping[str, int]

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> 'Lexicon':
        counts: Counter[str] = Counter()
        for text in texts:
            counts.update(set(folded_words(text)))
        return cls(dict(counts))

    def __call__(self, word: str) -> int:
        return self.df.get(word, 0)


def strip_one_suffix(word: str) -> str:
    """The first light10 suffix whose removal leaves 3 letters, removed; at most one (analyser.rs:142-151)."""
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            return word[: -len(suffix)]
    return word


class Analyser:
    """Tokens, query terms, stopwords and synonym members, all under one stemming rule (`stem`)."""

    name = ''

    def __init__(self) -> None:
        self.stopwords = frozenset(self.join(word) for word in RAW_STOPWORDS.split())
        self._synonyms = [[self.tokens(member) for member in group] for group in RAW_GROUPS]
        # The installed vocabulary's directed pairs (synonyms.use_vocabulary), read when the analyser is built.
        self._directed = [(self.tokens(everyday), self.tokens(statutory)) for everyday, statutory in synonyms.RAW_DIRECTED]

    def stem(self, word: str) -> str:
        raise NotImplementedError

    def tokens(self, text: str) -> list[str]:
        return [self.stem(word) for word in folded_words(text)]

    def join(self, text: str) -> str:
        return ' '.join(self.tokens(text))

    def query_terms(self, tokens: list[str], stoplist: bool = True) -> list[str]:
        """In order, de-duplicated, without one-letter tokens or (with `stoplist`) stopwords (analyser.rs:237-246)."""
        seen: set[str] = set()
        terms = []
        for token in tokens:
            if len(token) >= 2 and not (stoplist and token in self.stopwords) and token not in seen:
                seen.add(token)
                terms.append(token)
        return terms

    def synonym_groups(self) -> list[list[list[str]]]:
        return [list(group) for group in self._synonyms]

    def synonym_members(self, tokens: list[str]) -> list[list[str]]:
        """The absent members of every group with a member present, each as prefix-matched words (analyser.rs:249-266),
        then the statutory phrase of every installed everyday wording present, unless the query already searches it
        (synonyms.synonym_terms)."""

        def contains(member: list[str]) -> bool:
            size = len(member)
            return size > 0 and len(tokens) >= size and any(
                all(tokens[i + j].startswith(member[j]) for j in range(size)) for i in range(len(tokens) - size + 1)
            )

        def covers(member: list[str]) -> bool:
            size = len(member)
            return size > 0 and len(tokens) >= size and any(
                all(member[j].startswith(tokens[i + j]) for j in range(size)) for i in range(len(tokens) - size + 1)
            )

        added: list[list[str]] = []
        for group in self._synonyms:
            if any(contains(member) for member in group):
                for member in group:
                    if not contains(member) and member not in added:
                        added.append(member)
        for everyday, statutory in self._directed:
            if contains(everyday) and not covers(statutory) and statutory not in added:
                added.append(statutory)
        return added


class Today(Analyser):
    """normalize.py's stemming, the live search's analyser."""

    name = 'today'

    def stem(self, word: str) -> str:
        return stem_today(word)


class GuardLight(Analyser):
    """`stem_fixed`, then one suffix (analyser.rs:193-216, :223)."""

    name = 'guardlight'

    def __init__(self, lexicon: Lexicon) -> None:
        self.lexicon = lexicon
        super().__init__()

    def stem_fixed(self, word: str) -> str:
        for article in ARTICLES:
            if word.startswith(article) and len(word) - len(article) >= MIN_STEM:
                return word[len(article):]
        if word in PROTECTED:
            return word
        for clitic in ONE_LETTER:
            if word.startswith(clitic):
                rest = word[len(clitic):]
                if len(rest) >= MIN_STEM and self.lexicon(rest) + self.lexicon('ال' + rest) >= max(self.lexicon(word), 1):
                    return rest
                return word
        return word

    def stem(self, word: str) -> str:
        return strip_one_suffix(self.stem_fixed(word))


def analyser_of(name: str, lexicon: Lexicon) -> Analyser:
    """The analyser a SearchConfig names (search_config.ANALYSERS)."""
    if name == 'today':
        return Today()
    if name == 'guardlight':
        return GuardLight(lexicon)
    raise ValueError(f'unknown analyser {name!r}')
