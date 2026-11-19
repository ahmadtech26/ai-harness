// إنذار عدلي خاص بإخلاء مأجور (source.pdf page 12). Fields and rules: warning-eviction.json.
// The court line sits inside the page's title box, as printed.
#import "/lib/form.typ": *
#show: form.with([إنذار عدلي خاص بإخلاء مأجور موجه بواسطة الكاتب العدل \ لدى محكمة #fill("notary_court", width: 7cm)])

اسم المنذر : #fill("warner_name", width: 6.5cm) #h(1fr) الرقم الوطني : #nn("warner_national_no") \
العنوان : #fill("warner_address") #h(0.6em) الهاتف : #fill("warner_phone", width: 4cm) \
وكيله إن وجد : #fill("agent_name", width: 5cm) #h(0.6em) العنوان : #fill("agent_address") \
الهاتف : #fill("agent_phone", width: 6cm)

اسم المنذر إليه : #fill("warned_name", width: 6cm) #h(0.6em) العنوان : #fill("warned_address")

#v(0.6em)
*الوقائع :*
#grid(
  columns: (auto, 1fr),
  column-gutter: 0.5em,
  row-gutter: 0.7em,
  [١-], [يعلم المنذر إليه بأنه يشغل عن طريق الإجارة العقار العائد للمنذر والكائن في #fill("property_location", width: 10cm) بأجرة #fill("rent", width: 4cm)],
  [٢-], [يعلم المنذر إليه بأنه تخلف عن دفع أجرة #fill("unpaid_period", width: 3.5cm) والبالغة #fill("unpaid_amount", width: 3.6cm) دينار بالإضافة إلى كافة الضرائب والنفقات المستحقة عليه.],
  [٣-], [رغم المطالبة الودية المتكررة من المنذر للمنذر إليه، إلا أنه يرفض دفع المبلغ المترصد بذمته بدل أجور والبالغة قيمته #fill("total_amount", width: 3.6cm)دينار.],
  [٤-], para("point_4", lines: 2),
)

#v(0.8em)
*لذا أنذركم بدفع المبلغ المذكور أعلاه وذلك خلال* #fill("deadline", width: 3cm) *من تاريخ تبلغكم هذا الإنذارالعدلي وخلاف ذلك فإنني سأكون مضطراً لاتخاذ الإجراءات القانونية اللازمة بحقكم ومنها إقامة دعاوى الإخلاء أو الفسخ وتضمينكم الرسوم والنفقات.*

#v(2em)
#align(end, block(width: 9cm)[
  #set align(start)
  #align(center)[*المنذر*]
  #v(0.2em)
  الإسم: #fill("warner_name") \
  الرقم الوطني: #nn("warner_national_no") \
  العنوان : #fill("warner_address") \
  الهاتف : #fill("warner_phone") \
  التوقيع : #dots(1fr)
])
