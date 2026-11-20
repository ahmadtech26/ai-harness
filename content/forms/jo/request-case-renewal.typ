// طلب تجديد دعوى (source.pdf page 17). Fields and rules: request-case-renewal.json.
#import "/lib/form.typ": *
#show: form.with("طلب تجديد دعوى")

#align(center)[*لدى محكمة* #fill("court", width: 6cm)]

#v(1.2em)
المستدعي : #fill("applicant_name", width: 12cm) \
وكيله إن وجد : #fill("agent_name", width: 12cm)

#v(1.2em)
*الموضوع :* طلب تجديد الدعوى الصلحية الحقوقية رقم #fill("case_number", width: 3.8cm)

#v(1.2em)
حيث تم إسقاط الدعوى #fill("dropped_case_type", width: 4.8cm) رقم #fill("dropped_case_number", width: 3cm) بتاريخ #fill("dropped_date", width: 3cm)، لذا ألتمس الإيعاز لمن يلزم بتجديد الدعوى أعلاه وتحديد موعد لرؤيتها والنظر بها من النقطة التي وصلت إليها.

#v(1.2em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(2em)
#align(end, box(width: 8cm)[
  اسم المستدعي : #fill("applicant_name") \
  التاريخ : #dots(1fr) \
  التوقيع : #dots(1fr)
])

#v(1fr)
#rect(width: 100%, inset: 10pt)[
  #underline[*تعبأ بعد قيد الدعوى :*] \
  اسم الهيئة الحاكمة: #dots(9cm) \
  تفهمت موعد الجلسة الواقع يوم #dots(2cm) تاريخ #dots(2cm) الساعة #dots(2.2cm) \
  اسم المستدعي أو وكيله : #dots(5cm) \
  التوقيع : #dots(5cm)
]
#v(1fr)
