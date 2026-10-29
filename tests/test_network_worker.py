"""Real queue + local subprocess tests; no model calls or production data."""
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import test_network as network_tests
from test_network import BASE
from network_client import ClientError
from network_worker import Worker, bounded, feedback, save


class WorkerTests(unittest.TestCase):
    setUp = network_tests.NetworkTests.setUp
    tearDown = network_tests.NetworkTests.tearDown
    grant = network_tests.NetworkTests.grant
    request = network_tests.NetworkTests.request
    sql = network_tests.NetworkTests.sql

    def worker(self, source, runtime='pi', **extra):
        executable = self.root / ('fake-' + runtime)
        executable.write_text('#!/usr/bin/env python3\n' + source)
        executable.chmod(0o700)
        profile = {'agent': self.ids['codex'], 'runtime': runtime, 'executable': str(executable),
                   'token_file': str(self.root / 'codex.token'), 'requesters': [self.ids['pi']],
                   'execute': True, 'cwd': str(self.root), 'timeout_seconds': 10, **extra}
        worker = Worker(BASE, profile, self.root / ('state-' + runtime))
        self.addCleanup(worker.lock.close)
        return worker

    def result(self, job):
        return self.clients['pi'].call('GET', '/requests/' + job['id'])

    def test_each_adapter_returns_actual_final_feedback(self):
        scripts = {
            'pi': "import sys\nsys.stdin.read()\nprint('pi feedback')\n",
            'codex': "import sys,pathlib\nsys.stdin.read()\npathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('codex feedback')\nprint('tool chatter')\n",
            'claude': "import sys,json\nsys.stdin.read()\nprint(json.dumps({'result':'claude feedback','is_error':False}))\n",
            'opencode': "import sys,json\nassert 'TASK:' in sys.argv[-1]\nprint(json.dumps({'type':'text','part':{'text':'opencode feedback'}}))\n"
        }
        for runtime, source in scripts.items():
            with self.subTest(runtime=runtime):
                worker = self.worker(source, runtime)
                job = self.request('message')
                self.assertTrue(worker.tick(threading.Event()))
                result = self.result(job)
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['result']['message'], runtime + ' feedback')
                self.assertEqual(result['attempts'], 1)
                self.assertFalse(worker.tick(threading.Event()))

    def test_input_is_data_and_secrets_are_redacted(self):
        worker = self.worker("import sys,os\nprompt=sys.stdin.read()\nassert '$(touch owned)' in prompt\nprint(os.environ['FAKE_API_KEY'])\n", env={'FAKE_API_KEY': 'sk-secretsecretsecret'})
        job = self.clients['pi'].call('POST', '/requests', {'recipient': self.ids['codex'], 'kind': 'message',
              'payload': {'message': '$(touch owned)'}, 'idempotency_key': 'injection'})
        worker.tick(threading.Event())
        self.assertFalse((self.root / 'owned').exists())
        self.assertEqual(self.result(job)['result']['message'], '[redacted]')

    def test_local_grant_denies_launch_and_missing_runtime_reports_failure(self):
        worker = self.worker("raise Exception('must not launch')", requesters=['not/enabled'])
        job = self.request('message')
        worker.tick(threading.Event())
        self.assertEqual(self.result(job)['error'], 'Local execution grant denied')
        worker.profile['requesters'] = [self.ids['pi']]
        worker.profile['executable'] = '/nonexistent/runtime'
        job = self.request('message')
        worker.tick(threading.Event())
        self.assertEqual(self.result(job)['error'], 'Agent runtime unavailable')

    def test_failure_and_timeout_return_feedback(self):
        worker = self.worker("import sys\nprint('authentication unavailable',file=sys.stderr)\nsys.exit(7)")
        job = self.request('message')
        worker.tick(threading.Event())
        result = self.result(job)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('authentication unavailable', result['result']['message'])
        Path(worker.profile['executable']).write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n')
        worker.timeout = 1
        job = self.request('message')
        worker.tick(threading.Event())
        self.assertEqual(self.result(job)['error'], 'Agent task timed out')

    def test_stop_terminates_process_and_completes_failure(self):
        worker = self.worker("import time\nprint('started',flush=True)\ntime.sleep(60)")
        job = self.request('message')
        stop = threading.Event()
        thread = threading.Thread(target=worker.tick, args=(stop,))
        thread.start()
        deadline = time.monotonic() + 3
        while self.result(job)['status'] == 'queued' and time.monotonic() < deadline:
            time.sleep(.02)
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.result(job)['error'], 'Worker stopped during execution')

    def test_revoked_request_stops_without_success(self):
        worker = self.worker("import time\ntime.sleep(60)")
        job = self.request('message')
        original = worker.client.call
        def revoke_on_renew(method, path, *args, **kwargs):
            if path.endswith('/renew'):
                self.grant('message', delete=True)
            return original(method, path, *args, **kwargs)
        with patch.object(worker.client, 'call', side_effect=revoke_on_renew):
            worker.tick(threading.Event())
        self.assertEqual(self.result(job)['status'], 'cancelled')

    def test_lost_completion_response_does_not_rerun(self):
        worker = self.worker("from pathlib import Path\np=Path('runs');p.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint('done')")
        job = self.request('message')
        original = worker.client.call
        def lose_response(method, path, *args, **kwargs):
            value = original(method, path, *args, **kwargs)
            if path.endswith('/complete'):
                raise ClientError('lost response')
            return value
        with patch.object(worker.client, 'call', side_effect=lose_response):
            worker.tick(threading.Event())
        self.assertEqual(self.result(job)['status'], 'completed')
        worker.tick(threading.Event())
        self.assertEqual((self.root / 'runs').read_text(), 'x')

    def test_restart_delivers_saved_result_without_execution(self):
        worker = self.worker("raise Exception('must not run')")
        job = self.request('message')
        worker.heartbeat()
        claimed = worker.client.call('POST', '/claim', {'session_id': worker.session})
        save(worker.pending_file, {'session_id': worker.session, 'job': claimed,
                                  'completion': worker.result('saved feedback')})
        worker.lock.close()
        resumed = Worker(BASE, worker.profile, self.root / 'state-pi')
        self.addCleanup(resumed.lock.close)
        resumed.tick(threading.Event())
        self.assertEqual(self.result(job)['result']['message'], 'saved feedback')

    def test_crash_before_result_is_failed_never_reexecuted(self):
        worker = self.worker("raise Exception('must not run')")
        job = self.request('message')
        worker.heartbeat()
        claimed = worker.client.call('POST', '/claim', {'session_id': worker.session})
        save(worker.pending_file, {'session_id': worker.session, 'job': claimed})
        worker.lock.close()
        resumed = Worker(BASE, worker.profile, self.root / 'state-pi')
        self.addCleanup(resumed.lock.close)
        resumed.tick(threading.Event())
        self.assertEqual(self.result(job)['error'], 'Worker interrupted during execution')
        self.assertEqual(self.result(job)['attempts'], 1)

    def test_duplicate_worker_is_rejected(self):
        worker = self.worker("print('done')")
        with self.assertRaises(BlockingIOError):
            Worker(BASE, worker.profile, self.root / 'state-pi')

    def test_json_error_and_empty_success_are_failures(self):
        final = self.root / 'final'
        for runtime, output in [('claude', '{"is_error":true,"result":"quota exceeded"}'),
                                ('opencode', '{"type":"error","error":{"message":"bad model"}}'),
                                ('pi', '')]:
            self.assertTrue(feedback(runtime, output, '', final, 0)[1])
        self.assertLess(len(json.dumps({'message': bounded('あ' * 100000)})), 32000)


if __name__ == '__main__':
    unittest.main()
