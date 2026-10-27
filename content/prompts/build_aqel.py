"""Build the LibreChat edition of the AQEL prompt from the owner's source text (exact, asserted edits).

    python -I content/prompts/build_aqel.py 1.2

Reads aqel-v<version>-source.txt (kept verbatim for provenance) and writes aqel-v<version>-librechat.md.
Only platform wording is adapted: the date variable, AnythingLLM workspaces and indexing, and how the
legal library is reached (the search_law / get_article / get_memorandum tools). Every replacement must match exactly once
and no platform term may survive, so a changed source fails loudly instead of being half-adapted.
"""

import sys
from pathlib import Path

HERE = Path(__file__).parent

LIBRARY_TOOLS_AR_V11 = (
    'استخدام المكتبة القانونية\n'
    '- قبل الاستشهاد بأي مادة استدعِ search_law بعبارة بحث عربية دقيقة، أو get_article إذا عرفت رقم المادة؛ وانقل النص حرفيًا كما أعادته الأداة.\n'
    '- انقل حالة التحقق كما وردت في نتيجة الأداة؛ فإذا ذُكر أن النص لم يُتحقق بعد من مطابقته للجريدة الرسمية فاذكر ذلك ولا تصفه بأنه النص النافذ المعتمد.\n'
    '- المكتبة المحمّلة حاليًا: القانون المدني الأردني فقط. إذا تعلق السؤال بقانون آخر أو باجتهاد قضائي فصرّح بأنه غير محمّل بعد، ولا تستشهد به.\n'
    '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح من النصوص فاعتمد على ما استرجعته سابقًا في المحادثة ولا تحاول الالتفاف على الحد.'
)

# These bullets say what the library tools return (the 22 statutes of corpus v1 and the Civil Code memorandum,
# today). Update them, rebuild the edition and re-release the specialist whenever legal-search's content changes.
LIBRARY_TOOLS_AR = (
    'استخدام المكتبة القانونية\n'
    '- قبل الاستشهاد بأي مادة استدعِ search_law بعبارة بحث عربية دقيقة، أو get_article إذا عرفت رقم المادة؛ وانقل النص حرفيًا كما أعادته الأداة.\n'
    '- انقل حالة التحقق كما وردت في نتيجة الأداة؛ فإذا ذُكر أن النص لم يُتحقق بعد من مطابقته للجريدة الرسمية فاذكر ذلك ولا تصفه بأنه النص النافذ المعتمد. وانقل رقم القانون وسنته وبيانات الجريدة الرسمية وآخر تعديل كما وردت في النتيجة فقط، ومعها تنبيه «بيانات النشر لم يُتحقق منها بعد» إن ورد.\n'
    '- التشريعات المحمّلة في المكتبة ورموزها: القانون المدني الأردني (civil-code)، مجلة الأحكام العدلية (majalla)، '
    'قانون المالكين والمستأجرين (landlords-tenants)، قانون العقوبات الأردني (penal-code)، قانون التجارة (commerce)، '
    'قانون التجارة البحرية (maritime-commerce)، قانون الشركات (companies)، قانون الجمارك (customs)، '
    'قانون ضريبة الدخل (income-tax)، قانون الضريبة العامة على المبيعات (sales-tax)، قانون العمل (labour)، '
    'قانون صندوق الاستثمار الأردني (investment-fund)، قانون أصول المحاكمات المدنية (civil-procedure)، '
    'قانون البينات (evidence)، قانون التنفيذ (execution)، قانون الوساطة لتسوية النزاعات المدنية (mediation)، '
    'قانون أصول المحاكمات الجزائية (criminal-procedure)، قانون تشكيل المحاكم النظامية (courts-formation)، '
    'قانون محاكم الصلح (magistrates-courts)، قانون محكمة الجنايات الكبرى (major-felonies-court)، '
    'جدول رسوم المحاكم (court-fees)، قانون نقابة المحامين النظاميين (bar-association). '
    'أما الاجتهادات القضائية وأي تشريع غير مذكور هنا فليست في المكتبة بعد: إذا تعلق السؤال بها فصرّح بذلك ولا تستشهد بها من الذاكرة.\n'
    '- لحصر البحث في تشريع واحد مرّر رمزه في الوسيط law لـ search_law (مثل law="penal-code")، ومرّره كذلك لـ get_article؛ فإن لم تمرّره افترضت get_article القانون المدني.\n'
    '- مجلة الأحكام العدلية (majalla) مصدر تكميلي: تطبق فيما لا يتعارض مع أحكام القانون المدني (المادة 1448 منه). ابدأ بنص القانون المدني، ولا تستشهد بالمجلة مقدَّمةً عليه، وانقل التنبيه الذي يرد مع كل مادة منها.\n'
    '- لشرح مادة من القانون المدني استدعِ get_memorandum برقم المادة لاسترجاع ملاحظات المذكرة الإيضاحية صفحةً بعد صفحة (استعمل offset الذي تذكره الأداة للصفحة التالية). المذكرة تفسير لا نص تشريعي، فلا تقدّمها على نص المادة.\n'
    '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح من النصوص فاعتمد على ما استرجعته سابقًا في المحادثة ولا تحاول الالتفاف على الحد.'
)

