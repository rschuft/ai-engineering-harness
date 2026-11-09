"""A stand-in for a git launcher, used only by the tests (plan leaf F-09.4, round 4).

Git for Windows' ``cmd\\git.exe`` is a launcher: it runs the real git as its child, which
inherits the launcher's standard handles, and exits with the child's status. Killing the
launcher alone leaves the child running on the inherited pipes. This script does the same
thing with any command, on any platform:

    python -I -B fake_launcher.py PIDFILE ARGV...

It starts ARGV as its child with its own standard input, output and error, writes the child's
process id to PIDFILE (written whole: a temporary name, then renamed), waits for the child and
exits with its status. Standard library only.
"""
import os
import subprocess
import sys


def main():
    pidfile, argv = sys.argv[1], sys.argv[2:]
    child = subprocess.Popen(argv, stdin=0, stdout=1, stderr=2)
    with open(pidfile + '.tmp', 'w', encoding='ascii') as out:
        out.write(str(child.pid))
    os.replace(pidfile + '.tmp', pidfile)
    return child.wait()


if __name__ == '__main__':
    sys.exit(main())
