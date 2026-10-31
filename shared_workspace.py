"""Temporary, owner-enabled file exchange for every enrolled network identity."""
import hashlib
import json
import re
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import agent_network as net

TTL = 86400


def migrate(con):
    if con.execute('PRAGMA user_version').fetchone()[0] >= 9:
        return
    con.executescript('''
    BEGIN IMMEDIATE;
    CREATE TABLE workspace_settings(id INTEGER PRIMARY KEY CHECK(id=1),
      enabled INTEGER NOT NULL DEFAULT 0, quota_bytes INTEGER NOT NULL);
    INSERT INTO workspace_settings VALUES(1,0,1073741824);
    CREATE TABLE workspace_files(id TEXT PRIMARY KEY, creator TEXT NOT NULL,
      path TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
      object_key TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
    CREATE INDEX workspace_expiry ON workspace_files(expires_at);
    PRAGMA user_version=9;
    COMMIT;
    ''')


def used(con):
    # One capacity across direct workspace uploads and legacy request artifacts.
    return con.execute('SELECT (SELECT COALESCE(SUM(size),0) FROM workspace_files) + '
                       '(SELECT COALESCE(SUM(size),0) FROM network_artifacts)').fetchone()[0]


def quota(con):
    return con.execute('SELECT quota_bytes FROM workspace_settings WHERE id=1').fetchone()[0]


def delete(con, where, args=()):
    con.execute('INSERT OR IGNORE INTO network_storage_gc SELECT object_key,0 FROM workspace_files WHERE '+where, args)
    con.execute('DELETE FROM workspace_files WHERE '+where, args)


def output(row):
    return {k: row[k] for k in ('id','creator','path','size','sha256','created_at','expires_at')}


def status(con, configured):
    settings = con.execute('SELECT * FROM workspace_settings WHERE id=1').fetchone()
    enabled = bool(settings['enabled']) and configured
    return {'enabled':enabled, 'storage_configured':configured, 'quota_bytes':settings['quota_bytes'],
            'used_bytes':used(con), 'ttl_seconds':TTL, 'max_file_bytes':net.MAX_FILE,
            'members':[r[0] for r in con.execute('SELECT id FROM network_agents WHERE revoked=0 ORDER BY id')] if enabled else []}


def authorize(con, actor, digest, owner, configured, require_enabled=True):
    if not owner:
        net.require(con.execute('SELECT 1 FROM network_agents WHERE id=? AND token_hash=? AND revoked=0',
                                (actor,digest)).fetchone(), 'credential revoked',401)
    if require_enabled:
        net.require(status(con,configured)['enabled'], 'shared workspace is disabled',403)


