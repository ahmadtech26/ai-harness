// لائحة شكوى جزائية (source.pdf page 16). Fields and rules: complaint-criminal.json.
#import "/lib/form.typ": *
#show: form.with("لائحة شكوى جزائية")

#align(center)[*لدى محكمة* #fill("court", width: 6cm)]

#v(0.8em)
اسم المشتكي: #fill("complainant_name", width: 6cm) #h(1fr) الرقم الوطني : #nn("complainant_national_no") \
العنوان : #fill("complainant_address") #h(0.6em) الهاتف : #fill("complainant_phone", width: 4cm) \
وكيله إن وجد : #fill("agent_name") #h(0.6em) العنوان : #fill("agent_address") \
اسم المشتكى عليه: #fill("accused_1_name") #h(0.6em) العنوان : #fill("accused_1_address") \
#h(2.6cm) #fill("accused_2_name", width: 6cm) #h(1fr) #fill("accused_2_address", width: 6cm)

#v(0.8em)
*الموضوع :* #fill("subject")

#v(1em)
*الوقائع :*
#para("facts", lines: 5)

#v(1em)
*الطلب :* \
ألتمس تبليغ المشتكى عليه لائحة الشكوى ومرفقاتها وموعد الجلسة والتحقيق معه وبالنتيجة الحكم عليه بالعقوبة المقررة، محتفظاً بحقي في إقامة دعوى الحق الشخصي والمطالبة بالتعويض.

#v(1.2em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(1em)
#align(end, box(width: 8cm)[
  اسم المشتكي : #fill("complainant_name") \
  التاريخ : #dots(1fr) \
  التوقيع : #dots(1fr)
])
