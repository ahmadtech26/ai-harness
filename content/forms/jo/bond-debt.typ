// سند دين (source.pdf page 3). Fields and rules: bond-debt.json.
// The dates and the notary's own blanks («حضر لدي أنا …», «الكاتب العدل في محكمة …») are completed at the notary.
#import "/lib/form.typ": *
#show: form.with("سند دين")

*دائرة الكاتب العدل لدى محكمة* #fill("notary_court", width: 6cm)

#v(1em)
في يوم #dots(2.2cm) الواقع في#dots(2.2cm) من شهر#dots(2.2cm) سنة #dots(2.2cm) هجرية، الموافق لليوم#dots(2.2cm) من شهر#dots(2.2cm) لسنة #dots(2.2cm) ميلادية.

#v(1em)
حضر لدي أنا#dots(4cm) الكاتب العدل في محكمة #dots(3cm) السيد #fill("debtor_name", width: 7.5cm) وطلب إلي أن أنظم عليه سنداً يتضمن ما هو آت :

#v(1em)
أنه يقر ويعترف أن بذمته مبلغ وقدره #fill("amount", width: 6cm) لدائنه #fill("creditor", width: 7.5cm) سببه #fill("cause", width: 8cm) وأن يتعهد بدفع المبلغ المذكور غب مرور #fill("due_period", width: 3.5cm) من تاريخه لأمر دائنه المذكور أو لأمر من يحيله إليه من الأشخاص بلا تعلل وبدون حاجة إلى حكم من المحكمة ، وإذا تأخر عن الدفع يتحمل العطل والضرر والمصاريف القانونية ، فعليه عقدت مجلسا للعدل ونظمت هذا السند بذاتي وتلوته على المدين المومأ إليه وفهمته مآله حرفياً فأقر بمضمونه ووافق على صحة مندرجاته تماماً ووقعه أمامي وبحضوري وعليه صار تسجيله وتصديقه حسب الأصول .

#v(6em)
#align(end, block(width: 9cm)[
  #set align(start)
  #align(center)[*المدين*]
  #v(0.2em)
  الإسم :#fill("debtor_name") \
  الرقم الوطني :#nn("debtor_national_no") \
  العنوان :#fill("debtor_address") \
  الهاتف :#fill("debtor_phone") \
  التوقيع :#dots(1fr)
])
