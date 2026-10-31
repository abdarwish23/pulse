"""Real HTTP coordination tests. Optional real Copyparty via PULSE_TEST_STORAGE_CONFIG."""
import hashlib
import json
import os
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_pulse import call, server, BASE, TOKEN
from test_hardening import owner
from agent_network import stamp, maintain, NetworkError
from network_client import Client, ClientError
from network_connector import Connector, read_shared, list_shared


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        config=os.environ.get('PULSE_TEST_STORAGE_CONFIG')
        self.storage=json.loads(Path(config).read_text()) if config else {}
        self.cfg=patch.dict(server.CONFIG,{'agent_network':{'enabled':True,'storage':self.storage}})
        self.cfg.start()
        self.device='test-'+secrets.token_hex(5)
        self.tokens={};self.ids={};self.clients={}
        for name in ('pi','codex','other'):
            r=owner('POST','/api/network/agents',{'device':self.device,'name':name,'capabilities':['message','file.list','file.read']})
            self.assertIn('token',r,r)
            self.ids[name]=r['id'];self.tokens[name]=r['token']
            p=self.root/(name+'.token');p.write_text(r['token']);p.chmod(0o600)
            self.clients[name]=Client(BASE,str(p))
        for kind in ('file.read','file.list','message'):
            self.grant(kind)

    def tearDown(self):
        for aid in self.ids.values():owner('POST','/api/network/revoke',{'agent':aid})
        if self.storage:maintain(server)
        self.cfg.stop();self.tmp.cleanup()

    def grant(self,kind,delete=False):
        return owner('DELETE' if delete else 'POST','/api/network/grants',{
            'source':self.ids['codex'],'requester':self.ids['pi'],'kind':kind,'share':'demos' if kind.startswith('file.') else ''})

    def request(self,kind='file.read',key=None,path='sample.mp3'):
        return self.clients['pi'].call('POST','/requests',{'recipient':self.ids['codex'],'kind':kind,'share':'demos',
            'payload':{'message':'Inspect the demo; do not execute commands'} if kind=='message' else {'path':path},
            'idempotency_key':key or secrets.token_hex(8)})

    def claim(self,session='test-session',kind='file.read'):
        c=self.clients['codex'];c.call('POST','/heartbeat',{'session_id':session,'capabilities':[kind]})
        return c.call('POST','/claim',{'session_id':session})

    def sql(self,sql,args=()):
        with closing(server.db()) as con,con:return con.execute(sql,args).fetchall()

    def test_device_and_agent_names_preserve_identity_and_authority(self):
        job = self.request('message')
        original = self.sql('SELECT id,device,token_hash,capabilities FROM network_agents WHERE id=?', (self.ids['codex'],))[0]
        grants = [tuple(r) for r in self.sql('SELECT * FROM network_grants WHERE source=?', (self.ids['codex'],))]
        path = '/api/network/devices/' + self.device
        changed = owner('POST', path, {'label':'  Tokyo Cloud  ', 'kind':'cloud'})
        self.assertEqual(changed, {'id':self.device, 'label':'Tokyo Cloud', 'kind':'cloud'})
        self.assertEqual(owner('POST','/api/network/agents/label',{'agent':self.ids['codex'],'label':'Build assistant'})['label'],'Build assistant')
        self.assertEqual(tuple(self.sql('SELECT id,device,token_hash,capabilities FROM network_agents WHERE id=?', (self.ids['codex'],))[0]), tuple(original))
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM network_grants WHERE source=?', (self.ids['codex'],))], grants)
        server.init_db()
        self.assertEqual(next(d for d in owner('GET','/api/network/devices') if d['id']==self.device)['label'],'Tokyo Cloud')
        self.assertEqual(self.claim(kind='message')['id'],job['id'])
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['recipient'], self.ids['codex'])
        for body in ({'label':' ', 'kind':'cloud'},{'label':'x'*101,'kind':'pc'},{'label':'Valid','kind':'invalid'},{'label':'bad\nname','kind':'pc'}):
            self.assertEqual(owner('POST',path,body)['HTTP'],400)
        self.assertEqual(call('POST',path,{'label':'Hijacked','kind':'pc'},token=self.tokens['pi'])['HTTP'],403)
        self.assertEqual(call('POST','/api/network/agents/label',{'agent':self.ids['codex'],'label':'Hijacked'},token=self.tokens['pi'])['HTTP'],403)
        self.assertEqual(call('POST',path,{'label':'Hijacked','kind':'pc'},token=None,headers={'Cookie':'pulse_session='+server.make_session(),'Origin':'https://evil.example'})['HTTP'],403)
        self.assertEqual(owner('POST','/api/network/devices/missing',{'label':'Missing','kind':'pc'})['HTTP'],404)

    def test_busy_worker_is_not_masked_by_ready_file_connector(self):
        c = self.clients['codex']
        c.call('POST','/heartbeat',{'session_id':'files','capabilities':['file.read']})
        c.call('POST','/heartbeat',{'session_id':'worker','capabilities':['message'],'state':'busy'})
        def agent():return next(a for a in c.call('GET','/agents') if a['id']==self.ids['codex'])
        self.assertEqual((agent()['status'],agent()['activity']),('busy','working'))
        self.sql('UPDATE network_sessions SET last_seen=? WHERE agent=? AND id=?',(stamp()-100,self.ids['codex'],'worker'))
        self.assertEqual((agent()['status'],agent()['activity']),('ready','files-only'))
        job=self.request('message');claimed=self.claim('worker','message')
        self.assertEqual(claimed['id'],job['id'])
        self.assertEqual(agent()['activity'],'working')
        c.call('POST','/requests/'+job['id']+'/complete',{'session_id':'worker','lease':claimed['lease'],'result':{'message':'Done'}})
        response=c.call('GET','/requests/'+job['id'])
        self.assertIsNotNone(response['finished_at'])
        self.assertGreaterEqual(response['updated_at'],response['created_at'])
        self.assertEqual(agent()['activity'],'idle')
        self.sql('UPDATE network_sessions SET last_seen=? WHERE agent=?',(stamp()-100,self.ids['codex']))
        self.assertEqual((agent()['status'],agent()['activity']),('offline','offline'))

    def test_identity_cannot_be_spoofed_or_cross_boundary(self):
        self.assertEqual(call('GET','/api/network/agents')['HTTP'],401)
        self.assertEqual(call('GET','/api/network/agents',token=None)['HTTP'],401)
        self.assertEqual(call('GET','/api/notes',token=self.tokens['pi'])['HTTP'],401)
        r=call('POST','/api/network/heartbeat',{'session_id':'a','capabilities':[]},token=self.tokens['pi'],headers={'X-Pulse-Agent':self.ids['codex']})
        self.assertEqual(r['agent'],self.ids['pi'])
        self.assertEqual(call('POST','/api/network/agents',{'device':'fake','name':'x'},token=self.tokens['pi'])['HTTP'],403)
        self.assertEqual(owner('POST','/api/network/grants',{'source':'fake','requester':self.ids['pi'],'kind':'message'})['HTTP'],404)
        self.assertEqual(call('POST','/api/network/revoke',{'agent':self.ids['pi']},token=None,headers={
            'Cookie':'pulse_session='+server.make_session(),'Origin':'https://evil.example'})['HTTP'],403)

    def test_offline_queue_idempotency_and_scope(self):
        job=self.request(key='stable');self.assertEqual(job['status'],'queued')
        agents=self.clients['pi'].call('GET','/agents')
        self.assertEqual(next(a for a in agents if a['id']==self.ids['codex'])['status'],'offline')
        self.assertEqual(self.request(key='stable')['id'],job['id'])
        with self.assertRaises(ClientError) as e:self.request(key='stable',path='different')
        self.assertEqual(e.exception.status,409)
        with self.assertRaises(ClientError) as e:self.clients['other'].call('GET','/requests/'+job['id'])
        self.assertEqual(e.exception.status,404)
        with self.assertRaises(ClientError) as e:self.clients['other'].call('POST','/requests',{
            'recipient':self.ids['codex'],'kind':'file.read','share':'demos','payload':{'path':'sample.mp3'},'idempotency_key':'denied'})
        self.assertEqual(e.exception.status,403)
        # Reinitialization preserves queue and stable IDs (same path used after server restart).
        server.init_db()
        self.assertEqual(self.claim()['id'],job['id'])

    def test_concurrent_claim_and_stale_completion(self):
        job=self.request()
        for sid in ('one','two'):self.clients['codex'].call('POST','/heartbeat',{'session_id':sid,'capabilities':['file.read']})
        with ThreadPoolExecutor(2) as pool:
            claims=list(pool.map(lambda sid:self.clients['codex'].call('POST','/claim',{'session_id':sid}),('one','two')))
        self.assertEqual(sum(c is not None for c in claims),1)
        old=next(c for c in claims if c)
        self.sql('UPDATE network_requests SET lease_until=? WHERE id=?',(stamp()-1,job['id']))
        new=self.claim(session='three')
        self.assertNotEqual(new['lease'],old['lease'])
        with self.assertRaises(ClientError) as e:self.clients['codex'].call('POST','/requests/'+job['id']+'/complete',{
            'session_id':old['session_id'],'lease':old['lease'],'result':{},'error':'old failure'})
        self.assertEqual(e.exception.status,403)

    def test_message_interruption_requires_reconciliation(self):
        job=self.request('message');claimed=self.claim(kind='message')
        self.sql('UPDATE network_requests SET lease_until=? WHERE id=?',(stamp()-1,job['id']))
        self.assertIsNone(self.claim(session='new',kind='message'))
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['status'],'interrupted')
        with self.assertRaises(ClientError):self.clients['pi'].call('POST','/requests/'+job['id']+'/retry',{})
        self.clients['pi'].call('POST','/requests/'+job['id']+'/retry',{'reconciled':True})
        new=self.claim(session='new',kind='message')
        body={'session_id':new['session_id'],'lease':new['lease'],'result':{'message':'Checked the wording'}}
        result=self.clients['codex'].call('POST','/requests/'+job['id']+'/complete',body)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.clients['codex'].call('POST','/requests/'+job['id']+'/complete',body)['status'],'completed')
        with self.assertRaises(ClientError):self.clients['codex'].call('POST','/requests/'+job['id']+'/complete',{**body,'result':{'message':'different'}})

    def test_revocation_cancellation_expiry_and_presence(self):
        job=self.request();claimed=self.claim()
        self.grant('file.read',delete=True)
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['status'],'cancelled')
        with self.assertRaises(ClientError):self.request()
        self.grant('file.read')
        expired=self.request();self.sql('UPDATE network_requests SET expires_at=? WHERE id=?',(stamp()-1,expired['id']))
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+expired['id'])['status'],'expired')
        self.sql('UPDATE network_sessions SET last_seen=? WHERE agent=?',(stamp()-100,self.ids['codex']))
        a=next(a for a in self.clients['pi'].call('GET','/agents') if a['id']==self.ids['codex'])
        self.assertEqual(a['status'],'offline')
        owner('POST','/api/network/revoke',{'agent':self.ids['codex']})
        with self.assertRaises(ClientError) as e:self.clients['codex'].call('GET','/agents')
        self.assertEqual(e.exception.status,401)

    def test_malformed_inputs_limits_and_capability_denial(self):
        for path in ('../secret','/etc/passwd','a/../b','.env','a//b','a\\b'):
            with self.assertRaises(ClientError):self.request(path=path)
        with self.assertRaises(ClientError):self.clients['pi'].call('POST','/heartbeat',{'session_id':'x','capabilities':['shell']})
        self.assertEqual(call('POST','/api/network/requests',{},token=self.tokens['pi'],headers={'Content-Length':'999999999'})['HTTP'],413)
        self.assertEqual(call('POST','/api/network/heartbeat',{},token=self.tokens['pi'],headers={'Content-Length':'bogus'})['HTTP'],400)
        self.assertEqual(call('POST','/api/network/heartbeat',{},token=self.tokens['pi'],headers={'Content-Type':'text/plain'})['HTTP'],415)

    def test_mcp_message_claim_reply_and_cli_discovery(self):
        import subprocess
        import sys
        job=self.request('message')
        env={**os.environ,'PULSE_URL':BASE,'PULSE_NETWORK_TOKEN_FILE':str(self.root/'codex.token')}
        p=subprocess.Popen([sys.executable,str(Path(server.__file__).parent/'pulse_mcp.py')],env=env,
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            def tool(name,args):
                p.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})+'\n');p.stdin.flush()
                r=json.loads(p.stdout.readline())['result']
                self.assertFalse(r.get('isError'),r)
                return json.loads(r['content'][0]['text'])
            claimed=tool('claim_agent_request',{})
            self.assertEqual(claimed['id'],job['id'])
            reply=tool('complete_agent_request',{'request_id':job['id'],'lease':claimed['lease'],'message':'Reviewed by the recipient session'})
            self.assertEqual(reply['status'],'completed')
        finally:
            p.stdin.close();p.wait(timeout=5);p.stdout.close();p.stderr.close()
        result=subprocess.run([sys.executable,str(Path(server.__file__).parent/'pulse'),'network','agents'],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any(a['id']==self.ids['pi'] for a in json.loads(result.stdout)))

    def test_slow_storage_does_not_lock_database_and_revocation_wins(self):
        import threading
        import agent_network
        started=threading.Event();release=threading.Event()
        def put(*args):
            started.set()
            self.assertTrue(release.wait(5),'storage test was not released')
        job=self.request();claimed=self.claim()
        with patch.object(agent_network,'WebDAVStorage') as storage, ThreadPoolExecutor(1) as pool:
            storage.return_value.put.side_effect=put
            transfer=pool.submit(self.clients['codex'].upload,claimed,b'bounded upload')
            try:
                self.assertTrue(started.wait(2))
                # This needs a write transaction. It must succeed while storage is stalled.
                self.assertEqual(self.grant('file.read',delete=True),{'ok':True})
            finally:release.set()
            with self.assertRaises(ClientError):transfer.result(timeout=3)
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['status'],'cancelled')
        self.assertFalse(self.sql('SELECT 1 FROM network_artifacts WHERE request_id=?',(job['id'],)))

    def test_connector_lists_only_approved_files_and_local_grants(self):
        share=self.root/'demos';share.mkdir();(share/'hello.txt').write_text('hello');(share/'.env').write_text('hidden')
        (share/'escape').symlink_to('/etc/passwd')
        connector=Connector(BASE,{'token_file':str(self.root/'codex.token'),'shares':{'demos':{'path':str(share),'requesters':[self.ids['pi']]}}})
        job=self.request('file.list',path='');self.assertTrue(connector.tick())
        result=self.clients['pi'].call('GET','/requests/'+job['id'])
        self.assertEqual(result['result']['entries'],[{'name':'hello.txt','type':'file','size':5}])
        connector.shares['demos']['requesters']=[]
        job=self.request('file.list',path='');connector.tick()
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['status'],'failed')

    @unittest.skipUnless(os.environ.get('PULSE_TEST_STORAGE_CONFIG'),'set PULSE_TEST_STORAGE_CONFIG for real Copyparty transfers')
    def test_real_copyparty_connector_transfer_retries_and_withdrawal(self):
        data=b'ID3'+os.urandom(20000)
        share=self.root/'demos';share.mkdir();(share/'sample.mp3').write_bytes(data)
        connector=Connector(BASE,{'token_file':str(self.root/'codex.token'),'shares':{'demos':{'path':str(share),'requesters':[self.ids['pi']]}}})
        job=self.request();connector.tick()
        result=self.clients['pi'].call('GET','/requests/'+job['id'])
        self.assertEqual(result['status'],'completed');self.assertEqual(result['artifact']['sha256'],hashlib.sha256(data).hexdigest())
        output=self.root/'download.mp3';self.clients['pi'].download(job['id'],output)
        self.assertEqual(output.read_bytes(),data);self.assertEqual(output.stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):self.clients['pi'].download(job['id'],output)
        with self.assertRaises(ClientError) as e:self.clients['other'].download(job['id'],self.root/'denied')
        self.assertEqual(e.exception.status,404)
        self.assertEqual(self.clients['other'].call('GET','/artifacts'),[])
        owner('POST','/api/network/grants',{'source':self.ids['codex'],'requester':self.ids['other'],'kind':'file.read','share':'demos'})
        catalog=self.clients['other'].call('GET','/artifacts')
        self.assertEqual(catalog[0]['id'],job['id'])
        self.clients['other'].download(job['id'],self.root/'third-agent.mp3')
        self.assertEqual((self.root/'third-agent.mp3').read_bytes(),data)
        with self.assertRaises(ClientError):self.clients['other'].call('GET','/requests/'+job['id'])
        row=self.sql('SELECT session,lease FROM network_requests WHERE id=?',(job['id'],))[0]
        retry={**job,'session_id':row['session'],'lease':row['lease']}
        self.clients['codex'].upload(retry,data)
        with self.assertRaises(ClientError):self.clients['codex'].upload(retry,b'different')
        self.grant('file.read',delete=True)
        with self.assertRaises(ClientError):self.clients['pi'].download(job['id'],self.root/'revoked')
        maintain(server)
        self.assertFalse(self.sql('SELECT 1 FROM network_artifacts WHERE request_id=?',(job['id'],)))


    @unittest.skipUnless(os.environ.get('PULSE_TEST_STORAGE_CONFIG'),'requires real Copyparty')
    def test_permanent_retention_expiry_and_integrity_failure(self):
        server.CONFIG['agent_network']['artifact_ttl_seconds']=0
        job=self.request();claimed=self.claim()
        data=b'keep this artifact'
        self.clients['codex'].upload(claimed,data)
        row=self.sql('SELECT * FROM network_artifacts WHERE request_id=?',(job['id'],))[0]
        self.assertEqual(row['expires_at'],0)
        self.sql('UPDATE network_requests SET expires_at=? WHERE id=?',(stamp()-40*86400,job['id']))
        maintain(server)
        self.assertEqual(self.clients['pi'].call('GET','/requests/'+job['id'])['artifact']['size'],len(data))
        from network_storage import WebDAVStorage
        storage=WebDAVStorage(self.storage)
        storage.put(row['object_key'],b'corrupt')
        with self.assertRaises(ClientError) as e:self.clients['pi'].download(job['id'],self.root/'corrupt')
        self.assertEqual(e.exception.status,502)
        self.sql('UPDATE network_artifacts SET expires_at=? WHERE request_id=?',(stamp()-1,job['id']))
        maintain(server)
        self.assertIsNone(storage.get(row['object_key'],len(data)))



