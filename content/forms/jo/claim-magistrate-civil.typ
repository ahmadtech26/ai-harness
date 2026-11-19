// لائحة دعوى صلحية حقوقية (source.pdf page 4). Fields and rules: claim-magistrate-civil.json.
#import "/lib/form.typ": *
#show: form.with("لائحة دعوى صلحية حقوقية")
// The page is dense: tighter lines than the shared default keep it on one A4 page.
#set par(leading: 0.45em, spacing: 0.5em)

#align(center)[
  *لدى محكمة صلح حقوق* #fill("court", width: 5cm)
]

#v(0.3em)
المدعي : #fill("plaintiff_name", width: 7cm) #h(1fr) الرقم الوطني : #nn("plaintiff_national_no") \
العنوان : #fill("plaintiff_address") \
الوكيل إن وجد: #fill("agent_name", width: 6cm) #h(0.6em) العنوان: #fill("agent_address") \
المدعى عليه / عليهم :

#grid(
  columns: (1fr, 1fr),
  column-gutter: 1.5cm,
  row-gutter: 0.35em,
  align(center, underline[*الإسم*]), align(center, underline[*العنوان*]),
  fill("defendant_1_name", width: 100%), fill("defendant_1_address", width: 100%),
  fill("defendant_2_name", width: 100%), fill("defendant_2_address", width: 100%),
  fill("defendant_3_name", width: 100%), fill("defendant_3_address", width: 100%),
  fill("defendant_4_name", width: 100%), fill("defendant_4_address", width: 100%),
)

#v(0.4em)
موضوع الدعوى : #fill("subject") \
قيمة الدعوى : #fill("claim_value") \
*وقائع الدعوى :*
#para("facts", lines: 9)

#v(0.3em)
*الطلب :* \
#pad(right: 0.3cm)[
  ١- تبليغ المدعى عليه نسخة من لائحة الدعوى وتعيين موعد الجلسة ودعوته للمحاكمة . \
  ٢- غب المحاكمة والثبوت الحكم للمدعي بالمبلغ المدعى به مع الرسوم و المصاريف و #fill("request_extra", width: 3.3cm)
]

#v(0.3em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(0.3em)
اسم المدعي : #fill("plaintiff_name", width: 7cm) \
التاريخ : #dots(5cm) \
التوقيع : #dots(5cm)

#v(0.2em)
#rect(width: 100%, inset: 6pt)[
  #underline[*تعبأ بعد قيد الدعوى :*] \
  اسم الهيئة الحاكمة:#dots(7cm) \
  تفهمت موعد الجلسة الواقع يوم #dots(1.5cm) تاريخ #dots(1.5cm) الساعة #dots(2cm) \
  اسم المستدعي أو وكيله : #dots(4cm) \
  التوقيع : #dots(4cm)
]
