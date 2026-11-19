// استبدال الحبس بالغرامة (source.pdf page 10). Fields and rules: request-fine-substitution.json.
#import "/lib/form.typ": *
#show: form.with("استبدال الحبس بالغرامة")

#align(center)[
  *لدى محكمة* #fill("court", width: 5cm)
]

#v(1em)
اسم المستدعي : #fill("applicant_name") \
الموضوع #h(0.5em) : استبدال الحبس بالغرامة في الدعوى #fill("case_number", width: 6cm)

#v(1em)
حيث أنه قد صدر قرار المحكمة الموقرة بحقي في الدعوى رقم #fill("case_number", width: 3cm) فصل #fill("decision_date", width: 3cm) والتي موضوعها #fill("subject", width: 9cm) \
يتضمن الحكم بالحبس مدة #fill("prison_term", width: 4cm) \
فإنني ألتمس التكرم بالموافقة على استبدال عقوبة الحبس المحكوم بها بالغرامة، وإنني على استعداد لدفعها في صندوق المحكمة في حال تفضلتم بالموافقة على ذلك.

#v(2em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(5em)
إسم المستدعي : #fill("applicant_name", width: 8cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
