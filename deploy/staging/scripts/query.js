// mongosh helper for the scenario driver (read-only). The request arrives base64-encoded in IQRAA_QUERY so no
// shell quoting is involved:  {op:'find', collection, filter, sort?, limit?}  {op:'indexes', collection}
// Prints one JSON line. Roles change only through LibreChat's guarded routes and the staff bootstrap runner
// (spec-passwordless-login «Spec review» item 5), never through a raw update here.
// It signs in first as iqraa_reader (read on LibreChat, O-34), so the database itself keeps it read-only; the password
// is read from the secrets volume inside the mongo container, never from a command line.
db.auth('iqraa_reader', require('fs').readFileSync('/secrets/mongo_reader_password', 'utf8').trim());
const query = JSON.parse(Buffer.from(process.env.IQRAA_QUERY || '', 'base64').toString('utf8'));
let result;
if (query.op === 'find') {
  result = db
    .getCollection(query.collection)
    .find(query.filter || {})
    .sort(query.sort || { _id: 1 })
    .limit(query.limit || 0)
    .toArray();
} else if (query.op === 'indexes') {
  result = db.getCollection(query.collection).getIndexes();
} else {
  result = { error: 'unknown op' };
}
print(JSON.stringify(result));
