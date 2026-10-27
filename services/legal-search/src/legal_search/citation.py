"""The text a library result shows the model: the citation heading, the article, the publication data
the registry has (nothing it lacks), the verification labels, and a law's note."""

from datetime import date

from legal_search.db import Found, Note

UNVERIFIED = 'لم يُتحقق بعد من مطابقته للنص المنشور في الجريدة الرسمية'
VERIFIED = 'متحقق منه'
METADATA_UNVERIFIED = 'بيانات النشر لم يُتحقق منها بعد'
MEMORANDUM_TITLE = 'المذكرة الإيضاحية للقانون المدني الأردني'
MEMORANDUM_UNVERIFIED = 'لم يُتحقق بعد من مطابقته للنص الرسمي للمذكرة'


def _date(value: date) -> str:
    return f'{value.day}/{value.month}/{value.year}'


def _gazette(issue: int | None, published: date | None) -> str | None:
    parts = [part for part in (f'العدد {issue}' if issue is not None else None, _date(published) if published else None) if part]
    return 'الجريدة الرسمية: ' + '، '.join(parts) if parts else None


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
    parts.append(f'المصدر: {found.source}')
    status = VERIFIED if found.verified else UNVERIFIED
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
    blocks += [f'[ملاحظة {note.note_no}]{_scope(note)}\n{note.text}\n(المصدر: {note.source} — {MEMORANDUM_UNVERIFIED})'
               for note in notes]
    left = total - last
    if left > 0:
        blocks.append(f'الملاحظات المتبقية: {left}. للمتابعة: get_memorandum(article={article}, offset={last})')
    else:
        blocks.append('لا ملاحظات أخرى لهذه المادة.')
    return '\n\n'.join(blocks)