LIBRARY_TOOLS_EN = (
    '- The legal-library tools return the 22 Jordanian statutes named, with their slugs, in the Arabic library section '
    '(search_law and get_article take law="<slug>"; get_article defaults to civil-code) and the Civil Code explanatory '
    'memorandum (get_memorandum, paged). The Majalla (majalla) applies only where it does not conflict with the Civil '
    'Code (art. 1448): never cite it over the Civil Code. Judgments and other legislation are not loaded yet: say so '
    'rather than citing them from memory, and pass on the verification status each result carries.'
)

EDITIONS = {
    '1.1': {
        'replacements': [
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
                LIBRARY_TOOLS_AR_V11,
            ),
        ],
        'leftovers': ['AnythingLLM', '{datetime}', 'قبل رفع القوانين'],
    },
    '1.2': {
        'replacements': [
            # LibreChat substitutes {{current_datetime}} in agent instructions.
            ('التاريخ الحالي في بيئة البرنامج: {datetime}', 'التاريخ الحالي في بيئة البرنامج: {{current_datetime}}'),
            ('Current date and time in the application: {datetime}', 'Current date and time in the application: {{current_datetime}}'),
            ('واجهة AnythingLLM أو تصميمها.', 'واجهة المنصة أو تصميمها.'),
            ('الوصول تحدده صلاحيات AnythingLLM وإعدادات مساحات العمل،', 'الوصول تحدده صلاحيات المنصة،'),
            (
                'استخدم فقط الملفات التي تظهر فعليًا في سياق الاسترجاع لمساحة العمل الحالية؛ لا تفترض أن كل الملفات المرفوعة متاحة لكل مساحة عمل،',
                'استخدم فقط النصوص التي تعيدها فعليًا أدوات المكتبة القانونية في المحادثة الحالية أو المستندات التي يرفقها المستخدم؛ لا تفترض أن كل الملفات المرفوعة إلى المشروع متاحة في المكتبة،',
            ),
            ('منهج الاسترجاع والاستشهاد داخل AnythingLLM', 'منهج الاسترجاع والاستشهاد داخل المنصة'),
            (
                'لا تزعم أن وصف «حفظ وتضمين» أو وجود ملف داخل مساحة العمل يثبت سلامة عملية الاسترجاع',
                'لا تزعم أن رفع ملف إلى المكتبة أو فهرسته يثبت سلامة عملية الاسترجاع',
            ),
            ('\nتعليمات ضبط الجودة القانونية\n', f'\n{LIBRARY_TOOLS_AR}\n\nتعليمات ضبط الجودة القانونية\n'),
            ('current or available in every workspace.', 'current or available to the legal-library tools.'),
            (
                '- Permissions must be enforced through AnythingLLM and the underlying systems;',
                '- Permissions must be enforced through the platform and the underlying systems;',
            ),
            (
                'Use documents actually returned by retrieval in the active workspace.',
                'Use documents actually returned by the legal-library tools (search_law, get_article, get_memorandum) in the current conversation, or documents the user attached.',
            ),
            (
                '- No upload/indexing confirmation proves real retrieval or legal accuracy without a tested query and source inspection.',
                '- No upload/indexing confirmation proves real retrieval or legal accuracy without a tested query and source inspection.\n'
                + LIBRARY_TOOLS_EN,
            ),
        ],
        'leftovers': ['AnythingLLM', '{datetime}', 'مساحة العمل', 'مساحات العمل', 'مساحة عمل', 'workspace', 'حفظ وتضمين'],
    },
}


def build(version: str) -> int:
    edition = EDITIONS[version]
    source = HERE / f'aqel-v{version}-source.txt'
    text = source.read_bytes().decode('utf-8-sig').replace('\r\n', '\n')
    for old, new in edition['replacements']:
        if text.count(old) != 1:
            print(f'FAIL: expected exactly one match for: {old[:60]!r}')
            return 1
        text = text.replace(old, new)
    for leftover in edition['leftovers']:
        if leftover in text:
            print(f'FAIL: the built text still contains {leftover!r}')
            return 1
    target = HERE / f'aqel-v{version}-librechat.md'
    target.write_text(text, encoding='utf-8', newline='\n')
    print(f'wrote {target.name} ({len(text)} characters)')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in EDITIONS:
        print(f'usage: build_aqel.py <{"|".join(EDITIONS)}>')
        sys.exit(2)
    sys.exit(build(sys.argv[1]))
