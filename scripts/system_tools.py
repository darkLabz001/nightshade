#!/usr/bin/env python3
"""System section: quick one-shot views of what the Pi is doing."""
import subprocess
import sys
from pathlib import Path


def run(argv, timeout=10):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def processes():
    print('NIGHTSHADE / TOP PROCESSES\n')
    rc, out = run(['ps', '-eo', 'pcpu,pmem,comm', '--sort=-pcpu'])
    if rc != 0:
        print(out.strip() or 'ps failed'); return
    lines = out.splitlines()
    print(lines[0].strip())
    shown = 0
    for line in lines[1:]:
        # ps lists itself first while it sorts; the reading is meaningless
        # (hundreds of percent) so leave the sampler out of its own ranking.
        if line.split() and line.split()[-1] == 'ps':
            continue
        print(line.strip()); shown += 1
        if shown >= 8:
            break


def storage():
    print('NIGHTSHADE / STORAGE\n')
    rc, out = run(['df', '-h'])
    if rc != 0:
        print(out.strip() or 'df failed'); return
    for line in out.splitlines():
        name = line.split()[0] if line.split() else ''
        if line.startswith('Filesystem') or name.startswith(('/dev/', 'overlay', '/dev/root')):
            print(line.strip())


def usb():
    print('NIGHTSHADE / USB DEVICES\n')
    rc, out = run(['lsusb'], 10)
    print(out.strip() or 'No USB devices')


def radios():
    print('NIGHTSHADE / RADIO KILL SWITCHES\n')
    rc, out = run(['rfkill', 'list'], 10)
    print(out.strip() or 'rfkill unavailable')


def applog():
    print('NIGHTSHADE / APP LOG\n')
    log = Path.home() / '.local' / 'state' / 'nightshade' / 'console.log'
    if not log.exists():
        print('No log yet'); return
    lines = log.read_text(errors='replace').splitlines()
    for line in lines[-12:]:
        print(line)


mode = sys.argv[1] if len(sys.argv) > 1 else ''
if mode == 'processes':
    processes()
elif mode == 'storage':
    storage()
elif mode == 'usb-list':
    usb()
elif mode == 'rfkill':
    radios()
elif mode == 'nslog':
    applog()
else:
    sys.exit('Unknown system tool')