class ConnectorPathTests(unittest.TestCase):
    def test_symlinks_hardlinks_fifo_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'normal').write_bytes(b'ok')
            self.assertEqual(read_shared(root,'normal'),b'ok')
            (root/'symlink').symlink_to(root/'normal')
            (root/'sub').mkdir();(root/'escape-dir').symlink_to(root/'sub')
            os.link(root/'normal',root/'hardlink');os.mkfifo(root/'pipe')
            for path in ('symlink','hardlink','normal','pipe','escape-dir/file','../etc/passwd'):
                with self.assertRaises((OSError,ValueError,NetworkError)):read_shared(root,path)
            with open(root/'big','wb') as f:f.truncate(32*1024*1024+1)
            with self.assertRaises(ValueError):read_shared(root,'big')

    def test_client_rejects_non_tls_remote_url(self):
        with self.assertRaises(ClientError):Client('http://example.com','unused')


class ProcessRecoveryTests(unittest.TestCase):
    def test_queue_survives_actual_server_restart(self):
        import socket
        import subprocess
        import sys
        import urllib.request
        with tempfile.TemporaryDirectory(prefix='pulse-restart-') as tmp:
            root=Path(tmp)
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            cfg=root/'config.json';cfg.write_text(json.dumps({'port':port,'trust_localhost':True,'agent_network':{'enabled':True}}))
            env={**os.environ,'PULSE_CONFIG':str(cfg),'PULSE_DB':str(root/'pulse.db')}
            url=f'http://127.0.0.1:{port}'
            def owner_call(path,body):
                req=urllib.request.Request(url+'/api/network'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=2) as r:return json.load(r)
            with open(root/'server.log','w') as log:
                def start():
                    p=subprocess.Popen([sys.executable,str(Path(server.__file__).resolve())],env=env,stdout=log,stderr=log)
                    for _ in range(100):
                        if p.poll() is not None:raise AssertionError('test server exited')
                        try:
                            with urllib.request.urlopen(url+'/api/health',timeout=.1):return p
                        except OSError:time.sleep(.05)
                    p.terminate();p.wait();raise AssertionError('test server did not start')
                p=start()
                try:
                    tokens={}
                    for name in ('pi','codex'):
                        r=owner_call('/agents',{'device':'fixture','name':name,'capabilities':['message']})
                        f=root/(name+'.token');f.write_text(r['token']);tokens[name]=f
                    owner_call('/grants',{'source':'fixture/codex','requester':'fixture/pi','kind':'message'})
                    client=Client(url,str(tokens['pi']))
                    job=client.call('POST','/requests',{'recipient':'fixture/codex','kind':'message','payload':{'message':'Persistent request'},'idempotency_key':'restart'})
                    p.terminate();p.wait(timeout=5);p=start()
                    self.assertEqual(client.call('GET','/requests/'+job['id'])['status'],'queued')
                    worker=Client(url,str(tokens['codex']))
                    worker.call('POST','/heartbeat',{'session_id':'new-process','capabilities':['message']})
                    claimed=worker.call('POST','/claim',{'session_id':'new-process'})
                    self.assertEqual(claimed['id'],job['id'])
                finally:p.terminate();p.wait(timeout=5)
