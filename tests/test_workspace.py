"""Real HTTP workspace authorization, quota, expiry and durable cleanup tests."""
import hashlib
import json
import os
import secrets
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_network
from test_pulse import call, server, TOKEN
from test_hardening import owner
from agent_network import maintain, stamp
from network_client import ClientError
from network_storage import StorageError


class MemoryStorage:
    objects = {}

    def __init__(self, config): pass
    def put(self, key, data): self.objects[key] = data
    def get(self, key, size): return self.objects.get(key)
    def delete(self, key): self.objects.pop(key, None)


class WorkspaceTests(unittest.TestCase):
    grant = test_network.NetworkTests.grant
    sql = test_network.NetworkTests.sql

    def setUp(self):
        test_network.NetworkTests.setUp(self)
        self.fake=patch('agent_network.WebDAVStorage',MemoryStorage);self.fake.start()
        MemoryStorage.objects={}
        server.CONFIG['agent_network']['storage']={'url':'http://127.0.0.1:1','credentials_file':'not-read'}
        self.assertTrue(owner('POST','/api/network/workspace',{'enabled':True,'quota_bytes':1024**3})['enabled'])

    def tearDown(self):
        self.sql('INSERT OR IGNORE INTO network_storage_gc SELECT object_key,0 FROM workspace_files')
        self.sql('DELETE FROM workspace_files')
        self.sql('UPDATE workspace_settings SET enabled=0,quota_bytes=1073741824')
        self.fake.stop()
        # No real backend in these tests.
        self.storage={}
        test_network.NetworkTests.tearDown(self)
        # Remove only this test's identities; the process-wide HTTP fixture has
        # a production enrollment cap and deliberately retains other histories.
        for aid in self.ids.values():
            self.sql('DELETE FROM network_requests WHERE sender=? OR recipient=?',(aid,aid))
            self.sql('DELETE FROM network_grants WHERE source=? OR requester=?',(aid,aid))
            self.sql('DELETE FROM network_sessions WHERE agent=?',(aid,))
            self.sql('DELETE FROM network_agents WHERE id=?',(aid,))

    def upload(self, name='folder/sample.txt', data=b'hello', agent='pi', fid=None):
        p=self.root/'source';p.write_bytes(data)
        return self.clients[agent].workspace_upload(p,name,fid)

    def test_all_enrolled_agents_share_and_rename_does_not_change_access(self):
        self.sql("UPDATE network_agents SET capabilities='[\"message\"]' WHERE id=?",(self.ids['other'],))
        f=self.upload()
        for client in self.clients.values():
            self.assertEqual(client.call('GET','/workspace/files')[0]['id'],f['id'])
            self.assertEqual(client.call('GET','/workspace/files/'+f['id'],download=True),b'hello')
        owner('POST','/api/network/agents/label',{'agent':self.ids['pi'],'label':'Renamed agent'})
        self.assertIn(self.ids['pi'],self.clients['other'].call('GET','/workspace')['members'])
        self.assertEqual(f['expires_at']-f['created_at'],86400)
        with self.assertRaises(ClientError) as e:self.clients['other'].call('DELETE','/workspace/files/'+f['id'],{})
        self.assertEqual(e.exception.status,403)
        dest=self.root/'download';self.clients['other'].workspace_download(f['id'],dest)
        self.assertEqual(dest.read_bytes(),b'hello')
        with self.assertRaises(FileExistsError):self.clients['other'].workspace_download(f['id'],dest)

    def test_boundary_disable_and_revocation(self):
        self.assertEqual(call('GET','/api/network/workspace',token=TOKEN)['HTTP'],401)
        self.assertEqual(call('POST','/api/network/workspace',{'enabled':True,'quota_bytes':1024**3},token=self.tokens['pi'])['HTTP'],403)
        self.assertEqual(call('POST','/api/network/workspace',{},token=None,headers={'Cookie':'pulse_session='+server.make_session(),'Origin':'https://evil.example'})['HTTP'],403)
        f=self.upload()
        owner('POST','/api/network/workspace',{'enabled':False,'quota_bytes':1024**3})
        with self.assertRaises(ClientError):self.clients['other'].call('GET','/workspace/files/'+f['id'],download=True)
        owner('POST','/api/network/workspace',{'enabled':True,'quota_bytes':1024**3})
        owner('POST','/api/network/revoke',{'agent':self.ids['pi']})
        with self.assertRaises(ClientError):self.clients['pi'].call('GET','/workspace')
        self.assertEqual(self.clients['other'].call('GET','/workspace/files'),[])
        maintain(server);self.assertFalse(MemoryStorage.objects)

    def test_quota_competing_uploads_and_settings_validation(self):
        self.sql('UPDATE workspace_settings SET quota_bytes=1048576')
        a=self.root/'a';a.write_bytes(b'a'*700000)
        def attempt(n):
            try:return self.clients['pi'].workspace_upload(a,str(n)+'.bin')
            except ClientError as e:return e.status
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn(429,results)
        self.assertEqual(len(MemoryStorage.objects),1)
        for capacity in (0,True,1024**4+1):
            self.assertEqual(owner('POST','/api/network/workspace',{'enabled':True,'quota_bytes':capacity})['HTTP'],400)
        self.sql('UPDATE workspace_files SET size=2097152')
        self.assertEqual(owner('POST','/api/network/workspace',{'enabled':True,'quota_bytes':1048576})['HTTP'],409)

    def test_idempotency_paths_and_checksum(self):
        fid=secrets.token_hex(16);f=self.upload(fid=fid)
        self.assertEqual(self.upload(fid=fid),f)
        for kwargs in ({'data':b'changed','fid':fid},{'agent':'other','fid':fid},{'fid':secrets.token_hex(16)}):
            with self.assertRaises(ClientError) as e:self.upload(**kwargs)
            self.assertEqual(e.exception.status,409)
        for path in ('../secret','/root/file','.hidden/file','a//b'):
            with self.assertRaises(Exception):self.upload(name=path)
        with self.assertRaises(ClientError) as e:
            self.clients['pi'].call('POST','/workspace/files/'+secrets.token_hex(16)+'?path=test',data=b'bad',extra={'X-Content-SHA256':'0'*64})
        self.assertEqual(e.exception.status,400)
        self.assertEqual(len(MemoryStorage.objects),1)

    def test_expiry_and_retryable_physical_cleanup(self):
        f=self.upload();self.sql('UPDATE workspace_files SET expires_at=?',(stamp()-1,))
        self.assertEqual(self.clients['pi'].call('GET','/workspace/files'),[])
        with patch.object(MemoryStorage,'delete',side_effect=StorageError('unavailable')):
            with self.assertRaises(StorageError):maintain(server)
        self.assertTrue(self.sql('SELECT * FROM network_storage_gc'))
        maintain(server);self.assertFalse(MemoryStorage.objects)
        with self.assertRaises(ClientError):self.clients['pi'].call('GET','/workspace/files/'+f['id'],download=True)

    def test_revocation_during_upload_does_not_publish(self):
        original=MemoryStorage.put
        def revoke(store,key,data):
            original(store,key,data)
            owner('POST','/api/network/revoke',{'agent':self.ids['pi']})
        with patch.object(MemoryStorage,'put',revoke):
            with self.assertRaises(ClientError) as e:self.upload()
        self.assertEqual(e.exception.status,401)
        self.assertFalse(self.sql('SELECT * FROM workspace_files'))
        self.sql('UPDATE network_storage_gc SET not_before=0');maintain(server)
        self.assertFalse(MemoryStorage.objects)

    def test_backup_does_not_retain_temporary_files(self):
        from scripts.backup_network import snapshot
        self.upload()
        storage=self.root/'storage';storage.mkdir()
        for filename in ('copyparty.conf','credentials.json'):
            (storage/filename).write_text('test fixture')
        saved=snapshot(storage,self.root/'backups')
        manifest=json.loads((saved/'manifest.json').read_text())
        with sqlite3.connect(saved/manifest['database']) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM workspace_files').fetchone()[0],0)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(list((saved/'objects').iterdir()),[])
        self.assertEqual(len(self.clients['pi'].call('GET','/workspace/files')),1)

    @unittest.skipUnless(os.environ.get('PULSE_TEST_STORAGE_CONFIG'),'requires real Copyparty')
    def test_real_storage_upload_fetch_and_expiry(self):
        self.fake.stop()
        server.CONFIG['agent_network']['storage']=self.storage
        try:
            f=self.upload(data=b'real shared workspace transfer')
            for client in self.clients.values():
                self.assertEqual(client.call('GET','/workspace/files/'+f['id'],download=True),b'real shared workspace transfer')
            self.sql('UPDATE workspace_files SET expires_at=?',(stamp()-1,))
            maintain(server)
            self.assertEqual(self.clients['pi'].call('GET','/workspace/files'),[])
            from network_storage import WebDAVStorage
            self.assertIsNone(WebDAVStorage(self.storage).get(f['id']+'-'+f['sha256'],f['size']))
        finally:
            self.fake.start()
