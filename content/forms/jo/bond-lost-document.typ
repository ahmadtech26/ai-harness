// سند كفالة عدلية (source.pdf page 6). Fields and rules: bond-lost-document.json.
#import "/lib/form.typ": *
#show: form.with("سند كفالة عدلية")

// On paper the word that does not apply in «فقد / أتلف» and «فاقد / تالف» is struck by hand; here it is struck
// once the user has chosen. With no choice both words print as on the page.
#let pick(option, word) = if has("condition") and val("condition") != option { strike(word) } else { word }

#v(2em)
#pad(x: 1cm)[
  حيث أن المدعو #h(0.5em) #fill("person_name") \
  قد #pick("فاقد")[فقد] / #pick("تالف")[أتلف] ( #fill("document", width: 5cm) ) وتقدم بطلب بدل #pick("فاقد")[فاقد] / #pick("تالف")[تالف] فعليه أنا \
  الكفيل الموقع أدناه #h(0.5em) #fill("guarantor_name") \
  أكفل المذكور بأن يحافظ على هذه الوثيقة من الضياع أو التلف وبعكس ذلك أكون ملتزماً بدفع قيمة الكفالة البالغة ( #fill("amount", width: 3cm) ) ديناراً لخزينة الدولة دون الحاجة إلى إنذار أو إخطار عدلي .
]

#v(12em)
#align(end, block(width: 9cm)[
  #set align(start)
  #align(center)[*الكفيل*]
  #v(0.2em)
  الإسم :#fill("guarantor_name") \
  الرقم الوطني :#nn("guarantor_national_no") \
  العنوان :#fill("guarantor_address") \
  الهاتف :#fill("guarantor_phone") \
  التوقيع :#dots(1fr)
])
