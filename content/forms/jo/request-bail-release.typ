// طلب إخلاء سبيل بالكفالة (source.pdf page 8). Fields and rules: request-bail-release.json.
#import "/lib/form.typ": *
#show: form.with("طلب إخلاء سبيل بالكفالة")

#align(center)[
  *لدى محكمة* #fill("court", width: 5cm)
]

#v(1em)
*اسم الموقوف :* #fill("detainee_name") \
*إسم المستدعي:* #fill("applicant_name")

#v(1em)
رقم القضية: #fill("case_number", width: 5cm) \
لقد تم توقيف المذكور أعلاه من قبل محكمتكم الموقرة في القضية أعلاه والتي موضوعها #fill("subject", width: 11cm) ، وحيث أن التوقيف يلحق ضرراً بالمذكور أعلاه للأسباب التالية:

#v(0.6em)
#pad(x: 1cm)[#items("reasons", count: 6)]

#v(0.6em)
فإنني ألتمس التكرم بالموافقة على إخلاء سبيل الموقوف بالكفالة التي ترونها مناسبة، وإنه على استعداد لتقديم كفيل يضمن حضوره في جميع أدوار المحاكمة.

#v(1.5em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(1em)
إسم المستدعي : #fill("applicant_name", width: 8cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
