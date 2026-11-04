// Daily ledger reconciliation (mongosh). Read-only; exits 1 when an invariant fails.
//   docker compose exec -T mongo mongosh LibreChat --quiet --file /scripts/reconcile.js
// Optional env: RECONCILE_HOURS (window for the spend summary, default 24),
//               RECONCILE_STALE_MS (a held reservation this far past expiry is a problem, default 5 min).
const hours = Number(process.env.RECONCILE_HOURS || 24);
const staleMs = Number(process.env.RECONCILE_STALE_MS || 5 * 60 * 1000);
const since = new Date(Date.now() - hours * 3600 * 1000);
const problems = [];
const warnings = [];

// 1. Double entry: every transaction and the whole book sum to zero.
const unbalancedTx = db.iqraa_postings
  .aggregate([
    { $group: { _id: '$txId', total: { $sum: '$amount' } } },
    { $match: { total: { $ne: 0 } } },
    { $limit: 20 },
  ])
  .toArray();
for (const tx of unbalancedTx) problems.push(`transaction ${tx._id} sums to ${tx.total}`);

const accounts = db.iqraa_postings
  .aggregate([{ $group: { _id: '$account', total: { $sum: '$amount' } } }])
  .toArray();
const posted = {};
let book = 0;
for (const row of accounts) {
  // $sum answers a Long once an account passes 32 bits (the grants do), and adding that to a number joins them as text.
  const total = Number(row.total);
  posted[row._id] = total;
  book += total;
}
if (book !== 0) problems.push(`postings sum to ${book}, not 0`);

// 2. Wallet projections equal their posted balances; negative balances are overspend.
const wallets = db.iqraa_wallets.find({}).toArray();
for (const w of wallets) {
  const available = posted[`user:${w.userId}:available`] || 0;
  const held = posted[`user:${w.userId}:held`] || 0;
  if (available !== w.available || held !== w.held) {
    problems.push(`wallet ${w.userId} ${w.available}/${w.held} != postings ${available}/${held}`);
  }
  if (w.available < 0) warnings.push(`wallet ${w.userId} overspent: available ${w.available}`);
  if (w.held < 0) problems.push(`wallet ${w.userId} has negative held ${w.held}`);
}

// 3. Reservations and usage events agree one-to-one.
const reservations = db.iqraa_reservations.find({}).toArray();
const events = db.iqraa_usage_events.find({}).toArray();
const eventByKey = {};
for (const e of events) eventByKey[e.key] = e;
const reservationByKey = {};
const heldTotal = {};
for (const r of reservations) {
  reservationByKey[r.key] = r;
  const event = eventByKey[r.key];
  if (r.status === 'settled') {
    if (!event) problems.push(`settled reservation ${r.key} has no usage event`);
    else if (event.amount !== r.actualAmount) {
      problems.push(`reservation ${r.key} settled ${r.actualAmount} but usage event says ${event.amount}`);
    }
  } else if (event) {
    problems.push(`${r.status} reservation ${r.key} has a usage event`);
  }
  if (r.status === 'held') {
    heldTotal[r.userId] = (heldTotal[r.userId] || 0) + r.amount;
    if (r.expiresAt.getTime() + staleMs < Date.now()) {
      problems.push(`reservation ${r.key} held ${Math.round((Date.now() - r.expiresAt.getTime()) / 1000)}s past expiry`);
    }
  }
}
for (const e of events) {
  if (!reservationByKey[e.key]) problems.push(`usage event ${e.key} has no reservation`);
}
for (const w of wallets) {
  if ((heldTotal[w.userId] || 0) !== w.held) {
    problems.push(`wallet ${w.userId} held ${w.held} != open reservations ${heldTotal[w.userId] || 0}`);
  }
}

// 4. Each reservation's postings match its status.
const kindsByTx = {};
for (const p of db.iqraa_postings.find({ kind: { $ne: 'grant' } }, { txId: 1 }).toArray()) {
  kindsByTx[p.txId] = true;
}
for (const r of reservations) {
  if (!kindsByTx[`reserve:${r.key}`]) problems.push(`reservation ${r.key} has no reserve postings`);
  if (r.status === 'settled' && !kindsByTx[`settle:${r.key}`]) problems.push(`reservation ${r.key} has no settle postings`);
  if (r.status === 'released' && !kindsByTx[`release:${r.key}`]) problems.push(`reservation ${r.key} has no release postings`);
  if (r.status !== 'settled' && kindsByTx[`settle:${r.key}`]) problems.push(`${r.status} reservation ${r.key} has settle postings`);
}

// 5. Window summary: spend, estimated settlements (provider sent no usage), releases.
const windowEvents = events.filter((e) => e.createdAt >= since);
const estimated = windowEvents.filter((e) => e.estimated);
const summary = {
  since: since.toISOString(),
  usageEvents: windowEvents.length,
  spentMicroAic: windowEvents.reduce((acc, e) => acc + e.amount, 0),
  estimatedSettlements: estimated.length,
  releasedReservations: reservations.filter((r) => r.status === 'released' && r.updatedAt >= since).length,
  openReservations: reservations.filter((r) => r.status === 'held').length,
  wallets: wallets.length,
};
if (estimated.length > 0) warnings.push(`${estimated.length} settlement(s) in the window used the estimate (no provider usage)`);

print(JSON.stringify({ ok: problems.length === 0, problems, warnings, summary }));
if (problems.length > 0) quit(1);
