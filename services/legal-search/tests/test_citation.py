import hashlib
import re
from dataclasses import replace as with_changes
from datetime import date

import pytest

from legal_search.citation import (
    AMENDING_LAW,
    AMENDING_REGULATION,
    LIBRARY_COPY,
    MEMORANDUM_TITLE,
    MEMORANDUM_UNVERIFIED,
    METADATA_UNVERIFIED,
    OFFICIAL_SOURCES,
    RETRIEVAL_ID,
    UNVERIFIED,
    VERIFIED,
    format_articles,
    format_memorandum,
    heading,
    verified_label,
)
from legal_search.db import Found, LawMeta, Note
from legal_search.verification import GazetteRef, Verification

MAJALLA_NOTE = 'تطبق فيما لا يتعارض مع أحكام القانون المدني (المادة 1448)'
CHECKED = Verification(date(2026, 11, 14), (GazetteRef('2645', '2'), GazetteRef('5300', '10')), '3392', date(2026, 10, 1))
CHECKED_LABEL = ('متحقق منه: الجريدة الرسمية العدد 2645 ص 2 والعدد 5300 ص 10، ديوان التشريع والرأي معرّف التشريع 3392 '
                 'بصيغته في 1/10/2026، تاريخ التحقق 14/11/2026')
# The articles' library ids (articles.id, plan S8): apart from every number, year and block index here, so an id the
# details line took from anything but the row would show.
ARTICLE_ID = 4817
FEES_ID = 2093


def _found(law: LawMeta = LawMeta(), verification: Verification | None = None,
           title: str = 'قانون العقوبات الأردني') -> Found:
    return Found(id=ARTICLE_ID, law_slug='penal-code', number=153, suffix='مكرر', law_title=title, label='المادة 153 مكرر',
                 text='نص المادة.', verification=verification, law=law)


def test_heading_shows_title_number_year_and_label():
    text = format_articles([_found(LawMeta(number=99, year=1900))])

    assert text.splitlines()[0] == '[1] قانون العقوبات الأردني رقم 99 لسنة 1900 — المادة 153 مكرر'


def test_omits_every_field_the_registry_lacks():
    text = format_articles([_found()])

    assert text.splitlines()[0] == '[1] قانون العقوبات الأردني — المادة 153 مكرر'
    assert not any(part in text for part in ('رقم', 'لسنة', 'الجريدة الرسمية:', 'آخر تعديل', 'ملاحظة:'))


def test_shows_the_gazette_and_the_latest_amendment():
    law = LawMeta(gazette_issue=1234, gazette_date=date(1900, 3, 2), amendment_law=7, amendment_year=1950,
                  amendment_gazette_issue=4321, amendment_gazette_date=date(1950, 6, 5))

    details = format_articles([_found(law)]).splitlines()[2]

    assert details.startswith(
        '(الجريدة الرسمية: العدد 1234، 2/3/1900؛ آخر تعديل: القانون المعدِّل رقم 7 لسنة 1950 '
        '(الجريدة الرسمية: العدد 4321، 5/6/1950)؛ المصدر: نسخة المكتبة، غير رسمية؛ معرّف النص في المكتبة: 4817 — '
    )


# A regulation (registry `instrument`): court-fees is the schedule of نظام رسوم المحاكم رقم 43 لسنة 2005, last amended
# by نظام رقم 108 لسنة 2008. A law prints as before.

FEES = LawMeta(number=43, year=2005, gazette_issue=4711, gazette_date=date(2005, 6, 16), amendment_law=108,
               amendment_year=2008, amendment_gazette_issue=4935, amendment_gazette_date=date(2008, 11, 2),
               instrument='regulation')


def _article_1(law: LawMeta, title: str) -> Found:
    return Found(id=FEES_ID, law_slug='court-fees', number=1, suffix='', law_title=title, label='المادة 1', text='نص.',
                 law=law)


@pytest.mark.parametrize('law, title, expected', [
    (with_changes(FEES, instrument='law'), 'قانون العمل', 'قانون العمل رقم 43 لسنة 2005 — المادة 1'),
    (FEES, 'جدول رسوم المحاكم', 'جدول رسوم المحاكم رقم 43 لسنة 2005 — المادة 1'),
    (FEES, 'نظام رسوم المحاكم', 'نظام رسوم المحاكم رقم 43 لسنة 2005 — المادة 1'),
    (LawMeta(instrument='regulation'), 'جدول رسوم المحاكم', 'جدول رسوم المحاكم — المادة 1'),
], ids=['law', 'regulation', 'regulation titled نظام', 'regulation without number or year'])
def test_a_regulation_keeps_its_plain_title_in_its_heading(law: LawMeta, title: str, expected: str):
    assert heading(_article_1(law, title)) == expected
    assert format_articles([_article_1(law, title)]).splitlines()[0] == f'[1] {expected}'
    assert expected.count('—') == 1  # the heading's only dash is the one before the label


