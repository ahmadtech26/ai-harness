// mongosh helper for the scenario driver. The request arrives base64-encoded in IQRAA_QUERY so no
// shell quoting is involved:  {op:'find', collection, filter, sort?}  {op:'promote', email}  {op:'indexes', collection}
// Prints one JSON line.
const query = JSON.parse(Buffer.from(process.env.IQRAA_QUERY || '', 'base64').toString('utf8'));
let result;
if (query.op === 'find') {
  result = db
    .getCollection(query.collection)
    .find(query.filter || {})
    .sort(query.sort || { _id: 1 })
    .toArray();
} else if (query.op === 'promote') {
  result = db.users.updateOne({ email: query.email }, { $set: { role: 'ADMIN' } }).modifiedCount;
} else if (query.op === 'indexes') {
  result = db.getCollection(query.collection).getIndexes();
} else {
  result = { error: 'unknown op' };
}
print(JSON.stringify(result));