def handle(h, method, path, server, actor, owner, digest):
    parts = path.split('/')[3:]
    storage_config = server.CONFIG['agent_network'].get('storage',{})
    configured = bool(storage_config.get('url') and storage_config.get('credentials_file'))
    upload = method=='POST' and len(parts)==3 and parts[1]=='files'
    data, body = None, {}
    if method != 'GET':
        net.require(not h.headers.get('Transfer-Encoding'), 'chunked bodies are unsupported')
        length = h.headers.get('Content-Length','0')
        net.require(length.isdigit(), 'invalid content length')
        size = int(length)
        net.require(size <= (net.MAX_FILE if upload else 65536), 'body too large',413)
        with closing(server.db()) as con:
            authorize(con,actor,digest,owner,configured,parts!=['workspace'])
        raw = h.rfile.read(size)
        net.require(len(raw)==size,'incomplete body')
        if upload:
            data=raw
            net.require(h.headers.get('X-Content-SHA256')==hashlib.sha256(data).hexdigest(),'checksum mismatch')
        else:
            net.require(h.headers.get('Content-Type','').split(';')[0]=='application/json','JSON content type required',415)
            try: body=json.loads(raw or b'{}')
            except ValueError: raise net.NetworkError(400,'invalid JSON') from None
            net.require(isinstance(body,dict),'JSON object required')
    # Serialize capacity changes, both upload paths and GC. Never hold a DB write
    # transaction across WebDAV I/O; recheck credentials after external calls.
    with net.storage_guard(server):
        with closing(server.db()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            net.cleanup(con)
            authorize(con,actor,digest,owner,configured,parts!=['workspace'])
            if parts==['workspace']:
                if method=='POST':
                    net.require(owner,'owner required',403)
                    capacity=net.integer(body.get('quota_bytes'),1024**2,1024**4)
                    enabled=body.get('enabled')
                    net.require(type(enabled) is bool,'enabled must be boolean')
                    net.require(capacity>=used(con),'capacity is below current usage',409)
                    net.require(not enabled or configured,'storage is not configured',409)
                    con.execute('UPDATE workspace_settings SET enabled=?,quota_bytes=? WHERE id=1',(enabled,capacity))
                    net.audit(con,actor,'workspace-settings',str(capacity))
                else: net.require(method=='GET','method not allowed',405)
                result=status(con,configured)
            elif parts==['workspace','files'] and method=='GET':
                # At most 1000 files; this bounded response fits the CLI/MCP limit.
                result=[output(r) for r in con.execute('SELECT * FROM workspace_files ORDER BY path')]
            else:
                net.require(len(parts)==3 and parts[1]=='files' and re.fullmatch('[0-9a-f]{32}',parts[2]),'file not found',404)
                fid=parts[2]
                row=con.execute('SELECT * FROM workspace_files WHERE id=?',(fid,)).fetchone()
                if upload:
                    name=net.relative_path(parse_qs(urlsplit(h.path).query).get('path',[''])[0])
                    net.require(len(name.encode('utf-8'))<=1024,'path exceeds 1024 UTF-8 bytes')
                    checksum=hashlib.sha256(data).hexdigest()
                    if row:
                        net.require(row['creator']==actor and row['path']==name and row['sha256']==checksum,'file id already used',409)
                        return h.send_json(200,output(row))
                    net.require(not con.execute('SELECT 1 FROM workspace_files WHERE path=?',(name,)).fetchone(),'path already exists; choose another name',409)
                    net.require(con.execute('SELECT COUNT(*) FROM workspace_files').fetchone()[0]<1000,'workspace file limit reached',429)
                    net.require(used(con)+len(data)<=quota(con),'shared workspace capacity exceeded',429)
                    key=fid+'-'+checksum
                    # New object names cannot collide with the legacy artifact namespace.
                    net.require(not con.execute('SELECT 1 FROM network_artifacts WHERE object_key=?',(key,)).fetchone(),'file id already used',409)
                    con.execute('INSERT OR REPLACE INTO network_storage_gc VALUES(?,?)',(key,net.stamp()+3600))
                else:
                    net.require(row,'file unavailable or expired',404)
                    if method=='DELETE':
                        net.require(owner or row['creator']==actor,'only the uploader or owner can remove this file',403)
                        delete(con,'id=?',(fid,)); net.audit(con,actor,'workspace-delete',fid)
                        result={'ok':True}
                    else: net.require(method=='GET','method not allowed',405)
        if upload:
            net.WebDAVStorage(storage_config).put(key,data)
            with closing(server.db()) as con, con:
                con.execute('BEGIN IMMEDIATE')
                authorize(con,actor,digest,owner,configured)
                net.require(used(con)+len(data)<=quota(con),'shared workspace capacity exceeded',429)
                now=net.stamp()
                con.execute('INSERT INTO workspace_files VALUES(?,?,?,?,?,?,?,?)',(fid,actor,name,len(data),checksum,key,now,now+TTL))
                con.execute('DELETE FROM network_storage_gc WHERE object_key=?',(key,))
                net.audit(con,actor,'workspace-upload',fid)
                result=output(con.execute('SELECT * FROM workspace_files WHERE id=?',(fid,)).fetchone())
        elif method=='GET' and len(parts)==3:
            data=net.WebDAVStorage(storage_config).get(row['object_key'],row['size'])
            net.require(data is not None and len(data)==row['size'] and hashlib.sha256(data).hexdigest()==row['sha256'],'file missing or corrupt',502)
            with closing(server.db()) as con:
                authorize(con,actor,digest,owner,configured)
                net.require(con.execute('SELECT 1 FROM workspace_files WHERE id=? AND expires_at>?',(fid,net.stamp())).fetchone(),'file unavailable or expired',404)
            h.send_response(200)
            from urllib.parse import quote
            for k,v in {'Content-Type':'application/octet-stream','Content-Length':str(len(data)),
                        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['path'].split('/')[-1]),
                        'X-Content-SHA256':row['sha256'],'Cache-Control':'no-store',
                        'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"}.items():
                h.send_header(k,v)
            h.end_headers(); h.wfile.write(data)
            return
    return h.send_json(200,result)
