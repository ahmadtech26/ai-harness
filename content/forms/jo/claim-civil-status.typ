// لائحة دعوى أحوال مدنية (source.pdf page 5). Fields and rules: claim-civil-status.json.
#import "/lib/form.typ": *
#show: form.with("لائحة دعوى أحوال مدنية")
// The page is dense: tighter lines than the shared default keep it on one A4 page.
#set par(leading: 0.45em, spacing: 0.5em)

#align(center)[
  *لدى محكمة صلح حقوق* #fill("court", width: 5cm)
]

#v(0.2em)
المدعي : #fill("plaintiff_name", width: 7cm) #h(1fr) الرقم الوطني : #nn("plaintiff_national_no") \
العنوان : #fill("plaintiff_address") \
الوكيل إن وجد: #fill("agent_name", width: 6cm) #h(0.6em) العنوان: #fill("agent_address") \
المدعى عليه / عليهم :
#pad(right: 0.6cm)[
  ١- مدير عام دائرة الأحوال المدنية والجوازات بالإضافة لوظيفته . \
  ٢- أمين السجل المدني بالإضافة لوظيفته \
  ٣- #fill("defendant_3", width: 9cm)
]
موضوع الدعوى :
#para("subject", lines: 3)

#v(0.15em)
*وقائع الدعوى :*
#para("facts", lines: 7)

#v(0.15em)
*الطلب :* \
#pad(right: 0.3cm)[
  ١- تبليغ المدعى عليه/ عليهم نسخ من لائحة الدعوى وتعيين موعد الجلسة. \
  ٢- غب المحاكمة والثبوت الحكم بإلزام المدعى عليه/ عليهم بـ
  #pad(right: 1em)[#para("requested_judgment", lines: 1)]
  #h(1em) وتضمينه/ تضمينهم الرسوم والمصاريف #fill("request_extra", width: 4cm)
]

#v(0.15em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(0.15em)
اسم المدعي : #fill("plaintiff_name", width: 7cm) \
التاريخ : #dots(5cm) \
التوقيع : #dots(5cm)

#v(0.1em)
#rect(width: 100%, inset: 6pt)[
  #underline[*تعبأ بعد قيد الدعوى :*] \
  اسم الهيئة الحاكمة:#dots(7cm) \
  تفهمت موعد الجلسة الواقع يوم #dots(1.5cm) تاريخ #dots(1.5cm) الساعة #dots(2cm) \
  اسم المستدعي أو وكيله : #dots(4cm) \
  التوقيع : #dots(4cm)
]
