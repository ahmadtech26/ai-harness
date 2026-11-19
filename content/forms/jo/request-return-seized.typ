// طلب إعادة مضبوطات (source.pdf page 11). Fields and rules: request-return-seized.json.
#import "/lib/form.typ": *
#show: form.with("طلب إعادة مضبوطات")

#align(center)[
  *لدى محكمة* #fill("court", width: 5cm)
]

#v(1em)
اسم المستدعي : #fill("applicant_name", width: 6.2cm) #h(1fr) الرقم الوطني : #nn("applicant_national_no")

#v(1em)
أرجو التكرم بالموافقة والإيعاز لمن يلزم لإعادة المضبوطات العائدة لي بالقضية رقم #fill("case_number", width: 4cm) وهي على النحو التالي :

#v(0.6em)
// The rows are numbered on the page (١. to ٦.); lib/form.typ's list helper takes one mark for every row.
#let marks = ("١", "٢", "٣", "٤", "٥", "٦")
#pad(x: 0.6cm)[
  #if has("seized_items") {
    for (i, row) in val("seized_items").enumerate() { block(spacing: 0.55em)[#(marks.at(i)). #h(0.4em) #row] }
  } else {
    for m in marks { block(spacing: 0.55em)[#(m). #h(0.4em) #dots(1fr)] }
  }
]

#v(1.5em)
#align(center)[*وتفضلوا بقبول فائق الاحترام ،،،،*]

#v(5em)
إسم المستدعي : #fill("applicant_name", width: 6.2cm) \
التوقيع : #dots(5cm) \
التاريخ : #dots(5cm)
