#!/usr/bin/env python3
"""Isolated, fictional Agents preview. No workers, credentials or external services.

python3 scripts/demo_agents.py  # http://127.0.0.1:4102/#/agents
The temporary database is removed when the process stops.
"""
import json
import os
import signal
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='pulse-agents-demo-') as tmp:
        root = Path(tmp)
        port = int(os.environ.get('PULSE_DEMO_PORT', '4102'))
        config = root / 'config.json'
        config.write_text(json.dumps({'port':port, 'timezone':'Asia/Tokyo', 'secret':os.urandom(32).hex(),
            'trust_localhost':True, 'tokens':{}, 'agent_network':{'enabled':True}}))
        os.environ['PULSE_CONFIG'] = str(config)
        os.environ['PULSE_DB'] = str(root / 'pulse.db')
        import server as s
        import agent_network as n
        s.init_db()
        t = n.stamp()
        with closing(s.db()) as con, con:
            for device, label, kind, names in [
                ('pc','Home PC','pc',('codex','claude','pi')),
                ('vps','Tokyo VPS','vps',('codex','claude','pi','opencode')),
                ('cloud-research','Research Cloud','cloud',('claude',)),
                ('cloud-build','Build Cloud','cloud',('codex',))]:
                for name in names:
                    a = n.enroll(con, {'device':device,'name':name,'capabilities':['message','file.list','file.read']})
                    offline = a['id'] in ('pc/pi','vps/opencode')
                    state = 'busy' if a['id']=='vps/codex' else 'ready'
                    con.execute('INSERT INTO network_sessions VALUES(?,?,?,?,?)',
                        (a['id'],'demo-message','["message"]',state,t-1080 if offline else t))
                con.execute('UPDATE network_devices SET label=?,kind=? WHERE id=?',(label,kind,device))
            rows = [
                ('1'*32,'pc/codex','vps/codex','leased','Verify shared folder\nPlease check that the shared folder is reachable.',None,t-90),
                ('2'*32,'pc/claude','cloud-research/claude','completed','Review project notes\nPlease summarize the project notes.','Reviewed the notes. The next step is to verify the new navigation.',t-600),
                ('3'*32,'cloud-build/codex','pc/codex','completed','Check the build\nPlease run the local checks.','The local checks passed. The preview is ready to inspect.',t-1200),
                ('4'*32,'vps/pi','pc/pi','queued','Check device connectivity\nPlease confirm you are reachable.',None,t-1800),
                ('5'*32,'pc/codex','vps/claude','interrupted','Review configuration\nCheck the shared configuration.',None,t-2400),
            ]
            for rid,sender,recipient,status,message,reply,created in rows:
                n.grant(con,{'source':recipient,'requester':sender,'kind':'message'})
                con.execute('''INSERT INTO network_requests(id,sender,recipient,kind,share,payload,idempotency_key,status,
                    created_at,expires_at,session,lease_until,attempts,result) VALUES(?,?,?,'message','',?,?,?,?,?,'demo-message',?,1,?)''',
                    (rid,sender,recipient,json.dumps({'message':message}),rid,status,created,t+86400,t+300,
                     json.dumps({'message':reply}) if reply else None))
                if reply:con.execute('INSERT INTO network_audit(ts,actor,action,target) VALUES(?,?,?,?)',(created+60,recipient,'complete',rid))
            # A ready file connector must not hide an active message worker.
            con.execute('INSERT INTO network_sessions VALUES(?,?,?,?,?)',('vps/codex','demo-files','["file.list","file.read"]','ready',t))
        stop = threading.Event()
        def tick():
            while not stop.wait(10):
                with closing(s.db()) as con, con:
                    con.execute("UPDATE network_sessions SET last_seen=? WHERE agent NOT IN ('pc/pi','vps/opencode')",(n.stamp(),))
                    con.execute("UPDATE network_requests SET lease_until=?,expires_at=? WHERE status='leased'",(n.stamp()+300,n.stamp()+86400))
        threading.Thread(target=tick,daemon=True).start()
        class DemoHandler(s.Handler):
            def serve_static(self, path):
                if path not in ('/', '/index.html'):return super().serve_static(path)
                html = (s.STATIC / 'index.html').read_text().replace('</header>', '</header><aside class="demo-notice">Demo workspace · Fictional agents and activity</aside>')
                data = html.encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-cache')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        srv=s.ThreadingHTTPServer(('127.0.0.1',port),DemoHandler)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        print(f'Fictional Agents preview: http://127.0.0.1:{port}/#/agents',flush=True)
        try:srv.serve_forever()
        except KeyboardInterrupt:pass
        finally:stop.set();srv.server_close()


if __name__=='__main__':main()
