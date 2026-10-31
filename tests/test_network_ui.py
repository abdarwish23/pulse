"""Schema upgrade safety for the named-device directory."""
import json
import sqlite3
import unittest
import agent_network as n


class DeviceMigrationTests(unittest.TestCase):
    def test_v7_upgrade_retains_credentials_grants_and_requests(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.row_factory = sqlite3.Row
        n.migrate_v7(con)
        for device in ('pc', 'vps-eu', 'cloud-build', 'workstation'):
            aid = device + '/codex'
            con.execute('INSERT INTO network_agents VALUES(?,?,?,?,?,0,1)',
                        (aid, device, aid, 'hash-'+device, '["message"]'))
        con.execute("INSERT INTO network_grants VALUES('vps-eu/codex','pc/codex','message','',1)")
        con.execute("INSERT INTO network_sessions VALUES('pc/codex','existing','[\"message\"]','ready',1)")
        con.execute('''INSERT INTO network_requests(id,sender,recipient,kind,share,payload,idempotency_key,created_at,expires_at)
                       VALUES('existing','pc/codex','vps-eu/codex','message','','{}','existing',1,2)''')
        con.commit()
        tables = ('network_agents','network_sessions','network_grants','network_requests')
        before = {t:[tuple(r) for r in con.execute('SELECT * FROM '+t)] for t in tables}
        n.migrate(con); n.migrate(con)
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],8)
        for t in tables:self.assertEqual(before[t],[tuple(r) for r in con.execute('SELECT * FROM '+t)])
        self.assertEqual({r['id']:r['kind'] for r in con.execute('SELECT * FROM network_devices')},
                         {'pc':'pc','vps-eu':'vps','cloud-build':'cloud','workstation':'other'})
        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
