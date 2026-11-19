// وكالة خاصة (source.pdf page 20). Fields and rules: poa-special.json.
// The page has no signature block: only «حررت بتاريخ».
#import "/lib/form.typ": *
#show: form.with("وكالة خاصة")

*أنا الموقع أدناه:* \
*الإسم:* #fill("principal_name", width: 6.5cm) #h(1fr) *الرقم الوطني:* #nn("principal_national_no") \
#if not has("principal_name") [#h(1.3cm) #dots(6.5cm) \ #h(1.3cm) #dots(6.5cm) \ ]
*العنوان :* #fill("principal_address") #h(0.6em) *الهاتف :* #fill("principal_phone", width: 4.5cm)

#v(1em)
قد وكلت وأقمت مقام نفسي وعوضاً عن ذاتي وشخصي السيد #fill("agent_name", width: 6cm) الرقم~الوطني #fill("agent_national_no", width: 3.5cm) لينوب عني في
#para("powers", lines: 8)
وله الحق في التوقيع عني على كافة الأوراق والمعاملات المتعلقة بهذا الخصوص ومراجعة جميع الدوائر الرسمية ذات الاختصاص .

#v(1.5em)
#text(size: 14pt)[حررت بتاريخ: #fill("date", width: 3.5cm) م]
