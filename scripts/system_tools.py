#!/usr/bin/env python3
"""System section: quick one-shot views of what the Pi is doing."""
import subprocess
import sys
import time
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


def update_check():
    print('NIGHTSHADE / UPDATE CHECK\n')
    repo = Path('/opt/nightshade')
    if not (repo / '.git').exists():
        print('Not a git clone -- no OTA on this device')
        return
    # ls-remote only reads the repository and writes nothing,
    # so it is safe inside the service sandbox.
    rc, out = run(['git', '-C', str(repo), 'ls-remote',
                   'origin', '-h', 'refs/heads/main'], 25)
    remote = ''
    if rc == 0 and out.strip():
        remote = out.strip().split()[0]
    rc, out = run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], 10)
    local = out.strip() if rc == 0 else ''
    print(f'Installed : {local[:12] or "unknown"}')
    if not remote:
        print('Could not reach GitHub'); return
    print(f'Available : {remote[:12]}')
    if local == remote:
        print('\nUp to date')
    else:
        print('\nUpdate waiting -- Settings -> Update from GitHub')


def power(action):
    label = 'Reboot' if action == 'reboot' else 'Shut down'
    print(f'NIGHTSHADE / {label.upper()}\n')
    if action == 'reboot':
        print('Rebooting in 5 seconds -- the panel will go dark,')
        print('SSH and the dashboard come back on their own.')
    else:
        print('Shutting down in 5 seconds -- the panel will go dark.')
        print('Unplug and replug power to start again.')
    time.sleep(5)
    rc, out = run(['sudo', '-n', 'systemctl', action], 30)
    if rc != 0:
        print(out.strip() or f'{action} failed')


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
elif mode == 'update-check':
    update_check()
elif mode == 'reboot':
    power('reboot')
elif mode == 'shutdown':
    power('shutdown')
else:
    sys.exit('Unknown system tool')
