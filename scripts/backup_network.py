#!/usr/bin/env python3
"""Back up Pulse and its registered local Copyparty artifacts under the transfer lock."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from agent_network import storage_guard
from backup import backup_database


def private_copy(source, target):
    with open(source, 'rb') as src, open(target, 'xb') as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    os.chmod(target, 0o600)


def snapshot(storage_root, destination, token_directory=None, keep=7):
    os.umask(0o077)
    storage_root, destination = Path(storage_root).resolve(), Path(destination).resolve()
    if keep < 1:
        raise ValueError('keep must be positive')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    name = 'network-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4)
    pending, final = destination / ('.' + name), destination / name
    pending.mkdir(mode=0o700)
    try:
        # Upload registration and physical deletion both hold this lock. A grant
        # can change during the snapshot, but its bytes cannot disappear until
        # the snapshot finishes. Only immutable objects referenced by this DB
        # snapshot are copied, avoiding unrelated files and excess storage.
        with storage_guard(server):
            db = backup_database(server.DB_PATH, pending)
            with sqlite3.connect(db) as con:
                # Temporary bytes must not outlive their 24-hour policy in backups.
                con.execute('DELETE FROM workspace_files')
                con.execute('DELETE FROM network_artifacts WHERE expires_at>0')
                con.execute('DELETE FROM network_storage_gc')
                rows = con.execute('SELECT object_key,size,sha256 FROM network_artifacts').fetchall()
            if shutil.disk_usage(destination).free < sum(row[1] for row in rows) + 2 * 1024**3:
                raise ValueError('insufficient free space for artifact snapshot')
            objects = pending / 'objects'
            objects.mkdir(mode=0o700)
            for key, size, digest in rows:
                if not re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{64}', key):
                    raise ValueError('invalid artifact key')
                source = storage_root / 'files' / key
                if source.is_symlink() or not source.is_file():
                    raise ValueError('registered artifact is missing or unsafe')
                target = objects / key
                private_copy(source, target)
                with target.open('rb') as data:
                    checksum = hashlib.sha256()
                    for chunk in iter(lambda: data.read(1024 * 1024), b''):
                        checksum.update(chunk)
                    actual = checksum.hexdigest()
                if target.stat().st_size != size or actual != digest:
                    raise ValueError('artifact integrity check failed')
            private_copy(server.CONFIG_PATH, pending / 'pulse-config.json')
            private_copy(storage_root / 'copyparty.conf', pending / 'copyparty.conf')
            private_copy(storage_root / 'credentials.json', pending / 'storage-credentials.json')
            if token_directory:
                tokens = pending / 'network-tokens'
                tokens.mkdir(mode=0o700)
                for token in Path(token_directory).glob('*.token'):
                    if token.is_symlink() or not token.is_file():
                        raise ValueError('unsafe token file')
                    private_copy(token, tokens / token.name)
            (pending / 'manifest.json').write_text(json.dumps({
                'database': db.name, 'artifacts': len(rows), 'bytes': sum(row[1] for row in rows),
                'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'restore': 'Stop Pulse, connector and storage. Restore database/config and objects to storage files/. Preserve failed state and reconcile later writes first.',
            }, indent=2) + '\n')
        os.replace(pending, final)
    except BaseException:
        shutil.rmtree(pending)
        raise
    snapshots = sorted(p for p in destination.glob('network-*') if p.is_dir() and not p.is_symlink())
    for old in snapshots[:-keep]:
        shutil.rmtree(old)
    return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage-root', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--token-directory')
    parser.add_argument('--keep', type=int, default=7)
    args = parser.parse_args()
    try:
        print('Network snapshot written to', snapshot(args.storage_root, args.destination, args.token_directory, args.keep))
    except Exception:
        sys.exit('Network snapshot failed; check local paths, free space and artifact integrity. No successful snapshot published.')
