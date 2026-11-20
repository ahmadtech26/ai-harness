// لائحة استئناف حكم جزائي (source.pdf page 7). Fields and rules: appeal-criminal.json.
#import "/lib/form.typ": *
#show: form.with("لائحة استئناف حكم جزائي")

#align(center)[
  *لدى محكمة*#fill("court", width: 5cm)
]

#v(1em)
إسم المستأنف : #fill("appellant_name", width: 6.2cm) #h(1fr) الرقم الوطني : #nn("appellant_national_no") \
العنوان : #fill("appellant_address") \
وكيله إن وجد : #fill("agent_name", width: 5cm) #h(0.6em) العنوان : #fill("agent_address") \
المستأنف عليه : الحق العام \
القرار المستأنف : #fill("decision")

#v(1em)
*موجز الوقائع:*
#para("facts", lines: 3)

#v(0.6em)
وبما أنني أجد القرار واقعاً في غير محله، لذا بادرت بالاستئناف عليه ضمن المدة القانونية للأسباب التالية :
#pad(x: 1cm)[#items("reasons", count: 5)]

#v(1em)
*الطلب :* \
#pad(right: 0.6cm)[
  ١- ألتمس من محكمتكم الموقرة قبول الاستئناف شكلاً لتقديمه ضمن المدة القانونية . \
  ٢- فسخ القرار المستأنف والحكم
  #pad(right: 0.6cm)[#para("requested_judgment", lines: 2)]
]

#v(1.5em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(2em)
إسم المستأنف : #fill("appellant_name", width: 6.2cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
