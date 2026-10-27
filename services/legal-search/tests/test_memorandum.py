import json
import os
from pathlib import Path

import pytest
from psycopg import AsyncConnection

from legal_search import db
from legal_search.memorandum import (
    MemorandumCorrection,
    MemorandumError,
    load_memorandum,
    load_memorandum_corrections,
    parse_heading,
)
from tests.pg import fresh

needs_postgres = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs Postgres')

# Text before a heading, as in the real notes: it holds article numbers that are not a heading.
LEAD = 'وهي تطابق المادة 102 مصري و103 سوري ومشروع اردني. '

# (the heading at the end of a note, the article numbers it names). One case per form in the real memorandum;
# the note that ends with the form is in the comment.
HEADINGS = [
    ('المذكرة الايضاحية للمادة (107)', [107]),
    ('المذكرة الايضاحية للمادة ( 716)', [716]),
    ('المذكرة الايضاحية للمادتين (7) و (8)', [7, 8]),
    ('المذكرة الايضاحية للمادتين (353) و(354)', [353, 354]),
    ('المذكرة الايضاحية للمواد (13) و ( 14) و (15)', [13, 14, 15]),               # 10
    ('المذكرة الايضاحية للمادتين (858 و 859 )', [858, 859]),                       # 525: both numbers in one bracket
    ('المذكرة الايضاحية للمواد (108 - 110)', [108, 109, 110]),
    ('المذكرة الايضاحية للمواد (67 -71 )', [67, 68, 69, 70, 71]),
    ('المذكرة الايضاحية للمواد ( 441 ) - ( 443 )', [441, 442, 443]),
    ('المذكرة الايضاحية للمواد من ( 214 - 238)', list(range(214, 239))),          # 165
    ('المذكرة الايضاحية للمواد 862 - 867 )', list(range(862, 868))),              # 528: no opening bracket
    ('المذكرة الايضاحية للمادة 898', [898]),                                      # 543: no brackets
    ('المذكرة الايضاحية للمادة ( 1220 - 1224)', list(range(1220, 1225))),         # 698: singular word, range
    ('المادة الايضاحية للمادة (204)', [204]),                                     # 157: typo
    ('المذكرة الايضايحة للمادة (205)', [205]),                                    # 158: typo
    ('المذكرة الايضاحية للمدة (263)', [263]),                                     # 188: typo
    ('المكرة الايضاحية للمادة (517)', [517]),                                     # 353: typo
]


def test_parse_heading_reads_every_heading_variant():
    assert {heading: parse_heading(LEAD + heading) for heading, _ in HEADINGS} == dict(HEADINGS)


def test_parse_heading_ignores_a_reference_before_the_end():
    assert parse_heading('شرح. وتراجع المذكرة الايضاحية للمواد (53 و54 و 55 ) من هذا القانون.') is None
    assert parse_heading('شرح. ( وتراجع المذكرة الايضاحية للمادة التالية ). المذكرة الايضاحية للمادة (99)') == [99]
    assert parse_heading(LEAD) is None
    # A descending range is unreadable (None), so the load fails naming the note instead of guessing.
    assert parse_heading('شرح. المذكرة الايضاحية للمواد (3) و (7 - 5)') is None


MEMORANDUM_CORRECTION = {'note': 458, 'articles': [716, 717], 'reason': 'the heading names 716 only',
                         'evidence': 'the note opens «مصدر حكم هاتين المادتين»'}


