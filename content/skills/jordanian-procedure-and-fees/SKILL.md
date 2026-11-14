---
name: jordanian-procedure-and-fees
description: Jordanian court fees and civil procedure from library articles — fee computation from the court-fees schedule, competent court, filing documents, answer and appeal deadlines, and execution steps. Use for fee, deadline, court or execution questions.
metadata:
  version: "1.2.0"
  owner: iqraa-legal-content
  requires:
    tools: [search_law, get_article]
  review:
    status: draft
    note: "1.2.0 adds practice notes (references/, PN ids) on civil procedure, execution and the fee schedule, distilled from law-firm practice pages and each tied to the corpus articles it names; internal source records under docs/distillation: draft, for lawyer review"
---

# احتساب رسوم المحاكم الأردنية وإجراءات التقاضي المدني

منهج لاحتساب رسم إقامة الدعوى أو الطعن أو التنفيذ أو الطلب من «جدول رسوم المحاكم» في المكتبة القانونية، ولتحديد المحكمة المختصة ومستندات الدعوى ومواعيد الجواب والطعن وخطوات التنفيذ. الأرقام والمواعيد تؤخذ من النص المسترجع وحده.

## متى يُستخدم
- السؤال عن مقدار رسم دعوى أو طعن أو تنفيذ أو طلب أمام المحاكم الأردنية.
- السؤال عن المحكمة المختصة، أو مستندات رفع الدعوى، أو مواعيد الجواب والطعن، أو خطوات التنفيذ في الدعاوى المدنية.

## خطوات العمل
1. **الوقائع اللازمة**: نوع الإجراء، المحكمة (صلح، بداية، استئناف، تمييز، تنفيذ)، وقيمة الدعوى إن كانت قابلة للتقدير. اسأل عما ينقص قبل الحساب.
2. **النص المنطبق**: استرجع المادة من جدول رسوم المحاكم بـ `get_article` مع `law="court-fees"` إن عرفت رقمها، وإلا فبـ `search_law` بعبارة تصف الإجراء. لتحديد البند المنطبق استعن بـ `skills/jordanian-procedure-and-fees/references/court-fees-map.md`. انقل النص حرفيًا مع حالة التحقق التي تعيدها الأداة.
3. **الحساب**: طبّق النسب والشرائح والحدين الأدنى والأعلى الواردة في النص المسترجع، خطوة خطوة، وأظهر العملية بالأرقام.
4. **الإضافات والإعفاءات**: اذكر ما ينص عليه الجدول من رسوم إضافية أو إعفاءات إن انطبقت، مع مادتها.
5. **التنبيه**: الجدول في المكتبة غير متحقق من مطابقته للجريدة الرسمية ما لم تذكر الأداة غير ذلك، والرسم النهائي تقدّره المحكمة.

## الإجراءات والمواعيد
- للمحكمة المختصة ورفع الدعوى والحضور والطلبات المستعجلة والطعن ونزاعات العمل الفردية: `skills/jordanian-procedure-and-fees/references/civil-litigation.md`.
- للسند التنفيذي وطلب التنفيذ والحبس والحجز والبيع: `skills/jordanian-procedure-and-fees/references/execution.md`.
- كل سطر فيهما يسمّي المواد التي تقول ما فيه: استرجع منها بـ `get_article` ما يلزم المسألة الحاسمة قبل أن تبني عليه، ولا تنقل من السطر نفسه مدة أو مقدارًا أو حكمًا.

## قواعد
- لا تعطِ رقمًا لم تسترجع مادته؛ إن لم تجد المادة فصرّح بذلك.
- مواعيد الطعن وإجراءات التقاضي المدنية في قانون أصول المحاكمات المدنية المحمّل في المكتبة: استرجعها بـ `search_law` مع `law="civil-procedure"` بعبارة تصف الإجراء، أو بـ `get_article` مع `law="civil-procedure"` إن عرفت رقم المادة، وانقل النص حرفيًا مع حالة التحقق. لا تذكر موعدًا أو إجراءً إلا مما أعادته المكتبة في هذه المحادثة؛ فإن لم تجده فصرّح بذلك.
