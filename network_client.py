"""Dependency-free outbound client for the Pulse agent network."""
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


class ClientError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('Redirect refused; check Pulse URL and Cloudflare Access configuration')


class Client:
    def __init__(self, url=None, token_file=None):
        self.url = (url or os.environ.get('PULSE_URL', 'http://127.0.0.1:4100')).rstrip('/')
        u = urlparse(self.url)
        if not (u.scheme=='https' or (u.scheme=='http' and u.hostname in ('127.0.0.1','::1','localhost'))):
            raise ClientError('HTTPS is required except on loopback')
        if u.username or u.password or u.query or u.fragment or u.path:
            raise ClientError('Pulse URL must be an origin without credentials, path or query')
        filename = token_file or os.environ.get('PULSE_NETWORK_TOKEN_FILE')
        if not filename:
            raise ClientError('Set PULSE_NETWORK_TOKEN_FILE to an enrolled network credential')
        try:
            self.token = Path(filename).expanduser().read_text().strip()
        except OSError:
            raise ClientError('Network token file unavailable') from None
        if not self.token.startswith('pn_'):
            raise ClientError('A dedicated network token is required')
        self.opener = urllib.request.build_opener(NoRedirect())

    def headers(self):
        headers = {'Authorization': 'Bearer '+self.token, 'Content-Type':'application/json',
                   'User-Agent': 'Pulse-Agent-Network/1.0'}
        if urlparse(self.url).scheme != 'https':
            return headers
        cid = os.environ.get('PULSE_CF_ACCESS_CLIENT_ID')
        secret = os.environ.get('PULSE_CF_ACCESS_CLIENT_SECRET')
        f = Path(os.environ.get('PULSE_CF_ACCESS_FILE', '~/.config/pulse/cf-access.json')).expanduser()
        if not (cid and secret) and f.exists():
            try:
                d=json.loads(f.read_text()); cid,secret=d.get('client_id'),d.get('client_secret')
            except (ValueError,OSError):
                raise ClientError('Invalid Cloudflare Access credential file') from None
        if cid and secret:
            headers.update({'CF-Access-Client-Id':cid,'CF-Access-Client-Secret':secret})
        return headers

    def call(self, method, path, body=None, data=None, extra=None, download=False):
        headers=self.headers()
        if extra:
            headers.update(extra)
        if data is None and body is not None:
            data=json.dumps(body).encode()
        req=urllib.request.Request(self.url+'/api/network'+path, method=method, data=data, headers=headers)
        try:
            with self.opener.open(req,timeout=45) as r:
                limit=32*1024*1024 if download else 4*1024*1024
                value=r.read(limit+1)
                if len(value)>limit:
                    raise ClientError('Response too large')
                if download:
                    if hashlib.sha256(value).hexdigest()!=r.headers.get('X-Content-SHA256'):
                        raise ClientError('Artifact checksum mismatch')
                    return value
                try:
                    return json.loads(value)
                except ValueError:
                    raise ClientError('Expected Pulse JSON; check URL and Access policy') from None
        except urllib.error.HTTPError as e:
            try:
                msg=json.loads(e.read(65536)).get('error','Request failed')
            except ValueError:
                msg='Request rejected; check URL and Access policy'
            raise ClientError(f'{msg} (HTTP {e.code})', e.code) from None
        except (urllib.error.URLError,OSError):
            raise ClientError('Pulse connection unavailable') from None

    def upload(self, job, data):
        return self.call('POST','/requests/'+job['id']+'/artifact',data=data,extra={
            'Content-Type':'application/octet-stream','X-Pulse-Session':job['session_id'],
            'X-Pulse-Lease':job['lease'],'X-Content-SHA256':hashlib.sha256(data).hexdigest()})

    def download(self, request_id, destination):
        if not isinstance(request_id,str) or len(request_id)!=32 or any(c not in '0123456789abcdef' for c in request_id):
            raise ClientError('Invalid request id')
        data=self.call('GET','/artifacts/'+request_id,download=True)
        # Explicit local output, exclusive creation, no clobbering or symlink following.
        path=Path(destination).expanduser()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {'path':str(path.absolute()),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
