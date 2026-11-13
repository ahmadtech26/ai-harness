// The search terms skills and editions tell the model to pass to search_law (owner, 2026-11-13, «Noun phrases only»).
// A term is a statutory noun phrase: the words of the statute that name the issue («تعدد الكفلاء», «عدم سماع الدعوى»),
// never a proposition the model could repeat as a rule («الرهن لا يتجزا», «يفسر الشك في مصلحة المدين») and never an
// amount («ثلث التركة»). The tests reject a term that holds a negation, begins a clause (a negation, a condition or a
// relative pronoun), begins with a verb, or holds an amount.
//
// Arabic written without short vowels cannot always tell a verb from a noun (تصرف، تعدد، تحقق). So a first word read
// as an imperfect verb (ي…, or و/ف before ي…) counts as a verb unless NOUNS_LIKE_VERBS lists it, and VERBS lists the
// other verb forms found so far. A nominal sentence («الشرط باطل») begins with a noun and passes: a reviewer still reads
// each new term.

/** The normalisation the corpus-term tests use: short vowels, tatweel, hamza seats, final ى and ة. */
export const normalise = (text) =>
  text
    .replace(/[ً-ْـ]/g, '')
    .replace(/[إأآ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .replace(/ؤ/g, 'و')
    .replace(/ئ/g, 'ي')
    .replace(/ء/g, '')
    .replace(/\s+/g, ' ')
    .trim();

const NEGATIONS = new Set(['لا', 'ولا', 'فلا', 'لم', 'ولم', 'فلم', 'لن', 'ليس', 'ليست']);
const CLAUSE_STARTS = new Set(['ما', 'وما', 'فما', 'من', 'ومن', 'ممن', 'لمن', 'اذا', 'واذا', 'فاذا', 'ان', 'وان', 'فان', 'لو', 'ولو', 'كلما', 'متي', 'حيث', 'ايا']);
const NOUNS_LIKE_VERBS = new Set(['يد', 'يسار', 'يمين', 'يوم']);
const VERBS = new Set([
  'اوفي', 'وجب', 'وجبت', 'خرج', 'استوفي', 'انحصر', 'ضمن', 'لغا', 'اشترك', 'زاد', 'تجرد', 'اشترط', 'اوجبته', 'اقر', 'سقط',
  'سقطت', 'هلك', 'هلكت', 'فات', 'احاله', 'احاط', 'اعتبر', 'انتحر', 'تعذرت', 'صدر', 'تنشا', 'تنقطع', 'تنفسخ', 'تستحق', 'تفرق',
  'وتتم', 'تتم', 'جاز', 'كان', 'كانت', 'اصبح', 'تبين', 'وقع', 'لزم', 'انقضي', 'انفسخ', 'بطل', 'قام', 'تم',
]);
// Whole words only, after normalise: fractions, and cardinal numbers up to the thousands. «ثمن» (price) and «واحد»
// («مجلس واحد», a single session) are not listed.
const AMOUNT_WORDS = new Set([
  'نصف', 'ثلث', 'ثلثا', 'ثلثي', 'ربع', 'خمس', 'سدس', 'سبع', 'تسع', 'عشر', 'اثنان', 'اثنين', 'ثلاث', 'ثلاثه', 'اربع',
  'اربعه', 'خمسه', 'ست', 'سته', 'سبعه', 'ثماني', 'ثمانيه', 'تسعه', 'عشره', 'عشرين', 'ثلاثين', 'مايه', 'ميه', 'مييه', 'الف', 'الاف',
]);

/** Why a search term is not a statutory noun phrase, or null when it is one. */
export function termProblem(term) {
  const words = normalise(term).split(' ');
  const [first] = words;
  if (/[0-9٠-٩]/.test(term) || words.some((word) => AMOUNT_WORDS.has(word))) return 'it holds an amount';
  if (words.some((word) => NEGATIONS.has(word))) return 'it holds a negation';
  if (CLAUSE_STARTS.has(first)) return 'it begins a clause';
  const imperfect = /^(?:[وف])?ي/.test(first) && first.length > (/^[وف]ي/.test(first) ? 3 : 1);
  if ((imperfect && !NOUNS_LIKE_VERBS.has(first)) || VERBS.has(first)) return 'it begins with a verb';
  return null;
}
