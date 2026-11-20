// إنذار عدلي (source.pdf page 13). Fields and rules: warning-general.json.
#import "/lib/form.typ": *
#show: form.with([إنذار عدلي موجه بواسطة الكاتب العدل لدى محكمة \ #fill("notary_court", width: 9cm)])

اسم المنذر : #fill("warner_name", width: 7cm) #h(1fr) الرقم الوطني : #nn("warner_national_no") \
العنوان : #fill("warner_address") #h(0.6em) الهاتف : #fill("warner_phone", width: 4cm) \
وكيله إن وجد : #fill("agent_name") #h(0.6em) العنوان : #fill("agent_address") \
الهاتف : #fill("agent_phone", width: 5cm) \
اسم المنذر إليه : #fill("warned_name") #h(0.6em) العنوان : #fill("warned_address")

#v(1em)
*الوقائع :*
#para("facts", lines: 8)

#v(1.5em)
*لذا أنذركم بـ #fill("demand", width: 8.5cm) من تاريخ تبلغكم هذا الإنذار العدلي وخلاف ذلك فإنني سأكون مضطراً لاتخاذ الإجراءات القانونية اللازمة بحقكم ومنها إقامة #fill("action", width: 11cm)*

#v(2.5em)
#align(end, box(width: 8cm)[
  #align(center)[*المنذر*]
  الإسم: #fill("warner_name") \
  الرقم الوطني: #nn("warner_national_no") \
  العنوان : #fill("warner_address") \
  الهاتف : #fill("warner_phone") \
  التوقيع : #dots(1fr)
])
