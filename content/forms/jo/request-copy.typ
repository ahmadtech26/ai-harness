// طلب تصوير (source.pdf page 9). Fields and rules: request-copy.json.
#import "/lib/form.typ": *
#show: form.with("طلب تصوير")

#align(center)[
  *لدى محكمة* #fill("court", width: 5cm)
]

#v(1em)
اسم المستدعي : #fill("applicant_name", width: 6.2cm) #h(1fr) الرقم الوطني : #nn("applicant_national_no") \
وكيله إن وجد : #fill("agent_name", width: 6.2cm) #h(1fr) الرقم الوطني : #nn("agent_national_no")

#v(1em)
أرجو التكرم بالموافقة والإيعاز لمن يلزم بإعطائي صورة عن #fill("copy_of", width: 9cm) في الدعوى ذات الرقم #fill("case_number", width: 4cm)

#pad(x: 0.6cm)[
  #chosen("case_status", "المنظورة") المنظورة لدى هيئة القاضي #fill("judge", width: 3.5cm) وموعد الجلسة القادمة #fill("next_session", width: 3.5cm) \
  #chosen("case_status", "المفصولة") المفصولة بتاريخ #fill("decided_on", width: 4cm)
]

#v(1em)
وذلك للأسباب التالية :

#v(0.6em)
#pad(x: 1cm)[#items("reasons", count: 6)]

#v(1.5em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(3em)
إسم المستدعي : #fill("applicant_name", width: 6.2cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
