#!/usr/bin/env python3
"""OTA update for Nightshade.

Pulls the GitHub repository on the device (/opt/nightshade is a git
clone of the project) and reinstalls both trees. Runs through the
passwordless sudo already configured for the service account: git and
install.sh need root because /opt is outside the sandboxed home tree.
"""
import subprocess
import sys
import time

REPO = '/opt/nightshade'


def run(argv, timeout=60):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def update():
    print('NIGHTSHADE / OTA UPDATE\n')
    rc, out = run(['sudo', '-n', 'git', '-C', REPO, 'pull', '--ff-only'], 120)
    lines = [line for line in out.splitlines() if line.strip()]
    for line in lines[:6]:
        print(line)
    if rc != 0:
        print('\nUpdate failed — is the network up?')
        return
    if 'Already up to date' in out:
        print('\nAlready the newest version')
        return
    print('\nApplying to both trees…')
    rc, out = run(['sudo', '-n', 'bash', REPO + '/deploy/install.sh'], 300)
    for line in [l for l in out.splitlines() if l.strip()][-6:]:
        print(line)
    if rc != 0:
        print('\nInstalled with errors; check the log')
        return
    print('\nUpdate applied — restarting now')
    sys.stdout.flush()
    # Let the panel show the final line before the restart takes
    # the running job (and the old code) down with it.
    time.sleep(3)
    run(['sudo', '-n', 'systemctl', 'restart', 'nightshade'], 30)


mode = sys.argv[1] if len(sys.argv) > 1 else 'update'
if mode == 'update':
    update()
else:
    sys.exit('Unknown ota tool')
