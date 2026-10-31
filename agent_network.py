"""Private agent coordination. No model execution; authority comes from owner grants."""
import hashlib
import json
import re
import os
import secrets
import time
import threading
from contextlib import closing, nullcontext, contextmanager
from dataclasses import dataclass
from network_storage import WebDAVStorage, StorageError

KINDS = ('message', 'file.list', 'file.read')
MAX_FILE = 32 * 1024 * 1024
MAX_STORAGE = 256 * 1024 * 1024
LEASE_SECONDS = 300
PRESENCE_SECONDS = 90
ID = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,47}$')


class NetworkError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def require(ok, message, code=400):
    if not ok:
        raise NetworkError(code, message)


def stamp():
    return int(time.time())


def text(value, name, limit=1000, empty=False):
    require(isinstance(value, str) and len(value) <= limit and (empty or bool(value)), f'invalid {name}')
    require(not any(ord(c) < 32 for c in value) if name != 'message' else '\x00' not in value, f'invalid {name}')
    return value


def identifier(value):
    require(isinstance(value, str) and ID.fullmatch(value), 'invalid identifier')
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, f'expected integer {low}..{high}')
    return value


def relative_path(value, directory=False):
    text(value, 'path', 1024, empty=directory)
    require(not value.startswith('/') and '\\' not in value and ':' not in value, 'relative path required')
    require(value == '' or all(p not in ('', '.', '..') and not p.startswith('.') for p in value.split('/')),
            'hidden files and path traversal are not allowed')
    return value


def migrate_v7(con):
    if con.execute('PRAGMA user_version').fetchone()[0] >= 7:
        return
    con.executescript('''
    BEGIN IMMEDIATE;
    CREATE TABLE network_agents(
      id TEXT PRIMARY KEY, device TEXT NOT NULL, label TEXT NOT NULL,
      token_hash TEXT NOT NULL UNIQUE, capabilities TEXT NOT NULL,
      revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
    CREATE TABLE network_sessions(
      agent TEXT NOT NULL REFERENCES network_agents(id), id TEXT NOT NULL,
      capabilities TEXT NOT NULL, state TEXT NOT NULL, last_seen INTEGER NOT NULL,
      PRIMARY KEY(agent,id));
    CREATE TABLE network_grants(
      source TEXT NOT NULL REFERENCES network_agents(id), requester TEXT NOT NULL REFERENCES network_agents(id),
      kind TEXT NOT NULL, share TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
      PRIMARY KEY(source,requester,kind,share));
    CREATE TABLE network_requests(
      id TEXT PRIMARY KEY, sender TEXT NOT NULL REFERENCES network_agents(id),
      recipient TEXT NOT NULL REFERENCES network_agents(id), kind TEXT NOT NULL, share TEXT NOT NULL,
      payload TEXT NOT NULL, idempotency_key TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
      session TEXT NOT NULL DEFAULT '', lease TEXT NOT NULL DEFAULT '', lease_until INTEGER NOT NULL DEFAULT 0,
      attempts INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT NOT NULL DEFAULT '',
      UNIQUE(sender,idempotency_key));
    CREATE INDEX network_requests_recipient ON network_requests(recipient,status,created_at);
    CREATE TABLE network_artifacts(
      request_id TEXT PRIMARY KEY REFERENCES network_requests(id) ON DELETE CASCADE,
      sha256 TEXT NOT NULL, size INTEGER NOT NULL, expires_at INTEGER NOT NULL, object_key TEXT NOT NULL UNIQUE);
    CREATE TABLE network_storage_gc(object_key TEXT PRIMARY KEY, not_before INTEGER NOT NULL);
    CREATE TABLE network_audit(
      id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL);
    PRAGMA user_version=7;
    COMMIT;
    ''')