def _corrections_file(directory: Path, document: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'corrections.json'
    path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return path


def test_reads_the_memorandum_corrections(tmp_path: Path):
    with_key = _corrections_file(tmp_path / 'with', {'corrections': [], 'memorandum': [MEMORANDUM_CORRECTION]})
    without_key = _corrections_file(tmp_path / 'without', {'corrections': []})

    assert load_memorandum_corrections(with_key) == [
        MemorandumCorrection(458, (716, 717), 'the heading names 716 only', 'the note opens «مصدر حكم هاتين المادتين»')
    ]
    assert load_memorandum_corrections(without_key) == []


# (the memorandum list, the error it must raise). One case per rule.
INVALID_CORRECTIONS = [
    ({}, 'corrections file: memorandum must be a list'),
    (['x'], 'memorandum[0]: each memorandum correction must be an object'),
    ([{**MEMORANDUM_CORRECTION, 'note': 0}], 'memorandum[0]: note must be an int >= 1'),
    ([{**MEMORANDUM_CORRECTION, 'articles': []}],
     'memorandum[0]: articles must be a non-empty list of ints in strictly ascending order'),
    ([{**MEMORANDUM_CORRECTION, 'articles': [717, 716]}],
     'memorandum[0]: articles must be a non-empty list of ints in strictly ascending order'),
    ([{**MEMORANDUM_CORRECTION, 'reason': ' '}], 'memorandum[0]: reason must not be empty'),
    ([{key: value for key, value in MEMORANDUM_CORRECTION.items() if key != 'evidence'}],
     'memorandum[0]: evidence must not be empty'),
    ([MEMORANDUM_CORRECTION, MEMORANDUM_CORRECTION], 'memorandum[1]: note 458 is corrected more than once'),
]


def test_rejects_an_invalid_memorandum_correction_naming_it(tmp_path: Path):
    raised = []
    for index, (entries, _) in enumerate(INVALID_CORRECTIONS):
        path = _corrections_file(tmp_path / str(index), {'corrections': [], 'memorandum': entries})
        try:
            load_memorandum_corrections(path)
            raised.append(None)
        except MemorandumError as error:
            raised.append(str(error))

    assert raised == [expected for _, expected in INVALID_CORRECTIONS]


def _notes(directory: Path, notes: dict[int, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    document = {'source': 'example.test/memo', 'articles': {str(number): text for number, text in notes.items()}}
    (directory / 'memorandum_civil_law.json').write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return directory


def _correction(note: int, *articles: int) -> MemorandumCorrection:
    return MemorandumCorrection(note, articles, 'test', 'test')


# A six-article code. Each note ends with the heading of the next; no heading precedes note 1, so a
# correction says it explains article 2.
NOTES = {
    1: 'شرح المادة الثانية. المذكرة الايضاحية للمادة (3)',
    2: 'شرح المادة الثالثة. المذكرة الايضاحية للمادتين (4) و (5)',
    3: 'شرح المادتين الرابعة والخامسة.',
}
FIRST = _correction(1, 2)


def test_each_heading_links_its_articles_to_the_next_note(tmp_path: Path):
    memorandum = load_memorandum(_notes(tmp_path, NOTES), [FIRST], civil_articles=6)

    assert memorandum.links == [(2, 1), (3, 2), (4, 3), (5, 3)]
    assert memorandum.uncovered == [1, 6]
    assert memorandum.source == 'example.test/memo'


def test_the_trailing_heading_is_not_part_of_the_stored_text(tmp_path: Path):
    memorandum = load_memorandum(_notes(tmp_path, NOTES), [FIRST], civil_articles=6)

    assert memorandum.notes == {1: 'شرح المادة الثانية.', 2: 'شرح المادة الثالثة.', 3: 'شرح المادتين الرابعة والخامسة.'}


def test_the_first_note_needs_a_correction_naming_its_articles(tmp_path: Path):
    with pytest.raises(MemorandumError, match='memorandum note 1 has no readable heading'):
        load_memorandum(_notes(tmp_path, NOTES), [], civil_articles=6)


def test_a_correction_replaces_the_parsed_set_of_its_note(tmp_path: Path):
    # Not a superset of the parsed [4, 5]: a loader that merged the correction in would keep article 4.
    memorandum = load_memorandum(_notes(tmp_path, NOTES), [FIRST, _correction(3, 5, 6)], civil_articles=6)

    assert [link for link in memorandum.links if link[1] == 3] == [(5, 3), (6, 3)]
    assert memorandum.uncovered == [1, 4]


def test_a_correction_for_a_missing_note_fails_naming_it(tmp_path: Path):
    with pytest.raises(MemorandumError, match='memorandum correction for note 9'):
        load_memorandum(_notes(tmp_path, NOTES), [FIRST, _correction(9, 6)], civil_articles=6)


# (the notes, the error they must raise). One case per rule: order inside a heading, order across notes, range.
VIOLATIONS = [
    ({**NOTES, 2: 'شرح. المذكرة الايضاحية للمادتين (5) و (4)'},
     'memorandum note 3: articles [5, 4] are not in strictly ascending order'),
    # The previous note spans two articles, so "after its last" and "after its first" differ.
    ({**NOTES, 1: 'شرح. المذكرة الايضاحية للمادتين (3) و (4)', 2: 'شرح. المذكرة الايضاحية للمادة (4)'},
     'memorandum note 3: article 4 is not after the last article of note 2 (4)'),
    ({**NOTES, 2: 'شرح. المذكرة الايضاحية للمادة (7)'},
     'memorandum note 3: article 7 is outside 1..6'),
]


def test_each_order_or_range_violation_fails_naming_the_note(tmp_path: Path):
    raised = []
    for index, (notes, _) in enumerate(VIOLATIONS):
        try:
            load_memorandum(_notes(tmp_path / str(index), notes), [FIRST], civil_articles=6)
            raised.append(None)
        except MemorandumError as error:
            raised.append(str(error))

    assert raised == [expected for _, expected in VIOLATIONS]


@pytest.mark.skipif(not (os.environ.get('CORPUS_DIR') and os.environ.get('CONTENT_DIR')), reason='real corpus not mounted')
def test_the_real_memorandum_links_each_article_to_its_own_note():
    corrections = load_memorandum_corrections(Path(os.environ['CONTENT_DIR']) / 'corpus' / 'corrections.json')

    memorandum = load_memorandum(Path(os.environ['CORPUS_DIR']), corrections)

    note_of = dict(memorandum.links)  # article -> note; as many keys as links means one note per article
    assert (len(memorandum.notes), len(memorandum.links), len(note_of), memorandum.uncovered) == (766, 1447, 1447, [1, 1449])
    assert [note_of[article] for article in (2, 107, 716, 717, 1448)] == [1, 74, 458, 458, 766]
    assert {note_of[a] for a in range(1292, 1298)} == {733} and {note_of[a] for a in range(214, 239)} == {166}
    assert {note_of[a] for a in range(1315, 1322)} == {740}
    assert 'العربون' in memorandum.notes[74] and 'المذكرة الايضاحية للمادة (107)' not in memorandum.notes[73]


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
        await fresh(connection)
        notes = {n: f'شرح رقم {n}.' for n in range(1, 8)}
        # Article 1 links all seven notes (for paging); note 3 also explains articles 2 and 4.
        links = [(1, n) for n in (7, 3, 5, 1, 2, 6, 4)] + [(2, 3), (4, 3)]
        await db.replace_memorandum(connection, notes, links, 'example.test/memo')
        yield connection


@needs_postgres
async def test_memorandum_page_returns_notes_in_note_order_with_the_articles_each_explains(conn):
    page = await db.memorandum_page(conn, 1, 2, 3)

    assert [(note.note_no, note.first_article, note.last_article) for note in page] == [(3, 1, 4), (4, 1, 1), (5, 1, 1)]
    assert page[0].source == 'example.test/memo'
    assert await db.memorandum_count(conn, 1) == 7


@needs_postgres
async def test_replacing_the_memorandum_drops_links_and_notes_no_longer_in_the_source(conn):
    await db.replace_memorandum(conn, {1: 'شرح.', 2: 'شرح.'}, [(1, 1)], 'example.test/memo')

    cur = await conn.execute('SELECT count(*) FROM memorandum_notes')
    assert (await cur.fetchone())[0] == 2
    assert await db.memorandum_count(conn, 1) == 1
    # A re-ingest replaces note text too (a source or heading-strip fix must reach the database).
    cur = await conn.execute('SELECT text FROM memorandum_notes WHERE note_no = 1')
    assert (await cur.fetchone())[0] == 'شرح.'
