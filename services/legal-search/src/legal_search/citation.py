"""The text a library result shows the model: the citation heading, the article, the publication data
the registry has (nothing it lacks), the source and verification labels, and a law's note.

The source line never names the copy site a text was taken from (owner: «Hide all copy sites»): a verified article
names the official sources and its label gives the Gazette issues, the Bureau's legislation id and version and the
verification date; any other article and every memorandum note names the library's own, unofficial copy.

The fork's client reads the status label as the details line's text after its last « — », up to «؛» or «)»
(ai-platform overlay/client/src/iqraa/answer/library/output.ts, statusLabelOf and isDetailsLine): the source line
comes before that dash, and a label never holds « — », «؛», «)» or «المادة» (tests/test_citation.py checks both)."""

from datetime import date

from legal_search.db import Found, Note
from legal_search.verification import Verification

UNVERIFIED = 'لم يُتحقق بعد من مطابقته للنص المنشور في الجريدة الرسمية'
VERIFIED = 'متحقق منه'
METADATA_UNVERIFIED = 'بيانات النشر لم يُتحقق منها بعد'
MEMORANDUM_TITLE = 'المذكرة الإيضاحية للقانون المدني الأردني'
MEMORANDUM_UNVERIFIED = 'لم يُتحقق بعد من مطابقته للنص الرسمي للمذكرة'
OFFICIAL_SOURCES = 'الجريدة الرسمية وديوان التشريع والرأي'  # the source of a verified article
LIBRARY_COPY = 'نسخة المكتبة، غير رسمية'  # the source of every other article and of the memorandum


def _date(value: date) -> str:
    return f'{value.day}/{value.month}/{value.year}'


def _gazette(issue: int | None, published: date | None) -> str | None:
    parts = [part for part in (f'العدد {issue}' if issue is not None else None, _date(published) if published else None) if part]
    return 'الجريدة الرسمية: ' + '، '.join(parts) if parts else None


def _page(page: str | None) -> str:
    return f' ص {page}' if page else ''


def verified_label(verification: Verification) -> str:
    """«متحقق منه: الجريدة الرسمية العدد 2645 ص 2 والعدد 5300 ص 10، ديوان التشريع والرأي معرّف التشريع 3392 بصيغته في
    1/10/2026، تاريخ التحقق 14/11/2026»: the Gazette issues of the text in force (oldest first), the Bureau's
    legislation id and the date of the version it showed (when the record has one), and the record's date."""
    issues = ' و'.join(f'العدد {ref.issue}{_page(ref.page)}' for ref in verification.gazette)
    bureau = f'ديوان التشريع والرأي معرّف التشريع {verification.bureau_id}'
    if verification.bureau_as_of:
        bureau += f' بصيغته في {_date(verification.bureau_as_of)}'
    return f'{VERIFIED}: الجريدة الرسمية {issues}، {bureau}، تاريخ التحقق {_date(verification.checked_on)}'


def heading(found: Found) -> str:
    name = found.law_title
    if found.law.number is not None:
        name += f' رقم {found.law.number}'
    if found.law.year is not None:
        name += f' لسنة {found.law.year}'
    return f'{name} — {found.label}'


def details(found: Found) -> str:
    law = found.law
    parts = []
    gazette = _gazette(law.gazette_issue, law.gazette_date)
    if gazette:
        parts.append(gazette)
    if law.amendment_law is not None or law.amendment_year is not None:
        amendment = 'آخر تعديل: القانون المعدِّل'
        if law.amendment_law is not None:
            amendment += f' رقم {law.amendment_law}'
        if law.amendment_year is not None:
            amendment += f' لسنة {law.amendment_year}'
        amended_in = _gazette(law.amendment_gazette_issue, law.amendment_gazette_date)
        if amended_in:
            amendment += f' ({amended_in})'
        parts.append(amendment)
    if found.verification is not None:
        parts.append(f'المصدر: {OFFICIAL_SOURCES}')
        status = verified_label(found.verification)
    else:
        parts.append(f'المصدر: {LIBRARY_COPY}')
        status = UNVERIFIED
    if not law.approved:
        status += f'؛ {METADATA_UNVERIFIED}'
    return f'({"؛ ".join(parts)} — {status})'


def format_articles(found: list[Found]) -> str:
    blocks = []
    for index, article in enumerate(found, start=1):
        block = f'[{index}] {heading(article)}\n{article.text}\n{details(article)}'
        if article.law.note:
            block += f'\nملاحظة: {article.law.note}'
        blocks.append(block)
    return '\n\n'.join(blocks)


def _scope(note: Note) -> str:
    """« (تشرح المادة 107)» or « (تشرح المواد 214–238)»; empty when the note's articles are unknown."""
    if note.first_article is None:
        return ''
    if note.last_article is None or note.last_article == note.first_article:
        return f' (تشرح المادة {note.first_article})'
    return f' (تشرح المواد {note.first_article}–{note.last_article})'


def format_memorandum(article: int, offset: int, notes: list[Note], total: int) -> str:
    last = offset + len(notes)
    blocks = [f'{MEMORANDUM_TITLE} — المادة {article}: الملاحظات {offset + 1} إلى {last} من {total}']
    blocks += [f'[ملاحظة {note.note_no}]{_scope(note)}\n{note.text}\n(المصدر: {LIBRARY_COPY} — {MEMORANDUM_UNVERIFIED})'
               for note in notes]
    left = total - last
    if left > 0:
        blocks.append(f'الملاحظات المتبقية: {left}. للمتابعة: get_memorandum(article={article}, offset={last})')
    else:
        blocks.append('لا ملاحظات أخرى لهذه المادة.')
    return '\n\n'.join(blocks)
