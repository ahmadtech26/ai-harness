// وكالة خاصة غير قابلة للعزل (source.pdf page 22). Fields and rules: poa-irrevocable.json.
#import "/lib/form.typ": *
#show: form.with("وكالة خاصة غير قابلة للعزل")

*أنا الموقع أدناه:* \
*الإسم:* #fill("principal_name", width: 6.5cm) #h(1fr) *الرقم الوطني:* #nn("principal_national_no") \
#if not has("principal_name") [#h(1.3cm) #dots(6.5cm) \ #h(1.3cm) #dots(6.5cm) \ ]
*العنوان :* #fill("principal_address") #h(0.6em) *الهاتف :* #fill("principal_phone", width: 4.5cm) \
*أفوض السيد:* #fill("agent_name", width: 6.5cm) #h(1fr) *الرقم الوطني:* #nn("agent_national_no")

#v(0.4em)
#[
#set par(justify: true)
ليقوم مقام نفسي وينوب عني في بيع وفراغ ما مساحته #fill("area", width: 4cm) شقة رقم #fill("flat_number", width: 2cm)
في قطعة الارض رقم #fill("parcel_number", width: 2cm) من حوض رقم #fill("basin_number", width: 2cm) المسمى #fill("basin_name", width: 3.5cm)
لوحة رقم #fill("plate_number", width: 2cm) من القرية المسماه #fill("village", width: 3.5cm) من اراضي #fill("lands_of", width: 3.5cm)
لمن يشاء بالبدل والثمن الذي يراه مناسباً وأفوضه في البيع والهبة والرهن وفك الرهن والافراز والمبادلة في الحصص المذكورة أعلاه وضمها وتوحيدها
مع أية قطعة أخرى يراها مناسبة وأفوضه باستلام المخططات وسندات التسجيل الخاصة بهذه القطعة وله حق الاشراف والمناظره والإدارة وقبض الإيجارات
وفي إنشاء الأبنية عليها واستصدار التراخيص اللازمة لذلك وزراعتها والتوقيع على الإقرارات العدلية والتعهدات أمام كتاب العدل لغايات الإفراز والتوقيع
على نظام الجمعيات السكنية وله الحق بتوجيه الإنذارات العدلية وإقامة الدعاوى باختلاف أنواعها أمام جميع المحاكم باختلاف أنواعها ودرجاتها وتمثيلي
أمام كافة المحاكم، كما يحق له التوقيع على كل ما يلزم من الأوراق أمام دوائر الأراضي والمساحة وجميع الدوائر الرسمية وغير الرسمية في المملكة
الأردنية الهاشمية المتعلقة بهذا الخصوص، وكالة غير قابلة للعزل كوني قبضت الثمن كاملاً وفقاً لأحكام المادة ٨٦٣ من القانون المدني.
]

#v(1em)
#text(size: 14pt)[حررت بتاريخ: #fill("date", width: 3.5cm) م]

#v(0.6em)
#align(end, box(width: 8cm)[
  #align(center)[*الموكل*]
  الإسم: #fill("principal_name") \
  الرقم الوطني: #nn("principal_national_no") \
  العنوان : #fill("principal_address") \
  الهاتف : #fill("principal_phone") \
  التوقيع : #dots(1fr)
])
