// لائحة شكوى (شيك) (source.pdf page 15). Fields and rules: complaint-cheque.json.
#import "/lib/form.typ": *
#show: form.with("لائحة شكوى (شيك)")

#align(center)[*لدى محكمة* #fill("court", width: 6cm)]

#v(0.8em)
اسم المشتكي: #fill("complainant_name", width: 6cm) #h(1fr) الرقم الوطني : #nn("complainant_national_no") \
العنوان : #fill("complainant_address") #h(0.6em) الهاتف : #fill("complainant_phone", width: 4cm) \
وكيله إن وجد : #fill("agent_name") #h(0.6em) العنوان : #fill("agent_address") \
اسم المشتكى عليه: #fill("accused_name") #h(0.6em) العنوان : #fill("accused_address")

#v(0.8em)
*الموضوع : إصدار شيك بدون رصيد خلافاً لأحكام المادة رقم (٤٢١) من قانون العقوبات*

#v(0.8em)
*الوقائع :*
#grid(
  columns: (auto, 1fr),
  column-gutter: 0.6em,
  row-gutter: 0.7em,
  [١-], para("fact_1", lines: 3),
  [٢-], para("fact_2", lines: 3),
  [٣-], [إن عمل المشتكى عليه هذا يشكل جرماً جزائياً معاقب عليه قانوناً.],
)

#v(1em)
*الطلب :* \
ألتمس تبليغ المشتكى عليه لائحة الشكوى ومرفقاتها وموعد الجلسة والتحقيق معه وبالنتيجة الحكم عليه بالعقوبة المقررة ، محتفظاً بحقي في إقامة دعوى الحق الشخصي والمطالبة بقيمة الشيك.

#v(1.2em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(1em)
#align(end, box(width: 8cm)[
  اسم المشتكي : #fill("complainant_name") \
  التاريخ : #dots(1fr) \
  التوقيع : #dots(1fr)
])
