#!/usr/bin/env python3
"""OTA update for Nightshade.

Starts the nightshade-ota systemd unit and tails its log, so
the panel shows live progress. The unit runs as a root service
outside this app's sandbox on purpose: pulling and installing
means writing to /opt, /etc and the home tree, which the
sandboxed service cannot touch. The unit only ever runs the
fixed apply script from the repository, and only root can
start a systemd unit.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = '/opt/nightshade'
STATE = Path.home() / '.local' / 'state' / 'nightshade'
LOG = STATE / 'ota.log'
DONE = '__OTA_DONE__'
REMOTE = 'https://github.com/darkblightHQ/nightshade.git'


def run(argv, timeout=30):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def update():
    print('NIGHTSHADE / OTA UPDATE\n')
    if not Path(REPO + '/.git').exists():
        print('/opt/nightshade is not a git clone yet.')
        print('Clone it first (as root):')
        print(f'sudo git clone {REMOTE} /opt/nightshade')
        return
    LOG.write_text('')
    rc, out = run(['sudo', '-n', 'systemctl', '--no-block',
                   'start', 'nightshade-ota'], 20)
    if rc != 0:
        print('Could not start the update unit:')
        for line in out.splitlines()[:4]:
            print(line)
        return
    print('Pulling from GitHub…\n')
    seen = 0
    deadline = time.time() + 280
    while time.time() < deadline:
        if LOG.exists():
            text = LOG.read_text(errors='replace')
            complete = text[:text.rfind('\n') + 1] if '\n' in text else ''
            if len(complete) > seen:
                for line in complete[seen:].splitlines():
                    print(line)
                seen = len(complete)
            if DONE in text:
                break
        time.sleep(1)
    else:
        print('\nStill running — check the log again shortly')


mode = sys.argv[1] if len(sys.argv) > 1 else 'update'
if mode == 'update':
    update()
else:
    sys.exit('Unknown ota tool')
