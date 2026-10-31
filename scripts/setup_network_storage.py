#!/usr/bin/env python3
"""Prepare private Copyparty storage in a new directory. Does not start or publish services."""
import argparse
import hashlib
import json
import os
import secrets
import urllib.request
from pathlib import Path

VERSION='1.20.26'
SHA256='8f9a0def8a9c15252a06395781ec083372043b60caa80fb33c3d6dafa7f1b40a'
URL=f'https://github.com/9001/copyparty/releases/download/v{VERSION}/copyparty-sfx.py'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',help='New private service directory (must not exist)')
    ap.add_argument('--port',type=int,default=4102)
    args=ap.parse_args()
    if not 1024<=args.port<=65535:ap.error('port must be 1024..65535')
    root=Path(args.directory).expanduser().absolute()
    if any(c in str(root) for c in ('\n','\r','#','[',']')):ap.error('unsupported configuration path')
    os.umask(0o077)
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    with urllib.request.urlopen(URL,timeout=60) as response:
        binary=response.read(2*1024*1024)
    if hashlib.sha256(binary).hexdigest()!=SHA256:
        raise SystemExit('Copyparty checksum mismatch; no executable written')
    (root/'copyparty-sfx.py').write_bytes(binary)
    (root/'files').mkdir(mode=0o700)
    password=secrets.token_urlsafe(32)
    (root/'credentials.json').write_text(json.dumps({'username':'pulse','password':password})+'\n')
    (root/'copyparty.conf').write_text(f'''[global]
  i: 127.0.0.1
  p: {args.port}
  no-thumb
  no-mtag-ff
  no-robots
  no-readme
  no-logues
  no-html
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
    vmaxn: 10000
    nosub
''')
    fragment={'agent_network':{'enabled':True,'artifact_ttl_seconds':86400,'storage':{'url':f'http://127.0.0.1:{args.port}/artifacts',
                                                        'credentials_file':str(root/'credentials.json')}}}
    (root/'pulse-config-fragment.json').write_text(json.dumps(fragment,indent=2)+'\n')
    (root/'pulse-storage.service').write_text(f'''[Unit]
Description=Pulse private artifact storage (Copyparty {VERSION})
After=network-online.target
[Service]
Type=simple
UMask=0077
ExecStart=/usr/bin/python3 "{root}/copyparty-sfx.py" -c "{root}/copyparty.conf"
WorkingDirectory={root}
Restart=on-failure
RestartSec=5
MemoryMax=256M
NoNewPrivileges=yes
[Install]
WantedBy=default.target
''')
    print(f'Prepared Copyparty {VERSION} in {root}. Credentials saved privately, never printed.')
    print('No service started, no port exposed, and no Pulse configuration changed.')


if __name__=='__main__':main()
