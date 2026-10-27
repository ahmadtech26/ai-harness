from datetime import date

from legal_search.citation import METADATA_UNVERIFIED, UNVERIFIED, format_articles, format_memorandum
from legal_search.db import Found, LawMeta, Note

MAJALLA_NOTE = 'تطبق فيما لا يتعارض مع أحكام القانون المدني (المادة 1448)'


def _found(law: LawMeta = LawMeta(), verified: bool = False, title: str = 'قانون العقوبات الأردني') -> Found:
    return Found(id=1, law_slug='penal-code', number=153, suffix='مكرر', law_title=title, label='المادة 153 مكرر',
                 text='نص المادة.', source='jordan-lawyer.com', verified=verified, law=law)


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
        '(الجريدة الرسمية: العدد 4321، 5/6/1950)؛ المصدر: jordan-lawyer.com — '
    )


def test_unapproved_publication_data_is_labelled():
    details = format_articles([_found()]).splitlines()[2]

    assert details.endswith(f'— {UNVERIFIED}؛ {METADATA_UNVERIFIED})')


def test_approved_publication_data_and_a_verified_text_carry_no_label():
    details = format_articles([_found(LawMeta(approved=True), verified=True)]).splitlines()[2]

    assert details.endswith('— متحقق منه)')


def test_appends_the_law_note_to_each_result():
    majalla = _found(LawMeta(note=MAJALLA_NOTE), title='مجلة الأحكام العدلية')

    text = format_articles([majalla, majalla])

    assert text.count(f'ملاحظة: {MAJALLA_NOTE}') == 2


def test_memorandum_page_states_its_range_the_remaining_count_and_the_next_offset():
    notes = [Note(9, 'شرح.', 'example.test/memo'), Note(20, 'شرح آخر.', 'example.test/memo')]

    text = format_memorandum(1, 0, notes, 35)

    assert text.splitlines()[0] == 'المذكرة الإيضاحية للقانون المدني الأردني — المادة 1: الملاحظات 1 إلى 2 من 35'
    assert text.endswith('الملاحظات المتبقية: 33. للمتابعة: get_memorandum(article=1, offset=2)')


def test_each_memorandum_note_states_the_articles_it_explains():
    notes = [Note(74, 'شرح العربون.', 'example.test/memo', 107, 107),
             Note(166, 'شرح.', 'example.test/memo', 214, 238),
             Note(9, 'شرح بلا نطاق.', 'example.test/memo')]

    lines = format_memorandum(107, 0, notes, 3).splitlines()

    assert '[ملاحظة 74] (تشرح المادة 107)' in lines
    assert '[ملاحظة 166] (تشرح المواد 214–238)' in lines
    assert '[ملاحظة 9]' in lines
