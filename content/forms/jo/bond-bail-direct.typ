// سند كفالة نظم مباشرة (source.pdf page 18). Fields and rules: bond-bail-direct.json.
// The notary's paragraph (dates, «حضر لدي ... السيد ...») stays dotted: the notary writes it.
#import "/lib/form.typ": *
#show: form.with("سند كفالة نظم مباشرة")

#align(center)[*دائرة الكاتب العدل لدى محكمة* #fill("notary_court", width: 7cm)]

#v(1.2em)
في يوم #dots(2.6cm) الواقع #dots(2.6cm) من شهر #dots(2.6cm) سنة #dots(2.6cm) هجرية، الموافق لليوم #dots(2.6cm) من شهر #dots(2.6cm) لسنة #dots(2.6cm) ميلادية.

#v(0.8em)
حضر لدي أنا الكاتب العدل في محكمة #dots(4cm) السيد #dots(5cm) وطلب إلي أن أنظم عليه سنداً يتضمن ما هو آت :

#v(0.8em)
بما أنه تقرر تخلية سبيل #fill("released_name", width: 7cm) في القضية ذات الرقم #fill("case_number", width: 3cm) لدى #fill("case_court", width: 6.5cm) بكفالة عدلية وقدرها #fill("amount", width: 3cm) دينار ، تأميناً لحضوره في جميع الإجراءات التحقيقية وأدوار المحاكمة وعند تنفيذ الحكم فإنه يكفل المذكور ويتعهد بإحضاره عند كل طلب يصدر بحقه من الجهة المختصة في هذه القضية وعند تنفيذ الحكم وإن تأخر عن إحضاره يلتزم بدفع قيمة الكفالة المذكورة لخزينة الدولة بلا تعلل وبدون حاجة إلى إنذار أو محاكمة وبعكس ذلك يقبل بما يترتب عليه قانوناً، وعليه عقدت مجلساً للعدل ونظمت هذا السند وتلي عليه في المجلس علناً وتفهم مآله حرفياً وأقر بمضمونه ووافق على صحته تماماً ووقعه أمامي وبحضوري وعليه صار تسجيله والتوقيع عليه. \
فإنني أصادق على ملائته حسب الأصول.

#v(1fr)
#align(end, box(width: 8cm)[
  #align(center)[*الكفيل*]
  الإسم: #fill("guarantor_name") \
  الرقم الوطني: #nn("guarantor_national_no") \
  العنوان : #fill("guarantor_address") \
  الهاتف : #fill("guarantor_phone") \
  التوقيع : #dots(1fr)
])
#v(1.5fr)
