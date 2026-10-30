#!/usr/bin/env python3
"""Run the complete suite against an isolated real Copyparty service. No live config/data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent.parent


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--copyparty',required=True,help='Pinned copyparty-sfx.py prepared by setup_network_storage.py')
    a=ap.parse_args()
    binary=Path(a.copyparty).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix='pulse-storage-test-') as tmp:
        root=Path(tmp);(root/'files').mkdir(mode=0o700)
        password=secrets.token_urlsafe(32)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        conf=root/'storage.conf'
        conf.write_text(f'''[global]
  i: 127.0.0.1
  p: {port}
  no-thumb
  no-mtag-ff
  no-html
  no-readme
  no-logues
  no-robots
  usernames
  dav-auth
  xvol
  daw
  q
[accounts]
  pulse: {password}
[/artifacts]
  {root}/files
  accs:
    rwd: pulse
  flags:
    e2ds
    df: 2g
    vmaxb: 1g
    nosub
''');conf.chmod(0o600)
        creds=root/'credentials.json';creds.write_text(json.dumps({'username':'pulse','password':password}));creds.chmod(0o600)
        storage=root/'storage.json';storage.write_text(json.dumps({'url':f'http://127.0.0.1:{port}/artifacts','credentials_file':str(creds)}))
        with open(root/'service.log','w') as log:
            process=subprocess.Popen([sys.executable,str(binary),'-c',str(conf)],cwd=root,stdout=log,stderr=log)
            try:
                ready=False
                for _ in range(100):
                    if process.poll() is not None:raise RuntimeError('Copyparty failed to start; inspect your pinned binary/config')
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):ready=True;break
                    except OSError:time.sleep(.1)
                if not ready:raise RuntimeError('Copyparty startup timed out')
                # A filename or volume name must never grant anonymous file access.
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{port}/artifacts/',timeout=2)
                    raise RuntimeError('Anonymous access unexpectedly permitted')
                except urllib.error.HTTPError as e:
                    if e.code not in (401,403,404):raise
                env={**os.environ,'PULSE_TEST_STORAGE_CONFIG':str(storage)}
                result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,env=env)
                return result.returncode
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':sys.exit(main())
