"""Legal synonym groups folded at query time (candidate C4). Each group pairs a term a practitioner may type with
the corpus's own wording for the same concept: Civil Code and Majalla «مرور الزمان», Maritime Commerce and Civil
Procedure «مرور الزمن», Majalla «الإجارة», Criminal Procedure «التوقيف». A query word that starts with a group
member adds the other members.

Checked against the corpus: «المشتكى عليه»، «المتهم»، «الظنين» are distinct procedural statuses, and hamza folding
makes «الإخطار» (notice) one token with «الأخطار» (perils), so neither is a group; «الضمان» enters only as
«ضمان الضرر», because bare «ضمان» also means warranty or guarantee. «العامل»/«الأجير» is not a group: the Labour
Law never writes «الأجير»; the word is the Majalla's (35 articles, e.g. «الأجير المشترك», a distinct concept)."""

from legal_search.normalize import tokens

RAW_GROUPS = (
    ('التقادم', 'مرور الزمان', 'مرور الزمن'),
    ('الإيجار', 'الإجارة'),
    ('التعويض', 'ضمان الضرر'),
    ('التوقيف', 'الحبس الاحتياطي'),
)
GROUPS: tuple[tuple[tuple[str, ...], ...], ...] = tuple(tuple(tuple(tokens(member)) for member in group) for group in RAW_GROUPS)


def _contains(sequence: list[str], member: tuple[str, ...]) -> bool:
    size = len(member)
    return any(all(sequence[i + j].startswith(member[j]) for j in range(size)) for i in range(len(sequence) - size + 1))


def _term(member: tuple[str, ...]) -> str:
    return f'{member[0]}:*' if len(member) == 1 else '(' + ' <-> '.join(f'{word}:*' for word in member) + ')'


def synonym_terms(sequence: list[str]) -> list[str]:
    """tsquery terms for the members absent from `sequence` of every group with a member present in it."""
    added: list[str] = []
    for group in GROUPS:
        if any(_contains(sequence, member) for member in group):
            added += [_term(member) for member in group if not _contains(sequence, member)]
    return list(dict.fromkeys(added))