@pytest.mark.parametrize('instrument, amending', [('law', AMENDING_LAW), ('regulation', AMENDING_REGULATION)])
def test_the_amendment_line_names_the_instrument_that_amended_it(instrument: str, amending: str):
    details = format_articles([_article_1(with_changes(FEES, instrument=instrument), 'جدول رسوم المحاكم')]).splitlines()[2]

    assert details == (
        f'(الجريدة الرسمية: العدد 4711، 16/6/2005؛ آخر تعديل: {amending} رقم 108 لسنة 2008 (الجريدة الرسمية: العدد 4935، '
        f'2/11/2008)؛ المصدر: {LIBRARY_COPY}؛ {RETRIEVAL_ID}{FEES_ID} — {UNVERIFIED}؛ {METADATA_UNVERIFIED})')
    assert (AMENDING_LAW, AMENDING_REGULATION) == ('القانون المعدِّل', 'النظام المعدِّل')
    assert details.count('—') == 1  # the client's label still starts after the only dash


# The labels the model relays word for word (AQEL v1.3 line 73) and the fork's client reads: byte for byte as on
# recall-plan 649559a (sha256 of each constant's UTF-8 there).
@pytest.mark.parametrize('text, sha256', [
    (UNVERIFIED, 'd1dfbfbc715895dfbba45ef2cbbb26afa47713b0b19556ee5f893ff35adb0575'),
    (VERIFIED, '4777bb62cbee9387b5241c30330340d294253e3067c54e71c4e9250832ea3f5f'),
    (METADATA_UNVERIFIED, 'c2688c29f061681ddf490e4b9a849efd66ef71e3a802f0f3de5515bb4b6f945f'),
    (MEMORANDUM_TITLE, '30e50d85541e3e0c0f95b9077ee6735281826d454dfc2b149b324af4dd023e90'),
    (MEMORANDUM_UNVERIFIED, 'bf247f254f4dccead399d06067fafeef14ada4c2f6acc16f1b53e70b7a235fbe'),
], ids=['UNVERIFIED', 'VERIFIED', 'METADATA_UNVERIFIED', 'MEMORANDUM_TITLE', 'MEMORANDUM_UNVERIFIED'])
def test_the_labels_keep_their_bytes(text, sha256):
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == sha256


def test_an_unverified_article_names_the_library_copy_and_no_site():
    details = format_articles([_found()]).splitlines()[2]

    assert details == f'(المصدر: {LIBRARY_COPY}؛ {RETRIEVAL_ID}{ARTICLE_ID} — {UNVERIFIED}؛ {METADATA_UNVERIFIED})'
    assert LIBRARY_COPY == 'نسخة المكتبة، غير رسمية'


def test_an_unverified_article_of_an_approved_law_carries_the_text_label_alone():
    details = format_articles([_found(LawMeta(approved=True))]).splitlines()[2]

    assert details == f'(المصدر: {LIBRARY_COPY}؛ {RETRIEVAL_ID}{ARTICLE_ID} — {UNVERIFIED})'


def test_a_verified_article_names_the_official_sources_its_gazette_issues_the_bureau_and_the_date():
    details = format_articles([_found(LawMeta(approved=True), CHECKED)]).splitlines()[2]

    assert details == f'(المصدر: {OFFICIAL_SOURCES}؛ {RETRIEVAL_ID}{ARTICLE_ID} — {CHECKED_LABEL})'
    assert OFFICIAL_SOURCES == 'الجريدة الرسمية وديوان التشريع والرأي'


def test_a_verified_article_of_an_unapproved_law_keeps_the_publication_data_label():
    details = format_articles([_found(verification=CHECKED)]).splitlines()[2]

    assert details.endswith(f'— {CHECKED_LABEL}؛ {METADATA_UNVERIFIED})')
    assert f'؛ {METADATA_UNVERIFIED}' in details  # exactly as v1.3 line 73 quotes it


def test_the_verified_label_leaves_out_a_page_and_a_bureau_date_the_record_lacks():
    bare = Verification(date(2026, 1, 5), (GazetteRef('4632'),), 'A12')

    assert verified_label(bare) == 'متحقق منه: الجريدة الرسمية العدد 4632، ديوان التشريع والرأي معرّف التشريع A12، تاريخ التحقق 5/1/2026'


# The retrieval id (plan S8, owner: «Server + retrieval id»): the last part of the details parentheses, after the source
# and before « — <label>», in the form the fork's client parses (ai-platform overlay/client/src/iqraa/answer/library,
# __tests__/fixtures/rendered.ts RETRIEVAL_ID), written out in these two tests.

