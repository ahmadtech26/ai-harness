// The 22 laws of corpus v1: the library the AQEL editions up to 1.3.1 name («22 تشريعًا» and these slugs). The
// registry (corpus/laws.json) gained 12 draft laws on 2026-11-20; the editions written before are frozen texts, so their
// tests pin this list rather than the live registry, and an edition that names the new laws is tested against the
// registry itself.
export const CORPUS_V1_SLUGS = [
  'civil-code', 'majalla', 'landlords-tenants', 'penal-code', 'commerce', 'maritime-commerce', 'companies', 'customs',
  'income-tax', 'sales-tax', 'labour', 'investment-fund', 'civil-procedure', 'evidence', 'execution', 'mediation',
  'criminal-procedure', 'courts-formation', 'magistrates-courts', 'major-felonies-court', 'court-fees', 'bar-association',
];

/** The registry entries of corpus v1, in registry order; throws if one is missing, so a law dropped from the registry
 * still fails the tests of the editions that name it. */
export function corpusV1Laws(laws) {
  const found = laws.filter((law) => CORPUS_V1_SLUGS.includes(law.slug));
  const missing = CORPUS_V1_SLUGS.filter((slug) => !found.some((law) => law.slug === slug));
  if (missing.length) throw new Error(`corpus v1 laws missing from the registry: ${missing.join(', ')}`);
  return found;
}
