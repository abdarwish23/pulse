"""Native OS boundaries: real process locks, path confinement and binary uploads."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from platform_support import lock_exclusive, open_lock, open_regular_source
from network_connector import read_shared, list_shared


class PlatformTests(unittest.TestCase):
    def test_lock_excludes_other_processes_and_recovers_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'instance.lock'
            code = ('import sys,time; from platform_support import open_lock,lock_exclusive; '
                    'fd=open_lock(sys.argv[1]); lock_exclusive(fd); '
                    'print("locked",flush=True); time.sleep(60)')
            child = subprocess.Popen([sys.executable, '-c', code, str(path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                fd = open_lock(path)
                try:
                    with self.assertRaises(BlockingIOError):
                        lock_exclusive(fd)
                finally:
                    os.close(fd)
            finally:
                child.terminate()
                child.wait(timeout=5)
                child.stdout.close()
            fd = open_lock(path)
            try:
                lock_exclusive(fd)
            finally:
                os.close(fd)

    def test_explicit_upload_rejects_symlink_and_preserves_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            data = bytes(range(256)) + b'\r\n\x1a'
            source = root / 'report 日本語.bin'
            source.write_bytes(data)
            fd = open_regular_source(source)
            with os.fdopen(fd, 'rb') as stream:
                self.assertEqual(stream.read(), data)
            link = root / 'link'
            link.symlink_to(source)
            with self.assertRaises((OSError, ValueError)):
                open_regular_source(link)

    @unittest.skipUnless(os.name == 'nt', 'native Windows path rules')
    def test_windows_aliases_junctions_and_parent_renames_are_denied(self):
        from platform_support import WindowsPath
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'folder').mkdir()
            (root / 'folder' / 'data').write_bytes(b'allowed')
            self.assertEqual(read_shared(root, 'folder/data'), b'allowed')
            for name in ('NUL', 'CON.txt', 'COM1', 'LPT1.txt', 'folder/data:stream',
                         'folder/data.', 'folder/data ', '../secret', '//server/share'):
                with self.subTest(name=name), self.assertRaises(Exception):
                    read_shared(root, name)
            junction = root / 'junction'
            subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(junction), str(root / 'folder')],
                           capture_output=True, check=True)
            try:
                with self.assertRaises((OSError, ValueError)):
                    read_shared(root, 'junction/data')
                with self.assertRaises((OSError, ValueError)):
                    open_regular_source(junction / 'data')
                self.assertNotIn('junction', [x['name'] for x in list_shared(root, '')['entries']])
            finally:
                junction.rmdir()
            with WindowsPath(root / 'folder', directory=True):
                with self.assertRaises(OSError):
                    (root / 'folder').rename(root / 'moved')
            # Handles were closed, so ordinary owner operations work again.
            (root / 'folder').rename(root / 'moved')
