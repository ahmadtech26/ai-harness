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

# The library limits the specialist is told (owner, 2026-11-11 about 18:10Z: «Keep 8, tell the model»). They MUST equal
# legal-search's live guard_settings, which staff change without a restart (read 2026-11-11: per_answer 8,
# max_results 5, daily 300). When staff change per_answer or max_results, change it here, rebuild, recompose and
# re-apply the instructions, or the model plans with a budget it does not have. The daily cap is not stated: a
# throttled account gets throttle_daily_cap instead, and the tool answers both with one message (tools.py CAP_REACHED).
PER_ANSWER = 8  # guard_settings.per_answer: texts (articles and memorandum notes) one answer may receive in all
PER_SEARCH = 5  # guard_settings.max_results: the most one search_law call returns, whatever its limit
THREE_SEARCH_LIMIT = 3  # the limit= the model passes to each of three planned searches, so the third still gets texts
THIRD_SEARCH_SHARE = min(THREE_SEARCH_LIMIT, PER_ANSWER - 2 * THREE_SEARCH_LIMIT)  # 2 today: 3+3+2
if THIRD_SEARCH_SHARE < 1 or THREE_SEARCH_LIMIT > PER_SEARCH:
    raise SystemExit('FAIL: three searches of THREE_SEARCH_LIMIT no longer fit PER_ANSWER and PER_SEARCH')
PLANNED_SPLIT = f'{THREE_SEARCH_LIMIT}+{THREE_SEARCH_LIMIT}+{THIRD_SEARCH_SHARE}'

LIBRARY_TOOLS_AR_V11 = (
    'استخدام المكتبة القانونية\n'
    '- قبل الاستشهاد بأي مادة استدعِ search_law بعبارة بحث عربية دقيقة، أو get_article إذا عرفت رقم المادة؛ وانقل النص حرفيًا كما أعادته الأداة.\n'
    '- انقل حالة التحقق كما وردت في نتيجة الأداة؛ فإذا ذُكر أن النص لم يُتحقق بعد من مطابقته للجريدة الرسمية فاذكر ذلك ولا تصفه بأنه النص النافذ المعتمد.\n'
    '- المكتبة المحمّلة حاليًا: القانون المدني الأردني فقط. إذا تعلق السؤال بقانون آخر أو باجتهاد قضائي فصرّح بأنه غير محمّل بعد، ولا تستشهد به.\n'
    '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح من النصوص فاعتمد على ما استرجعته سابقًا في المحادثة ولا تحاول الالتفاف على الحد.'
)

# The language of the model's reasoning (owner, 2026-11-12 ~16:2xZ, after a live expert answer reasoned mostly in
# English on screen: «the thinking must be explicitly in arabic language only»). It heads the library section so it
# sits before the planning and budget rules it applies to; LIBRARY_TOOLS_EN repeats it first.
REASONING_LANGUAGE_AR = (
    'لغة التفكير\n'
    '- فكّر بالعربية وحدها: اكتب تفكيرك الداخلي كله، من فهم السؤال وتخطيط البحث إلى تحليل النصوص المسترجعة وبناء الإجابة، '
    'باللغة العربية الفصحى، ولا تفكّر بالإنجليزية ولا بأي لغة أخرى في أي مرحلة. لا يُستثنى إلا رموز التشريعات (مثل penal-code) '
    'وأسماء الأدوات وقيم وسائطها، فتبقى كما هي. والإجابة نفسها بالعربية.\n\n'
)

