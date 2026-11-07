// MongoDB's health check, which also sets up its authentication (O-34). Docker runs it inside the mongo container,
// over localhost, every few seconds:
//   mongosh --quiet --file /scripts/mongo-bootstrap.js
// It exits 0 only once this member is the replica set's primary and the three users exist, so LibreChat, which waits
// for a healthy mongo, never starts before it can sign in. Idempotent: on a volume already set up it only signs in and
// checks. The passwords are read from the secrets volume here, never from a command line.
//   iqraa_admin   root on admin: this script's own sign-in once the users exist
//   iqraa_app     readWrite on LibreChat: LibreChat and the staff bootstrap runner, through /secrets/mongo_uri
//   iqraa_reader  read on LibreChat: scripts/query.js and scripts/reconcile.js
// mongod runs with --keyFile, which turns authorization on. Until the first user exists, MongoDB's localhost exception
// lets this script initiate the replica set and create iqraa_admin, on an empty volume and on one that a release
// before O-34 wrote without authentication alike. MONGO_INITDB_* is not used: the image applies it to empty volumes
// only. A user that exists is never changed here: a password rotation or a role change is an operator's updateUser.
const fs = require('fs');

const secret = (name) => fs.readFileSync(`/secrets/${name}`, 'utf8').trim();
const admin = db.getSiblingDB('admin');
const librechat = db.getSiblingDB('LibreChat');
const USERS = [
  { user: 'iqraa_app', file: 'mongo_app_password', role: 'readWrite' },
  { user: 'iqraa_reader', file: 'mongo_reader_password', role: 'read' },
];

function signIn() {
  try {
    admin.auth('iqraa_admin', secret('mongo_admin_password'));
    return true;
  } catch (error) {
    return false;
  }
}

/** One pass; returns the reason the member is not ready yet, or null once it is. */
function bootstrap() {
  const authed = signIn();
  let status;
  try {
    status = rs.status();
  } catch (error) {
    if (error.codeName !== 'NotYetInitialized') throw error;
    rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: 'mongo:27017' }] });
    return 'replica set rs0 initiated, no primary yet';
  }
  // Just after its election a member reports PRIMARY while it still refuses writes.
  if (status.myState !== 1 || !db.hello().isWritablePrimary) return `member state ${status.myState}, not a writable primary yet`;
  if (!authed) {
    // Only possible while no user exists (the localhost exception); otherwise createUser is refused below.
    admin.createUser({ user: 'iqraa_admin', pwd: secret('mongo_admin_password'), roles: ['root'] });
    if (!signIn()) return 'iqraa_admin was created but cannot sign in';
  }
  for (const { user, file, role } of USERS) {
    if (librechat.getUser(user) === null) {
      librechat.createUser({ user, pwd: secret(file), roles: [{ role, db: 'LibreChat' }] });
    }
  }
  return null;
}

let reason;
try {
  reason = bootstrap();
} catch (error) {
  // An error code and message only: neither carries a password.
  reason = `${error.codeName ?? error.name}: ${error.message}`;
}
if (reason !== null) {
  print(`mongo not ready: ${reason}`);
  quit(1);
}
print('mongo ready: primary, iqraa_admin, iqraa_app and iqraa_reader exist');
