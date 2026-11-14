"""Legal synonym groups folded at query time (candidate C4). Each group pairs a term a practitioner may type with
the corpus's own wording for the same concept: Civil Code and Majalla «مرور الزمان», Maritime Commerce and Civil
Procedure «مرور الزمن», Majalla «الإجارة», Criminal Procedure «التوقيف». A query word that starts with a group
member adds the other members.

Checked against the corpus: «المشتكى عليه»، «المتهم»، «الظنين» are distinct procedural statuses, and hamza folding
makes «الإخطار» (notice) one token with «الأخطار» (perils), so neither is a group; «الضمان» enters only as
«ضمان الضرر», because bare «ضمان» also means warranty or guarantee. «العامل»/«الأجير» is not a group: the Labour
Law never writes «الأجير»; the word is the Majalla's (35 articles, e.g. «الأجير المشترك», a distinct concept).

An installed everyday vocabulary (vocabulary.py, off unless LEGAL_SEARCH_VOCABULARY names a file) adds directed pairs:
a query word sequence matching an everyday wording adds the statutory phrase, never the reverse."""

from legal_search.normalize import tokens

RAW_GROUPS = (
    ('التقادم', 'مرور الزمان', 'مرور الزمن'),
    ('الإيجار', 'الإجارة'),
    ('التعويض', 'ضمان الضرر'),
    ('التوقيف', 'الحبس الاحتياطي'),
)
GROUPS: tuple[tuple[tuple[str, ...], ...], ...] = tuple(tuple(tuple(tokens(member)) for member in group) for group in RAW_GROUPS)

# The installed vocabulary's (everyday wording, statutory phrase) pairs, as written and tokenised, and its file's sha256;
# empty and None until use_vocabulary installs one (server and evaluation startup).
RAW_DIRECTED: tuple[tuple[str, str], ...] = ()
DIRECTED: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = ()
VOCABULARY_SHA256: str | None = None


def use_vocabulary(vocabulary) -> None:
    """Install a vocabulary.Vocabulary for every later search in this process, or none (None). The keyword engine's
    analysers read the pairs when they are built, so install before the first index build (keyword_engine.CACHE)."""
    global RAW_DIRECTED, DIRECTED, VOCABULARY_SHA256
    RAW_DIRECTED = vocabulary.pairs() if vocabulary is not None else ()
    DIRECTED = tuple((tuple(tokens(everyday)), tuple(tokens(statutory))) for everyday, statutory in RAW_DIRECTED)
    VOCABULARY_SHA256 = vocabulary.sha256 if vocabulary is not None else None


def _contains(sequence: list[str], member: tuple[str, ...]) -> bool:
    size = len(member)
    return any(all(sequence[i + j].startswith(member[j]) for j in range(size)) for i in range(len(sequence) - size + 1))


def _covers(sequence: list[str], member: tuple[str, ...]) -> bool:
    """Whether the query already searches `member`: its words in order, each starting with the query word (a query
    word is searched as a prefix, so «فصل» covers «فصل» and «فصله», while «سماعيه» does not cover «سماع»)."""
    size = len(member)
    return any(all(member[j].startswith(sequence[i + j]) for j in range(size)) for i in range(len(sequence) - size + 1))


def _term(member: tuple[str, ...]) -> str:
    return f'{member[0]}:*' if len(member) == 1 else '(' + ' <-> '.join(f'{word}:*' for word in member) + ')'


def synonym_terms(sequence: list[str]) -> list[str]:
    """tsquery terms for the members absent from `sequence` of every group with a member present in it, then the
    statutory phrase of every installed everyday wording present in it, unless the query already searches it."""
    added: list[str] = []
    for group in GROUPS:
        if any(_contains(sequence, member) for member in group):
            added += [_term(member) for member in group if not _contains(sequence, member)]
    for everyday, statutory in DIRECTED:
        if _contains(sequence, everyday) and not _covers(sequence, statutory):
            added.append(_term(statutory))
    return list(dict.fromkeys(added))