def migrate(con):
    migrate_v7(con)
    if con.execute('PRAGMA user_version').fetchone()[0] < 8:
        con.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE network_devices(
          id TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'other');
        INSERT INTO network_devices(id,label,kind)
          SELECT DISTINCT device,device,CASE
            WHEN device='pc' OR device LIKE 'pc-%' THEN 'pc'
            WHEN device='vps' OR device LIKE 'vps-%' THEN 'vps'
            WHEN device='cloud' OR device LIKE 'cloud-%' THEN 'cloud'
            ELSE 'other' END FROM network_agents;
        CREATE INDEX network_audit_target ON network_audit(target,ts);
        PRAGMA user_version=8;
        COMMIT;
        """)


def device_kind(device):
    return next((kind for kind in ('pc', 'vps', 'cloud')
                 if device == kind or device.startswith(kind + '-')), 'other')


def display_name(value):
    value = text(text(value, 'display name', 100).strip(), 'display name', 100)
    require(not any(127 <= ord(c) <= 159 for c in value), 'invalid display name')
    return value


def audit(con, actor, action, target):
    con.execute('INSERT INTO network_audit(ts,actor,action,target) VALUES(?,?,?,?)', (stamp(), actor, action, target))


def enroll(con, body):
    device = identifier(body.get('device'))
    name = identifier(body.get('name'))
    aid = device + '/' + name
    label = text(body.get('label', aid), 'label', 100)
    caps = body.get('capabilities', [])
    require(isinstance(caps, list) and len(caps) <= len(KINDS) and all(c in KINDS for c in caps), 'invalid capabilities')
    require(con.execute('SELECT COUNT(*) FROM network_agents').fetchone()[0] < 100, 'agent limit reached', 429)
    require(not con.execute('SELECT 1 FROM network_agents WHERE id=?', (aid,)).fetchone(), 'agent already enrolled', 409)
    token = 'pn_' + secrets.token_urlsafe(32)
    con.execute('INSERT INTO network_agents(id,device,label,token_hash,capabilities,created_at) VALUES(?,?,?,?,?,?)',
                (aid, device, label, hashlib.sha256(token.encode()).hexdigest(), json.dumps(sorted(set(caps))), stamp()))
    con.execute('INSERT OR IGNORE INTO network_devices(id,label,kind) VALUES(?,?,?)',
                (device, device, device_kind(device)))
    audit(con, 'owner', 'enroll', aid)
    return {'id': aid, 'token': token}


def grant(con, body, delete=False):
    source, requester, kind = body.get('source'), body.get('requester'), body.get('kind')
    require(kind in KINDS, 'invalid kind')
    share = identifier(body.get('share')) if kind.startswith('file.') else ''
    for aid in (source, requester):
        require(isinstance(aid, str) and con.execute('SELECT 1 FROM network_agents WHERE id=? AND revoked=0', (aid,)).fetchone(),
                'active agent required', 404)
    if not delete:
        capabilities=json.loads(con.execute('SELECT capabilities FROM network_agents WHERE id=?',(source,)).fetchone()[0])
        require(kind in capabilities,'source is not enrolled for this capability')
    args = (source, requester, kind, share)
    if delete:
        con.execute('DELETE FROM network_grants WHERE source=? AND requester=? AND kind=? AND share=?', args)
        con.execute("UPDATE network_requests SET status='cancelled',lease='' WHERE recipient=? AND sender=? AND kind=? AND share=? AND status IN ('queued','leased','interrupted')", args)
        delete_artifacts(con, 'request_id IN (SELECT id FROM network_requests WHERE recipient=? AND sender=? AND kind=? AND share=?)', args)
    else:
        con.execute('INSERT OR IGNORE INTO network_grants VALUES(?,?,?,?,?)', (*args, stamp()))
    audit(con, 'owner', 'revoke-grant' if delete else 'grant', f'{source}:{kind}:{share}->{requester}')
    return {'ok': True}


def revoke(con, aid):
    require(con.execute('SELECT 1 FROM network_agents WHERE id=?', (aid,)).fetchone(), 'agent not found', 404)
    con.execute('UPDATE network_agents SET revoked=1 WHERE id=?', (aid,))
    con.execute('DELETE FROM network_sessions WHERE agent=?', (aid,))
    con.execute("UPDATE network_requests SET status='cancelled',lease='' WHERE (sender=? OR recipient=?) AND status IN ('queued','leased','interrupted')", (aid, aid))
    delete_artifacts(con, 'request_id IN (SELECT id FROM network_requests WHERE sender=? OR recipient=?)', (aid, aid))
    audit(con, 'owner', 'revoke-agent', aid)
    return {'ok': True}


def delete_artifacts(con, where, args=()):
    con.execute("INSERT OR IGNORE INTO network_storage_gc SELECT object_key,0 FROM network_artifacts WHERE " + where, args)
    con.execute("DELETE FROM network_artifacts WHERE " + where, args)


def cleanup(con):
    t = stamp()
    delete_artifacts(con, 'expires_at>0 AND expires_at<=?', (t,))
    con.execute("UPDATE network_requests SET status='expired',lease='' WHERE status IN ('queued','leased','interrupted') AND expires_at<=?", (t,))
    con.execute("UPDATE network_requests SET status=CASE WHEN kind='message' THEN 'interrupted' WHEN attempts>=5 THEN 'failed' ELSE 'queued' END,lease='' WHERE status='leased' AND lease_until<=?", (t,))
    con.execute('DELETE FROM network_sessions WHERE last_seen<?', (t - 7 * 86400,))
    con.execute('DELETE FROM network_requests WHERE expires_at<? AND NOT EXISTS (SELECT 1 FROM network_artifacts a WHERE a.request_id=network_requests.id)', (t - 30 * 86400,))
    con.execute('DELETE FROM network_audit WHERE ts<?', (t - 30 * 86400,))


def permitted(con, row):
    return con.execute('''SELECT 1 FROM network_grants g
      JOIN network_agents a ON a.id=g.source JOIN network_agents b ON b.id=g.requester
      WHERE g.source=? AND g.requester=? AND g.kind=? AND g.share=? AND a.revoked=0 AND b.revoked=0''',
      (row['recipient'], row['sender'], row['kind'], row['share'])).fetchone() is not None


def request_out(con, row):
    result = {k: row[k] for k in ('id','sender','recipient','kind','share','status','created_at','expires_at','attempts','error','lease_until')}
    result['payload'] = json.loads(row['payload'])
    result['result'] = json.loads(row['result']) if row['result'] else None
    a = con.execute('SELECT sha256,size,expires_at FROM network_artifacts WHERE request_id=?', (row['id'],)).fetchone()
    result['artifact'] = dict(a) if a else None
    times = con.execute('''SELECT MAX(ts) AS updated_at,
      MAX(CASE WHEN action='claim' THEN ts END) AS started_at,
      MAX(CASE WHEN action IN ('complete','failed') THEN ts END) AS finished_at
      FROM network_audit WHERE target=?''', (row['id'],)).fetchone()
    result.update(dict(times))
    result['updated_at'] = max(result['updated_at'] or 0, row['created_at'])
    return result


def artifact_access(con, row, actor, owner=False):
    return owner or actor==row["recipient"] or permitted(con,{"recipient":row["recipient"],"sender":actor,"kind":"file.read","share":row["share"]})


def get_request(con, rid, actor, owner=False, artifact=False):
    row = con.execute('SELECT * FROM network_requests WHERE id=?', (rid,)).fetchone()
    require(row and (artifact_access(con,row,actor,owner) if artifact else owner or actor in (row['sender'], row['recipient'])), 'request not found', 404)
    return row


def create_request(con, actor, b):
    recipient, kind = b.get('recipient'), b.get('kind')
    require(isinstance(recipient, str) and kind in KINDS, 'invalid recipient or kind')
    share = identifier(b.get('share')) if kind.startswith('file.') else ''
    payload = b.get('payload', {})
    require(isinstance(payload, dict), 'payload must be an object')
    if kind == 'message':
        payload = {'message': text(payload.get('message'), 'message', 8000)}
    else:
        payload = {'path': relative_path(payload.get('path', ''), directory=kind == 'file.list')}
    key = text(b.get('idempotency_key'), 'idempotency_key', 100)
    ttl = integer(b.get('ttl_seconds', 86400), 60, 7 * 86400)
    encoded = json.dumps(payload, sort_keys=True)
    r = {'recipient': recipient, 'sender': actor, 'kind': kind, 'share': share}
    require(permitted(con, r), 'no owner grant for this request', 403)
    target=con.execute('SELECT capabilities FROM network_agents WHERE id=?',(recipient,)).fetchone()
    require(target and kind in json.loads(target[0]), 'recipient does not have this capability', 409)
    old = con.execute('SELECT * FROM network_requests WHERE sender=? AND idempotency_key=?', (actor, key)).fetchone()
    if old:
        require(all(old[k] == v for k, v in r.items()) and old['payload'] == encoded, 'idempotency key already used for another request', 409)
        return request_out(con, old)
    require(con.execute("SELECT COUNT(*) FROM network_requests WHERE sender=? AND status IN ('queued','leased','interrupted')", (actor,)).fetchone()[0] < 100, 'pending request limit reached', 429)
    require(con.execute('SELECT COUNT(*) FROM network_requests').fetchone()[0] < 10000, 'request storage limit reached', 429)
    rid = secrets.token_hex(16)
    con.execute('INSERT INTO network_requests(id,sender,recipient,kind,share,payload,idempotency_key,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (rid, actor, recipient, kind, share, encoded, key, stamp(), stamp() + ttl))
    audit(con, actor, 'request', rid)
    return request_out(con, get_request(con, rid, actor))


def heartbeat(con, actor, b):
    sid = identifier(b.get('session_id'))
    caps = b.get('capabilities', [])
    allowed = json.loads(con.execute('SELECT capabilities FROM network_agents WHERE id=?', (actor,)).fetchone()[0])
    require(isinstance(caps, list) and len(caps) <= len(KINDS) and all(c in allowed for c in caps), 'capability not enrolled', 403)
    state = b.get('state', 'ready')
    require(state in ('ready', 'busy', 'offline'), 'invalid state')
    count = con.execute('SELECT COUNT(*) FROM network_sessions WHERE agent=? AND last_seen>? AND id!=?', (actor, stamp()-PRESENCE_SECONDS, sid)).fetchone()[0]
    require(count < 16, 'session limit reached', 429)
    con.execute('INSERT INTO network_sessions VALUES(?,?,?,?,?) ON CONFLICT(agent,id) DO UPDATE SET capabilities=excluded.capabilities,state=excluded.state,last_seen=excluded.last_seen',
                (actor, sid, json.dumps(caps), state, stamp()))
    return {'agent': actor, 'session_id': sid, 'presence_seconds': PRESENCE_SECONDS}


def claim(con, actor, b):
    sid = identifier(b.get('session_id'))
    s = con.execute("SELECT * FROM network_sessions WHERE agent=? AND id=? AND state='ready' AND last_seen>?", (actor, sid, stamp()-PRESENCE_SECONDS)).fetchone()
    require(s, 'heartbeat a ready session before claiming', 409)
    require(not con.execute("SELECT 1 FROM network_requests WHERE recipient=? AND session=? AND status='leased'", (actor, sid)).fetchone(), 'session already has a leased request', 409)
    caps = json.loads(s['capabilities'])
    rows = con.execute("SELECT * FROM network_requests WHERE recipient=? AND status='queued' ORDER BY created_at,id LIMIT 100", (actor,)).fetchall()
    for row in rows:
        if row['kind'] not in caps or not permitted(con, row):
            continue
        lease = secrets.token_urlsafe(24)
        con.execute("UPDATE network_requests SET status='leased',session=?,lease=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                    (sid, lease, min(stamp()+LEASE_SECONDS, row['expires_at']), row['id']))
        audit(con, actor, 'claim', row['id'])
        out = request_out(con, get_request(con, row['id'], actor))
        out.update(lease=lease, session_id=sid)
        return out
    return None


def check_lease(con, row, actor, session, lease):
    require(row['recipient'] == actor and row['session'] == session and isinstance(lease, str)
            and bool(row['lease']) and secrets.compare_digest(row['lease'], lease), 'lease does not belong to this session', 403)
    require(row['status'] == 'leased' and row['lease_until'] > stamp() and row['expires_at'] > stamp(), 'lease no longer active', 409)
    require(permitted(con, row), 'grant revoked', 403)


@dataclass
class Binary:
    data: bytes
    sha256: str


def dispatch(con, h, method, parts, actor, owner, body, upload, downloaded, artifact_ttl):
    if parts == ['artifacts'] and method == 'GET':
        rows=con.execute('SELECT r.*,a.sha256,a.size,a.expires_at AS artifact_expires_at FROM network_artifacts a JOIN network_requests r ON r.id=a.request_id ORDER BY r.created_at DESC LIMIT 10000')
        items=[]
        for row in rows:
            if artifact_access(con,row,actor,owner):
                items.append({'id':row['id'],'source':row['recipient'],'share':row['share'],'path':json.loads(row['payload'])['path'],
                              'size':row['size'],'sha256':row['sha256'],'expires_at':row['artifact_expires_at']})
                if len(items)>=200:break
        return items
    if parts == ['devices'] and method == 'GET':
        return [dict(r) for r in con.execute('SELECT id,label,kind FROM network_devices ORDER BY label,id')]
    if len(parts) == 2 and parts[0] == 'devices' and method == 'POST':
        require(owner, 'owner only', 403)
        device = identifier(parts[1])
        require(con.execute('SELECT 1 FROM network_devices WHERE id=?', (device,)).fetchone(), 'device not found', 404)
        label = display_name(body.get('label'))
        kind = body.get('kind')
        require(kind in ('pc', 'vps', 'cloud', 'other'), 'invalid device type')
        con.execute('UPDATE network_devices SET label=?,kind=? WHERE id=?', (label, kind, device))
        audit(con, actor, 'rename-device', device)
        return {'id': device, 'label': label, 'kind': kind}
    if parts == ['agents', 'label'] and method == 'POST':
        require(owner, 'owner only', 403)
        aid = text(body.get('agent'), 'agent', 100)
        require(con.execute('SELECT 1 FROM network_agents WHERE id=?', (aid,)).fetchone(), 'agent not found', 404)
        label = display_name(body.get('label'))
        con.execute('UPDATE network_agents SET label=? WHERE id=?', (label, aid))
        audit(con, actor, 'rename-agent', aid)
        return {'id': aid, 'label': label}
    if parts == ['agents'] and method == 'GET':
        agents = []
        for r in con.execute('SELECT id,device,label,capabilities,revoked FROM network_agents ORDER BY device,id'):
            item = dict(r)
            item['capabilities'] = json.loads(item['capabilities'])
            sessions = [dict(s) for s in con.execute('SELECT id,capabilities,state,last_seen FROM network_sessions WHERE agent=? ORDER BY last_seen DESC LIMIT 16', (r['id'],))]
            for s in sessions:
                s['capabilities'] = json.loads(s['capabilities'])
                if s['last_seen'] <= stamp()-PRESENCE_SECONDS:
                    s['state'] = 'offline'
            item['sessions'] = sessions
            live = [s for s in sessions if s['state'] != 'offline']
            leased = con.execute("SELECT session FROM network_requests WHERE recipient=? AND status='leased' AND lease_until>?",
                                 (r['id'], stamp())).fetchall()
            working = any(s['state'] == 'busy' for s in live) or any(
                row['session'] == s['id'] for row in leased for s in live)
            item['status'] = 'revoked' if r['revoked'] else 'busy' if working else 'ready' if live else 'offline'
            item['last_seen'] = max((s['last_seen'] for s in sessions), default=None)
            live_caps = {cap for s in live for cap in s['capabilities']}
            item['activity'] = ('working' if working else 'idle' if 'message' in live_caps
                                else 'files-only' if live_caps else 'connected') if live else 'offline'
            if r['revoked']:
                item['activity'] = 'revoked'
            agents.append(item)
        return agents
    if parts == ['agents'] and method == 'POST':
        require(owner, 'owner only', 403)
        return enroll(con, body)
    if parts == ['revoke'] and method == 'POST':
        require(owner, 'owner only', 403)
        return revoke(con, text(body.get('agent'), 'agent', 100))
    if parts == ['grants']:
        if method == 'GET':
            return [dict(r) for r in con.execute('SELECT * FROM network_grants' + ('' if owner else ' WHERE requester=? OR source=?'), () if owner else (actor,actor))]
        if method in ('POST','DELETE'):
            require(owner, 'owner only', 403)
            return grant(con, body, delete=method=='DELETE')
    if parts == ['audit'] and method == 'GET':
        require(owner, 'owner only', 403)
        return [dict(r) for r in con.execute('SELECT * FROM network_audit ORDER BY id DESC LIMIT 200')]
    if parts == ['heartbeat'] and method == 'POST':
        require(not owner, 'agent credential required', 403)
        return heartbeat(con, actor, body)
    if parts == ['claim'] and method == 'POST':
        require(not owner, 'agent credential required', 403)
        return claim(con, actor, body)
    if parts == ['requests']:
        if method == 'POST':
            require(not owner, 'agent credential required', 403)
            return create_request(con, actor, body)
        if method == 'GET':
            rows = con.execute('SELECT * FROM network_requests' + ('' if owner else ' WHERE sender=? OR recipient=?') + ' ORDER BY created_at DESC,id DESC LIMIT 200', () if owner else (actor,actor))
            return [request_out(con, r) for r in rows]
    if len(parts) in (2,3) and parts[0]=='requests':
        row = get_request(con, parts[1], actor, owner, artifact=parts[2:]==['artifact'] and method=='GET')
        if len(parts)==2 and method=='GET':
            return request_out(con, row)
        action = parts[2] if len(parts)==3 else ''
        if action=='cancel' and method=='POST':
            require(owner or actor in (row['sender'],row['recipient']), 'participant or owner only', 403)
            con.execute("UPDATE network_requests SET status='cancelled',lease='' WHERE id=?", (row['id'],))
            delete_artifacts(con, 'request_id=?', (row['id'],))
            audit(con, actor, 'cancel', row['id'])
            return {'ok': True}
        if action=='retry' and method=='POST':
            require(owner or actor==row['sender'], 'sender or owner only', 403)
            require(row['status']=='interrupted' and row['expires_at']>stamp() and row['attempts']<5, 'request cannot be retried', 409)
            require(body.get('reconciled') is True, 'confirm prior execution has been reconciled')
            require(permitted(con, row), 'grant revoked', 403)
            con.execute("UPDATE network_requests SET status='queued',lease='' WHERE id=?", (row['id'],))
            audit(con, actor, 'retry-reconciled', row['id'])
            return {'ok': True}
        if action=='renew' and method=='POST':
            check_lease(con,row,actor,body.get('session_id'),body.get('lease'))
            con.execute('UPDATE network_requests SET lease_until=? WHERE id=?',(min(stamp()+LEASE_SECONDS,row['expires_at']),row['id']))
            return request_out(con,get_request(con,row['id'],actor))
        if action=='artifact' and method=='GET':
            require(owner or permitted(con, row), 'grant revoked', 403)
            a = con.execute('SELECT * FROM network_artifacts WHERE request_id=? AND (expires_at=0 OR expires_at>?)', (row['id'],stamp())).fetchone()
            require(a and row['status']=='completed', 'artifact unavailable or expired', 404)
            audit(con, actor, 'download', row['id'])
            require(downloaded and downloaded[0]==a['object_key'], 'artifact changed during download', 409)
            return Binary(downloaded[1], a['sha256'])
        if action in ('complete','artifact') and method=='POST':
            session = h.headers.get('X-Pulse-Session') if action=='artifact' else body.get('session_id')
            lease = h.headers.get('X-Pulse-Lease') if action=='artifact' else body.get('lease')
            # A lost success response may be retried with the same lease. A
            # different result must never silently replace the first result.
            if row['status']=='completed' and row['recipient']==actor and row['session']==session and row['lease']==lease and permitted(con,row):
                if action=='artifact':
                    a = con.execute('SELECT sha256 FROM network_artifacts WHERE request_id=?', (row['id'],)).fetchone()
                    require(a and a[0]==hashlib.sha256(upload).hexdigest(), 'different or expired artifact', 409)
                else:
                    require(json.loads(row['result'])==body.get('result'), 'different completion result', 409)
                return request_out(con,row)
            check_lease(con,row,actor,session,lease)
            if action=='artifact':
                require(row['kind']=='file.read', 'file.read request required')
                digest = hashlib.sha256(upload).hexdigest()
                require(h.headers.get('X-Content-SHA256')==digest, 'checksum mismatch')
                used = con.execute('SELECT COALESCE(SUM(size),0) FROM network_artifacts').fetchone()[0]
                require(used+len(upload)<=MAX_STORAGE, 'artifact storage quota exceeded', 429)
                key = row['id'] + '-' + digest
                con.execute('INSERT INTO network_artifacts VALUES(?,?,?,?,?)', (row['id'],digest,len(upload),stamp()+artifact_ttl if artifact_ttl else 0,key))
                con.execute('DELETE FROM network_storage_gc WHERE object_key=?', (key,))
                result = {'sha256':digest,'size':len(upload)}
            else:
                result = body.get('result')
                require(isinstance(result,dict) and len(json.dumps(result))<=32000, 'invalid result')
                require(row['kind']!='file.read' or body.get('error'), 'file.read must upload an artifact')
            error = text(body.get('error',''), 'error', 300, empty=True)
            con.execute('UPDATE network_requests SET status=?,result=?,error=? WHERE id=?',
                        ('failed' if error else 'completed',json.dumps(result),error,row['id']))
            audit(con,actor,'failed' if error else 'complete',row['id'])
            return request_out(con,get_request(con,row['id'],actor))
    raise NetworkError(404,'network route not found')


NETWORK_SLOTS = threading.BoundedSemaphore(8)
TRANSFER_SLOTS = threading.BoundedSemaphore(2)
@contextmanager
def storage_guard(server):
    """Serialize uploads and GC, including the separate local-admin process."""
    if os.name!='posix':
        raise StorageError('artifact storage currently requires POSIX file locking')
    import fcntl
    path=server.DB_PATH.resolve().with_name('.network-storage.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        deadline=time.monotonic()+15
        while True:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:
                    raise StorageError('storage busy; retry later')
                time.sleep(.05)
        yield
    finally:
        os.close(fd)



def handle(h, method, path, server):
    if not NETWORK_SLOTS.acquire(blocking=False):
        h.close_connection = True
        return h.send_json(503, {"error":"network busy; retry later"})
    transfer=path.endswith('/artifact') or '/network/artifacts/' in path
    acquired=not transfer or TRANSFER_SLOTS.acquire(blocking=False)
    try:
        if not acquired:
            h.close_connection=True
            return h.send_json(503, {'error':'file transfers busy; retry later'})
        return _handle(h, method, path, server)
    finally:
        if transfer and acquired:
            TRANSFER_SLOTS.release()
        NETWORK_SLOTS.release()


def _handle(h, method, path, server):
    """Separate authentication boundary: ordinary Pulse bearers cannot enter."""
    try:
        require(server.CONFIG.get('agent_network', {}).get('enabled') is True, 'agent network is disabled', 404)
        h.connection.settimeout(30)
        token = h.headers.get('Authorization','')
        owner = not bool(token)
        if owner:
            role, actor = h.identity()
            require(role=='user', 'owner login or network token required', 403)
            actor='owner'
        else:
            require(token.startswith('Bearer pn_') and len(token)<200, 'network token required', 401)
            digest = hashlib.sha256(token[7:].encode()).hexdigest()
            with closing(server.db()) as con:
                a = con.execute('SELECT id FROM network_agents WHERE token_hash=? AND revoked=0',(digest,)).fetchone()
            require(a, 'invalid or revoked network token', 401)
            actor=a['id']
        if method!='GET' and owner:
            origin=h.headers.get('Origin')
            allowed={server.CONFIG.get('public_url','').rstrip('/'), 'http://'+h.headers.get('Host',''), 'https://'+h.headers.get('Host','')}
            require(not origin or origin in allowed, 'cross-origin mutation rejected', 403)
        parts=path.split('/')[3:]
        if method=='GET' and len(parts)==2 and parts[0]=='artifacts':
            parts=['requests',parts[1],'artifact']
        is_upload=method=='POST' and len(parts)==3 and parts[0]=='requests' and parts[2]=='artifact'
        body,upload={},None
        if method!='GET':
            require(not h.headers.get('Transfer-Encoding'), 'chunked bodies are unsupported', 400)
            length=h.headers.get('Content-Length','0')
            require(length.isdigit(), 'invalid content length')
            size=int(length)
            require(size<=(MAX_FILE if is_upload else 65536), 'body too large', 413)
            if is_upload:
                require(not owner,'agent credential required',403)
                # Check destination/lease before accepting a potentially large body.
                with closing(server.db()) as con:
                    row=get_request(con,parts[1],actor)
                    require(row['kind']=='file.read', 'file.read request required')
                    if row['status']!='completed':
                        check_lease(con,row,actor,h.headers.get('X-Pulse-Session'),h.headers.get('X-Pulse-Lease'))
                    else:
                        require(row['recipient']==actor and row['session']==h.headers.get('X-Pulse-Session') and row['lease']==h.headers.get('X-Pulse-Lease'), 'invalid retry lease',403)
                upload=h.rfile.read(size)
                require(len(upload)==size,'incomplete upload')
                require(h.headers.get('X-Content-SHA256')==hashlib.sha256(upload).hexdigest(), 'checksum mismatch')
            else:
                require(h.headers.get('Content-Type','').split(';')[0]=='application/json','JSON content type required',415)
                raw=h.rfile.read(size)
                require(len(raw)==size,'incomplete body')
                try:
                    body=json.loads(raw or b'{}')
                except ValueError:
                    raise NetworkError(400,'invalid JSON')
                require(isinstance(body,dict),'JSON object required')
        network_config=server.CONFIG.get('agent_network',{})
        storage_config=network_config.get('storage',{})
        artifact_ttl=integer(network_config.get('artifact_ttl_seconds',86400),0,30*86400)
        downloaded=None
        if method=='GET' and len(parts)==3 and parts[0]=='requests' and parts[2]=='artifact':
            with closing(server.db()) as con:
                row=get_request(con,parts[1],actor,owner,artifact=True)
                require(owner or permitted(con,row), 'grant revoked',403)
                a=con.execute('SELECT * FROM network_artifacts WHERE request_id=? AND (expires_at=0 OR expires_at>?)',(row['id'],stamp())).fetchone()
                require(a and row['status']=='completed','artifact unavailable or expired',404)
            data=WebDAVStorage(storage_config).get(a['object_key'],a['size'])
            require(data is not None and len(data)==a['size'] and hashlib.sha256(data).hexdigest()==a['sha256'], 'artifact missing or corrupt in storage',502)
            downloaded=(a['object_key'],data)
        # External storage I/O must never hold Pulse's SQLite write lock.
        # The storage file lock also coordinates a separate admin cleanup process.
        with storage_guard(server) if is_upload else nullcontext():
            if is_upload:
                key=parts[1]+'-'+hashlib.sha256(upload).hexdigest()
                require(re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{64}',key), 'invalid artifact id')
                with closing(server.db()) as con, con:
                    row=get_request(con,parts[1],actor)
                    require(permitted(con,row),'grant revoked',403)
                    existing=con.execute('SELECT sha256 FROM network_artifacts WHERE request_id=?',(row['id'],)).fetchone()
                    if row['status']=='completed':
                        require(existing and existing[0]==hashlib.sha256(upload).hexdigest(),'different or expired artifact',409)
                    else:
                        check_lease(con,row,actor,h.headers.get('X-Pulse-Session'),h.headers.get('X-Pulse-Lease'))
                        used=con.execute('SELECT COALESCE(SUM(size),0) FROM network_artifacts').fetchone()[0]
                        require(used+len(upload)<=MAX_STORAGE,'artifact storage quota exceeded',429)
                    con.execute('INSERT INTO network_storage_gc VALUES(?,?) ON CONFLICT(object_key) DO UPDATE SET not_before=excluded.not_before',(key,stamp()+3600))
                WebDAVStorage(storage_config).put(key,upload)
            with closing(server.db()) as con, con:
                con.execute('BEGIN IMMEDIATE')
                # Recheck identity and grant after potentially slow storage I/O.
                if not owner:
                    require(con.execute('SELECT 1 FROM network_agents WHERE id=? AND token_hash=? AND revoked=0',(actor,digest)).fetchone(), 'credential revoked',401)
                cleanup(con)
                out=dispatch(con,h,method,parts,actor,owner,body,upload,downloaded,artifact_ttl)
        if isinstance(out,Binary):
            h.send_response(200)
            for k,v in {'Content-Type':'application/octet-stream','Content-Length':str(len(out.data)),
                        'Content-Disposition':'attachment; filename="artifact.bin"','X-Content-SHA256':out.sha256,
                        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                        'Content-Security-Policy':"default-src 'none'; sandbox"}.items():
                h.send_header(k,v)
            h.end_headers()
            h.wfile.write(out.data)
        else:
            h.send_json(200,out)
    except StorageError as e:
        h.close_connection=True
        h.send_json(503,{'error':str(e)})
    except NetworkError as e:
        h.close_connection=True
        h.send_json(e.code,{'error':e.message})


def maintain(server):
    """Explicit/periodic cleanup; failed deletes remain durable for the next run."""
    if not server.CONFIG.get('agent_network',{}).get('enabled'):
        return
    with closing(server.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        cleanup(con)
    with storage_guard(server):
        with closing(server.db()) as con:
            keys=con.execute('SELECT object_key FROM network_storage_gc WHERE not_before<=? LIMIT 20',(stamp(),)).fetchall()
        if keys:
            storage=WebDAVStorage(server.CONFIG['agent_network'].get('storage',{}))
            for r in keys:
                key=r['object_key']
                with closing(server.db()) as con:
                    referenced=con.execute('SELECT 1 FROM network_artifacts WHERE object_key=?',(key,)).fetchone()
                if not referenced:
                    storage.delete(key)
                with closing(server.db()) as con, con:
                    con.execute('DELETE FROM network_storage_gc WHERE object_key=?',(key,))


def maintenance_loop(server):
    while True:
        try:
            maintain(server)
        except Exception:
            # Never put credentials, URLs, or artifact contents in logs.
            server.sys.stderr.write('agent network maintenance deferred; check storage availability\n')
        time.sleep(60)
