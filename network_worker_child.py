"""Windows-only worker bootstrap. Wait for job assignment before any runtime runs."""
import os
import subprocess
import sys

from platform_support import kernel


def main():
    gate = int(sys.argv[1])
    try:
        if kernel.WaitForSingleObject(gate, 10000) != 0:
            return 125
    finally:
        kernel.CloseHandle(gate)
    env = dict(os.environ)
    # All pipes and text files passed to agent CLIs use UTF-8.
    env['PYTHONIOENCODING'] = 'utf-8'
    return subprocess.call(sys.argv[2:], env=env)


if __name__ == '__main__':
    sys.exit(main())