# These bullets say what the library tools return (the 22 statutes of corpus v1 and the Civil Code memorandum,
# today). Update them, rebuild the edition and re-release the specialist whenever legal-search's content changes.
LIBRARY_TOOLS_AR = (
    REASONING_LANGUAGE_AR
    + 'استخدام المكتبة القانونية\n'
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
    # Owner, 2026-11-11, after the stakeholder demo: «Broad questions must be narrowed, otherwise the answer won't be
    # accurate anyway». Each answer gets a fixed number of texts, so a broad question spread its searches thin and
    # the gaps were filled from memory (.hq/docs/audits/librechat-platform/demo-usage/failures-2026-11-11.md).
    # Owner, about 18:10Z: «Keep 8, tell the model»: the numbers above, and three planned searches at limit 3. At the
    # limit the one run under the earlier wording named no gap and stated a rule of law from memory (Fable 5.2 review).
    # Conditional analysis stays allowed (rule 5 of the quality rules is the owner's), but without a figure from memory.
    f'- لكل إجابة رصيد لا يتجاوز {PER_ANSWER} من نصوص المكتبة في مجموعها: يعيد البحث الواحد بـ search_law ما لا يزيد على {PER_SEARCH} منها ويُحتسب بعدد ما أعاده، وتُحتسب المادة التي تعيدها get_article نصًا واحدًا، وكذلك كل ملاحظة تعيدها get_memorandum. '
    'فخطّط لعمليات البحث قبل أول استدعاء: إذا كان السؤال واسعًا يجمع مسائل أو تشريعات عدة، فحدّد المسألة الحاسمة وابحث عنها أولًا، أو اطلب من المستخدم أن يضيّق سؤاله، ولا توزّع البحث على كل الجوانب. '
    f'وإذا خطّطت لثلاث عمليات بحث فمرّر limit={THREE_SEARCH_LIMIT} في كل منها ليتسع الرصيد للثالثة ({PLANNED_SPLIT})، واحسب من هذه العمليات أي صياغة ثانية تجرّبها. '
    'ابحث بالمصطلح القانوني الذي يستعمله نص التشريع نفسه لا بوصف عام للمسألة، ومرّر law كلما عُرف التشريع.\n'
    '- إذا أعادت الأداة أنه تم بلوغ الحد المسموح من النصوص فلا تستدعِ أدوات المكتبة بعدها في هذه الإجابة، ولا تحاول الالتفاف على الحد. '
    'أجب بما تدعمه النصوص المسترجعة في المحادثة وحدها، واذكر للمستخدم صراحةً، بموضوعها لا بأرقام مواد، النقاط التي بقيت دون نص مسترجع. '
    'ولا تسدّ النقص من الذاكرة أو بعبارة مثل «اجتهاد مستقر»: لا تذكر لهذه النقاط، ولو في تحليل مشروط، مقدارًا أو مدةً أو ميعادًا أو محكمةً مختصة، ولا أن الأمر متروك لتقدير المحكمة، ما لم يرد ذلك في نص مسترجع. '
    'واقترح على المستخدم أن يسأل عن كل نقطة منها في سؤال مستقل، فلكل إجابة رصيدها. '
    'لكن الرسالة نفسها تصدر عند بلوغ الحد اليومي للحساب: فإذا جاءت قبل أن تستنفد الإجابة رصيدها، فقد بلغ الحساب حده اليومي ولا يفيد تقسيم السؤال، فأخبر المستخدم بذلك.'
)

LIBRARY_TOOLS_EN = (
    # The Arabic «لغة التفكير» bullet, first, for a model that would otherwise reason in English.
    '- Reasoning language: think in Arabic only. Write all of your internal reasoning (understanding the question, '
    'planning the searches, analysing the retrieved texts, building the answer) in Modern Standard Arabic, never in '
    'English or any other language; only law slugs (e.g. penal-code), tool names and argument values stay as they are. '
    'The answer is in Arabic.\n'
    '- The legal-library tools return the 22 Jordanian statutes named, with their slugs, in the Arabic library section '
    '(search_law and get_article take law="<slug>"; get_article defaults to civil-code) and the Civil Code explanatory '
    'memorandum (get_memorandum, paged). The Majalla (majalla) applies only where it does not conflict with the Civil '
    'Code (art. 1448): never cite it over the Civil Code. Judgments and other legislation are not loaded yet: say so '
    'rather than citing them from memory, and pass on the verification status each result carries.\n'
    # The Arabic library section's two budget bullets, for a model that reasons in English (Fable 5.2 review).
    f'- Each answer may receive at most {PER_ANSWER} library texts in all: one search_law call returns at most {PER_SEARCH} '
    'and counts what it returns; an article from get_article counts one, and so does each get_memorandum note. Plan the '
    f'searches before the first call; when you plan three, pass limit={THREE_SEARCH_LIMIT} to each so the third still '
    f'fits ({PLANNED_SPLIT}), and count any second phrasing among them. When a tool says the limit is reached, make no '
    'further library call in that answer; answer from the retrieved texts only; name, by subject and not by article '
    'number, each point left without a retrieved text; state for it no amount, period, deadline or competent court '
    "from memory, nor that it is left to the court's discretion, not even in a conditional analysis; and suggest asking "
    'each point separately. The same message marks '
    "the account's daily limit: if it comes before the answer has used its budget, splitting the question will not "
    'help, so say so.'
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
