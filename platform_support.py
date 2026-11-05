"""Small native OS adapters; no third-party runtime dependencies."""
import errno
import os
from pathlib import Path


def lock_exclusive(fd):
    """Nonblocking process lock, released by closing the descriptor."""
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(errno.EAGAIN, 'lock is held') from None
            raise
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def open_lock(path):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    return os.open(path, flags, 0o600)


if os.name == 'nt':
    import ctypes
    from ctypes import wintypes as wt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class FileInfo(ctypes.Structure):
        _fields_ = [('attributes', wt.DWORD), ('created', wt.FILETIME),
                    ('accessed', wt.FILETIME), ('written', wt.FILETIME),
                    ('volume', wt.DWORD), ('size_high', wt.DWORD),
                    ('size_low', wt.DWORD), ('links', wt.DWORD),
                    ('index_high', wt.DWORD), ('index_low', wt.DWORD)]

    kernel.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID,
                                   wt.DWORD, wt.DWORD, wt.HANDLE]
    kernel.CreateFileW.restype = wt.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wt.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wt.BOOL
    kernel.GetFileType.argtypes = [wt.HANDLE]
    kernel.GetFileType.restype = wt.DWORD
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CloseHandle.restype = wt.BOOL


class WindowsPath:
    """Pin every local path component against rename; reject all reparse points.

    Each open excludes FILE_SHARE_DELETE. Ancestors stay open until the final
    file handle is acquired or a directory listing finishes. Only drive-letter
    paths are accepted; no UNC, device namespaces, ADS or DOS device aliases.
    """
    def __init__(self, path, directory=False):
        self.path = Path(path).expanduser()
        self.directory = directory
        self.handles = []

    def __enter__(self):
        path = self.path
        if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ':':
            raise ValueError('A local absolute drive-letter path is required')
        for part in path.parts[1:]:
            base = part.split('.')[0].upper()
            if (part in ('.', '..') or part.endswith((' ', '.')) or
                    any(c in part for c in ':<>"|?*') or
                    any(ord(c) < 32 for c in part) or
                    base in ('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$') or
                    base in {f'{p}{n}' for p in ('COM', 'LPT') for n in '123456789¹²³'}):
                raise ValueError('Unsafe Windows path component')
        current = Path(path.anchor)
        try:
            for index, part in enumerate(('', *path.parts[1:])):
                if part:
                    current /= part
                is_directory = index < len(path.parts) - 1 or self.directory
                # GENERIC_READ for the final file; metadata-only for directories.
                access = 0 if is_directory else 0x80000000
                handle = kernel.CreateFileW(str(current), access, 3, None, 3,
                                             0x02000000 | 0x00200000, None)
                if handle == wt.HANDLE(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles.append(handle)
                info = FileInfo()
                if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.GetFileType(handle) != 1 or info.attributes & 0x400:
                    raise ValueError('Reparse points and non-disk files are not allowed')
                if bool(info.attributes & 0x10) != is_directory:
                    raise ValueError('Unexpected file type')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def file_descriptor(self):
        import msvcrt
        handle = self.handles[-1]
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        self.handles.pop()  # CRT now owns the handle, including on close(fd).
        return fd

    def __exit__(self, *exc):
        for handle in reversed(self.handles):
            kernel.CloseHandle(handle)
        self.handles.clear()


def open_regular_source(path):
    """Open an explicitly selected upload without following its final symlink."""
    if os.name == 'nt':
        with WindowsPath(Path(os.path.abspath(Path(path).expanduser()))) as opened:
            return opened.file_descriptor()
    return os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)


if os.name == 'nt':
    class BasicJobLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wt.DWORD), ('min_working_set', ctypes.c_size_t),
                    ('max_working_set', ctypes.c_size_t), ('active_processes', wt.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wt.DWORD),
                    ('scheduling', wt.DWORD)]

    class JobIO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class ExtendedJobLimits(ctypes.Structure):
        _fields_ = [('basic', BasicJobLimits), ('io', JobIO),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

    kernel.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    kernel.SetInformationJobObject.restype = wt.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.AssignProcessToJobObject.restype = wt.BOOL
    kernel.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    kernel.CreateEventW.restype = wt.HANDLE
    kernel.SetEvent.argtypes = [wt.HANDLE]
    kernel.SetEvent.restype = wt.BOOL
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.WaitForSingleObject.restype = wt.DWORD


class WindowsJob:
    """Gate runtime launch until its wrapper belongs to a kill-on-close job."""
    def __init__(self):
        self.job = kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        self.gate = None
        try:
            limits = ExtendedJobLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.gate = kernel.CreateEventW(None, True, False, None)
            if not self.gate:
                raise ctypes.WinError(ctypes.get_last_error())
            os.set_handle_inheritable(self.gate, True)
        except BaseException:
            self.close()
            raise

    def launch(self, argv, **kwargs):
        import subprocess
        import sys
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {'handle_list': [self.gate]}
        wrapper = Path(__file__).with_name('network_worker_child.py')
        process = subprocess.Popen([sys.executable, str(wrapper), str(self.gate), *argv],
                                   startupinfo=startup, close_fds=True, **kwargs)
        try:
            if not kernel.AssignProcessToJobObject(self.job, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.SetEvent(self.gate):
                raise ctypes.WinError(ctypes.get_last_error())
            return process
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
            raise
        finally:
            kernel.CloseHandle(self.gate)
            self.gate = None

    def close(self):
        if self.job:
            kernel.CloseHandle(self.job)  # Terminates the wrapper and its descendants.
            self.job = None
        if self.gate:
            kernel.CloseHandle(self.gate)
            self.gate = None
