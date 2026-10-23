"""Build the LibreChat edition of the AQEL prompt from the owner's source text (exact, asserted edits).

    python -I content/prompts/build_aqel.py

Reads aqel-v1.1-source.txt (kept verbatim for provenance) and writes aqel-v1.1-librechat.md. Every
replacement must match exactly once, so a changed source fails loudly instead of being half-adapted.
"""

import sys
from pathlib import Path

HERE = Path(__file__).parent

REPLACEMENTS = [
    # LibreChat substitutes {{current_datetime}} in agent instructions.
    ('التاريخ الحالي في بيئة البرنامج: {datetime}', 'التاريخ الحالي في بيئة البرنامج: {{current_datetime}}'),
    ('تغيير اتجاه واجهة AnythingLLM أو تصميمها.', 'تغيير اتجاه واجهة المنصة أو تصميمها.'),
    (
        'قبل رفع القوانين، لا تدّع امتلاك مكتبة قانونية، ولا تذكر أرقام مواد أو أحكام باعتبارها موثقة من النظام.',
        'ولا تذكر رقم مادة أو نصها أو حكمًا باعتباره موثقًا إلا بعد استرجاعه في هذه المحادثة بأدوات المكتبة القانونية (search_law وget_article) أو وروده في مستند زوّد به المستخدم.',
    ),
    ('الوصول تحدده صلاحيات AnythingLLM وإعدادات مساحات العمل،', 'الوصول تحدده صلاحيات المنصة،'),
    (
        'الهدف التشغيلي الحالي قبل رفع القوانين\n'
        'أنت الآن في مرحلة «اختبار العقل بلا مكتبة قوانين». يمكنك تدريب المستخدم على تنظيم الوقائع، صياغة أسئلة التحقيق، '
        'المقارنة بين استراتيجيات افتراضية، وتجهيز قوالب أولية مشروطة. يجب أن تُقرّ بغياب النصوص المعتمدة إذا طلب اقتباس '
        'مادة قانونية أو الاستناد إلى حكم محدد. سننتقل لاحقًا إلى الاستشهاد الفعلي بعد التحقق من الوثائق الرسمية وفهرستها '
        'واختبار استرجاعها.',
        'استخدام المكتبة القانونية\n'
        '- قبل الاستشهاد بأي مادة استدعِ search_law بعبارة بحث عربية دقيقة، أو get_article إذا عرفت رقم المادة؛ وانقل النص حرفيًا كما أعادته الأداة.\n'
        '- انقل حالة التحقق كما وردت في نتيجة الأداة؛ فإذا ذُكر أن النص لم يُتحقق بعد من مطابقته للجريدة الرسمية فاذكر ذلك ولا تصفه بأنه النص النافذ المعتمد.\n'
        '- المكتبة المحمّلة حاليًا: القانون المدني الأردني فقط. إذا تعلق السؤال بقانون آخر أو باجتهاد قضائي فصرّح بأنه غير محمّل بعد، ولا تستشهد به.\n'
        '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح من النصوص فاعتمد على ما استرجعته سابقًا في المحادثة ولا تحاول الالتفاف على الحد.',
    ),
]


def main() -> int:
    text = (HERE / 'aqel-v1.1-source.txt').read_text(encoding='utf-8').replace('\r\n', '\n')
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            print(f'FAIL: expected exactly one match for: {old[:60]}')
            return 1
        text = text.replace(old, new)
    for leftover in ('AnythingLLM', '{datetime}', 'قبل رفع القوانين'):
        if leftover in text:
            print(f'FAIL: source text still contains {leftover!r}')
            return 1
    (HERE / 'aqel-v1.1-librechat.md').write_text(text, encoding='utf-8', newline='\n')
    print(f'wrote aqel-v1.1-librechat.md ({len(text)} characters)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
