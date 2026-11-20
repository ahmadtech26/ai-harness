// لائحة استئناف قضية تنفيذية (source.pdf page 1). Fields and rules: appeal-execution.json.
#import "/lib/form.typ": *
#show: form.with("لائحة استئناف قضية تنفيذية")

#align(center)[
  *لدى محكمة إستئناف* #fill("court", width: 5cm) \
  *بواسطة رئيس دائرة تنفيذ* #fill("execution_department", width: 4.5cm)
]

#v(1em)
إسم المستأنف: #fill("appellant_name", width: 6cm) #h(1fr) الرقم الوطني: #nn("appellant_national_no") \
العنوان: #fill("appellant_address") #h(0.6em) الهاتف: #fill("appellant_phone", width: 4cm) \
الوكيل إن وجد: #fill("agent_name") #h(0.6em) العنوان: #fill("agent_address") \
المستأنف ضده: #fill("respondent") \
*القرار المستأنف: القرار الصادر بالقضية التنفيذية رقم ( #fill("case_number", width: 1.6cm) / #fill("case_year", width: 1.2cm) ) لصالح المحكوم له والمتضمن* #fill("decision_contains")

#v(1.2em)
*مختصر الوقائع :*
#rect(width: 100%, inset: 9pt)[
  علمت بصدور القرار بالقضية وحيث أنني أجده واقعاً في غير محله فإنني أستأنف ضمن المده القانونية للأسباب التالية :
  #items("reasons", count: 6)
]

#v(1em)
*الطلب:* \
حسب ما تقدم وكما تراه المحكمة الموقره من أسباب ألتمس : \
١- قبول الاستئناف شكلاً لتقديمه ضمن المدة القانونية . \
٢- فسخ القرار المستأنف والسير بالقضية حسب الاصول . \
وإنني على استعداد لتقديم الكفالة التي ترونها مناسبة.

#v(1.5em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(1em)
إسم المستأنف : #fill("appellant_name", width: 5cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
