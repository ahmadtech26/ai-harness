// إنذار عدلي لعزل وكيل (source.pdf page 14). Fields and rules: warning-revoke-agent.json.
#import "/lib/form.typ": *
#show: form.with([إنذار عدلي لعزل وكيل موجه بواسطة الكاتب العدل لدى محكمة \ #fill("notary_court", width: 10cm)])

اسم المنذر : #fill("warner_name", width: 7cm) #h(1fr) الرقم الوطني : #nn("warner_national_no") \
العنوان : #fill("warner_address") #h(0.6em) الهاتف : #fill("warner_phone", width: 4cm) \
وكيله إن وجد : #fill("agent_name") #h(0.6em) العنوان : #fill("agent_address") \
الهاتف : #fill("agent_phone", width: 5cm) \
اسم المنذر إليه : #fill("warned_name") #h(0.6em) العنوان : #fill("warned_address")

#v(1.2em)
*الوقائع :* \
تعلم أنني بتاريخ #fill("poa_date", width: 3cm) م قد وكلتك وكالة #fill("poa_type", width: 4.5cm)، وحيث أنني قد ألغيت وكالتك ذات الرقم #fill("poa_number", width: 3cm) والصادرة من الكاتب العدل لدى محكمة #fill("poa_court", width: 5.5cm) بتاريخ #fill("poa_issue_date", width: 3cm) م، فإنني أخطرك بهذا العزل وعليك عدم استخدامها وبعكس ذلك سوف أحملك المسؤولية القانونية من تاريخ تبلغك هذا الإنذار .

#v(1fr)
#align(end, box(width: 8cm)[
  #align(center)[*المنذر*]
  الإسم: #fill("warner_name") \
  الرقم الوطني: #nn("warner_national_no") \
  العنوان : #fill("warner_address") \
  الهاتف : #fill("warner_phone") \
  التوقيع : #dots(1fr)
])
#v(1.5fr)