@pytest.mark.parametrize('article_id', [ARTICLE_ID, 90210])
@pytest.mark.parametrize('verification', [None, CHECKED], ids=['unverified', 'verified'])
def test_an_article_carries_its_rows_library_id_as_the_last_part_before_the_label(article_id, verification):
    article = with_changes(_found(LawMeta(approved=True), verification), id=article_id)

    details = format_articles([article]).splitlines()[2]

    source = OFFICIAL_SOURCES if verification else LIBRARY_COPY
    label = CHECKED_LABEL if verification else UNVERIFIED
    assert details == f'(المصدر: {source}؛ معرّف النص في المكتبة: {article_id} — {label})'


def test_each_memorandum_note_carries_its_number_as_its_library_id():
    notes = [Note(74, 'شرح العربون.', 107, 107), Note(166, 'شرح.', 214, 238)]

    lines = format_memorandum(107, 0, notes, 2).splitlines()

    assert [line for line in lines if line.startswith('(')] == [
        f'(المصدر: {LIBRARY_COPY}؛ معرّف النص في المكتبة: 74 — {MEMORANDUM_UNVERIFIED})',
        f'(المصدر: {LIBRARY_COPY}؛ معرّف النص في المكتبة: 166 — {MEMORANDUM_UNVERIFIED})',
    ]


def _client_label(details: str) -> str | None:
    """The fork's client, transcribed (ai-platform overlay/client/src/iqraa/answer/library/output.ts, statusLabelOf and
    isDetailsLine; first copied at f93f257, checked again on 2026-11-16 against the round-2 parser, whose header gives
    the retrieval id's place): a details line starts with «(», ends with «)», has «المصدر: » before its last « — »; its
    label is the text after that dash up to the first «؛» or «)», trimmed."""
    source = details.find('المصدر: ')
    dash = details.rfind(' — ')
    if not (details.startswith('(') and details.endswith(')') and 0 <= source < dash):
        return None
    rest = details[dash + len(' — '):]
    end = re.search('[؛)]', rest)
    return (rest[:end.start()] if end else rest).strip() or None


def _client_sources(text: str) -> list[str]:
    """The staging checks' source reader, transcribed (AI Harness-demo deploy/staging/lib.mjs sourcesOf,
    /المصدر: (.*?)(?:؛| — )/g): each source line's text up to the first «؛» or « — »."""
    return [match.group(1) for match in re.finditer('المصدر: (.*?)(?:؛| — )', text)]


@pytest.mark.parametrize('law', [LawMeta(), LawMeta(approved=True), FEES], ids=['draft law', 'approved law',
                                                                                   'regulation'])
@pytest.mark.parametrize('verification', [None, CHECKED], ids=['unverified', 'verified'])
def test_the_client_reads_the_whole_label_and_the_label_holds_nothing_it_forbids(law, verification):
    details = format_articles([_found(law, verification)]).splitlines()[2]

    label = _client_label(details)

    assert label == (CHECKED_LABEL if verification else UNVERIFIED)
    assert not any(forbidden in label for forbidden in (' — ', '—', '؛', ')', 'المادة'))
    # The source stops at «؛»: the retrieval id after it is never read as part of the source.
    assert _client_sources(details) == [OFFICIAL_SOURCES if verification else LIBRARY_COPY]
    assert f'؛ {RETRIEVAL_ID}{ARTICLE_ID} — ' in details


def test_the_client_reads_the_memorandum_label():
    text = format_memorandum(107, 0, [Note(74, 'شرح العربون.', 107, 107)], 1)

    details = text.split('\n\n')[1].splitlines()[-1]

    assert details == f'(المصدر: {LIBRARY_COPY}؛ {RETRIEVAL_ID}74 — {MEMORANDUM_UNVERIFIED})'
    assert _client_label(details) == MEMORANDUM_UNVERIFIED
    assert _client_sources(details) == [LIBRARY_COPY]


def test_appends_the_law_note_to_each_result():
    majalla = _found(LawMeta(note=MAJALLA_NOTE), title='مجلة الأحكام العدلية')

    text = format_articles([majalla, majalla])

    assert text.count(f'ملاحظة: {MAJALLA_NOTE}') == 2


def test_memorandum_page_states_its_range_the_remaining_count_and_the_next_offset():
    notes = [Note(9, 'شرح.'), Note(20, 'شرح آخر.')]

    text = format_memorandum(1, 0, notes, 35)

    assert text.splitlines()[0] == 'المذكرة الإيضاحية للقانون المدني الأردني — المادة 1: الملاحظات 1 إلى 2 من 35'
    assert text.endswith('الملاحظات المتبقية: 33. للمتابعة: get_memorandum(article=1, offset=2)')


def test_each_memorandum_note_states_the_articles_it_explains():
    notes = [Note(74, 'شرح العربون.', 107, 107),
             Note(166, 'شرح.', 214, 238),
             Note(9, 'شرح بلا نطاق.')]

    lines = format_memorandum(107, 0, notes, 3).splitlines()

    assert '[ملاحظة 74] (تشرح المادة 107)' in lines
    assert '[ملاحظة 166] (تشرح المواد 214–238)' in lines
    assert '[ملاحظة 9]' in lines
