"""Private WebDAV artifact storage (Copyparty), accessed only by the Pulse server."""
import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


class StorageError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StorageError('storage redirect refused')


class WebDAVStorage:
    def __init__(self, config):
        self.url = config.get('url', '').rstrip('/')
        u = urlparse(self.url)
        if not (u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('127.0.0.1', '::1', 'localhost'))):
            raise StorageError('storage requires HTTPS or loopback HTTP')
        if u.username or u.password or u.query or u.fragment:
            raise StorageError('invalid storage URL')
        try:
            credentials = json.loads(Path(config['credentials_file']).expanduser().read_text())
            self.auth = 'Basic ' + base64.b64encode((credentials['username'] + ':' + credentials['password']).encode()).decode()
        except (OSError, KeyError, ValueError):
            raise StorageError('storage credential file unavailable') from None
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, key, data=None, limit=65536):
        if not re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{64}', key):
            raise StorageError('invalid storage key')
        req = urllib.request.Request(self.url + '/' + key, data=data, method=method,
                                     headers={'Authorization': self.auth, 'Content-Type': 'application/octet-stream'})
        try:
            with self.opener.open(req, timeout=30) as response:
                value = response.read(limit + 1)
                if len(value) > limit:
                    raise StorageError('storage response exceeds expected size')
                return value
        except urllib.error.HTTPError as e:
            if e.code == 404 and method in ('GET', 'DELETE'):
                return None
            raise StorageError(f'storage returned HTTP {e.code}') from None
        except (urllib.error.URLError, OSError):
            raise StorageError('storage unavailable') from None

    def put(self, key, data):
        self.request('PUT', key, data)
        actual = self.get(key, len(data))
        if actual is None or hashlib.sha256(actual).digest() != hashlib.sha256(data).digest():
            raise StorageError('stored artifact verification failed')

    def get(self, key, size):
        return self.request('GET', key, limit=size)

    def delete(self, key):
        self.request('DELETE', key)
