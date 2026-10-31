"""Dependency-free outbound client for the Pulse agent network."""
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, quote


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

    def workspace_upload(self, source, path, file_id=None):
        import stat
        import uuid
        from agent_network import relative_path
        relative_path(path)
        file_id = file_id or uuid.uuid4().hex
        self.workspace_id(file_id)
        # Explicit files only: no devices, FIFOs or symbolic links.
        fd=os.open(Path(source).expanduser(),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>32*1024*1024:
                raise ClientError('Upload requires a regular file up to 32 MiB')
            data=stream.read(32*1024*1024+1)
        if len(data)>32*1024*1024:
            raise ClientError('File exceeds 32 MiB')
        return self.call('POST','/workspace/files/'+file_id+'?path='+quote(path,safe=''),data=data,
                         extra={'Content-Type':'application/octet-stream','X-Content-SHA256':hashlib.sha256(data).hexdigest()})

    @staticmethod
    def workspace_id(file_id):
        import re
        if not isinstance(file_id,str) or not re.fullmatch('[0-9a-f]{32}',file_id):
            raise ClientError('Invalid workspace file id')
        return file_id

    def workspace_download(self, file_id, destination):
        data=self.call('GET','/workspace/files/'+self.workspace_id(file_id),download=True)
        path=Path(destination).expanduser()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {'path':str(path.absolute()),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
