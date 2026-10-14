#!/usr/bin/env python3
"""Network section: address view plus raw-socket sweeps.

arp-scan and nmap's SYN scan need CAP_NET_RAW, so they run through the
passwordless sudo configured for the account the service runs as.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from wifi_tools import uplink_interface
except ImportError:
    def uplink_interface():
        return 'wlan0'

IPV4 = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')
STATE = Path.home() / '.local' / 'state' / 'nightshade'


def run(argv, timeout=20, cwd=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def gateway():
    rc, out = run(['ip', '-j', 'route', 'show', 'default'])
    if rc == 0:
        try:
            routes = json.loads(out) or []
            if routes and routes[0].get('gateway'):
                return routes[0]['gateway']
        except ValueError:
            pass
    return None


def interfaces():
    print('NIGHTSHADE / INTERFACES\n')
    rc, out = run(['ip', '-br', '-4', 'addr'])
    print(out.strip() or 'No IPv4 addresses')


def arp():
    print('NIGHTSHADE / LAN SWEEP\n')
    rc, out = run(['sudo', '-n', 'arp-scan', '--localnet'], 40)
    hosts = [line.split() for line in out.splitlines() if line.split() and IPV4.match(line.split()[0])]
    if not hosts:
        print(out.strip().splitlines()[-1] if out.strip() else 'No hosts found')
        return
    print(f'{len(hosts)} hosts answered\n')
    for parts in hosts[:12]:
        print(' '.join(parts[:2]))


def ports():
    print('NIGHTSHADE / PORT SCAN\n')
    target = gateway()
    if not target:
        print('No default gateway found'); return
    print(f'Target {target}')
    rc, out = run(['sudo', '-n', 'nmap', '-sS', '-Pn', '-T4', '--top-ports', '100', target], 60)
    opens = [line.strip() for line in out.splitlines() if '/tcp' in line and 'open' in line]
    for line in opens:
        print(line)
    print(f'\n{len(opens)} open of top 100 ports')


def responder():
    print('NIGHTSHADE / RESPONDER\n')
    print('AUTHORISED TESTING ONLY\n')
    uplink = uplink_interface() or 'wlan0'
    STATE.mkdir(parents=True, exist_ok=True)
    log = Path('/usr/share/responder/logs/Responder-Session.log')
    # the log is root-owned and appended across runs, so note
    # where this run starts and read only the new bytes back.
    offset = log.stat().st_size if log.exists() else 0
    print(f'Poisoning LLMNR/NBT-NS/mDNS + WPAD on {uplink}')
    print('Two minutes; events are logged\n')
    # responder hardcodes its log and SQLite database paths to
    # its package directory, so the unit makes that tree writable.
    rc, out = run(['sudo', '-n', 'timeout', '120', 'responder',
                   '-I', uplink, '-wv'], 150, cwd=str(STATE))
    events = []
    if log.exists() and log.stat().st_size > offset:
        rc, fresh = run(['sudo', '-n', 'tail', '-c',
                           str(offset + 1), str(log)], 15)
        events = [line.split(' - ', 1)[-1].strip()
                  for line in fresh.splitlines()
                  if ('Poisoned' in line or 'listening' in line
                      or 'Forwarding' in line)]
    if not events:
        print('No poisoner events this run')
        return
    for line in events[-8:]:
        print(line)
    print(f'\n{len(events)} events this run')


def sockets():
    print('NIGHTSHADE / SOCKETS\n')
    rc, out = run(['ss', '-tulpn'], 10)
    print('Listening')
    for line in out.splitlines()[:10]:
        if line.strip():
            print(line)
    rc, out = run(['ss', '-tn'], 10)
    print('\nEstablished TCP')
    for line in out.splitlines()[:6]:
        if line.strip():
            print(line)
    rc, out = run(['ip', 'route', 'show'], 10)
    print('\nRoutes')
    for line in out.splitlines():
        if line.strip():
            print(line)
    rc, out = run(['ip', 'neigh', 'show'], 10)
    print('\nARP cache')
    for line in out.splitlines()[:8]:
        if line.strip():
            print(line)


def deepscan():
    print('NIGHTSHADE / DEEP SCAN\n')
    target = gateway()
    if not target:
        print('No default gateway found'); return
    print(f'All ports, service detection on {target}')
    print('Bounded to about four minutes.\n')
    rc, out = run(['sudo', '-n', 'timeout', '280', 'nmap', '-sV', '-p-',
                   '-T4', '--max-retries', '1', '--host-timeout', '260s',
                   target], 300)
    # a full sweep lists thousands of closed ports; the panel only
    # gets the open ones (service/version included) and a count.
    opens = [line.strip() for line in out.splitlines()
             if '/tcp' in line and 'open' in line]
    for line in opens[:14]:
        print(line)
    print(f'\n{len(opens)} open of 65535 ports')


def http_watch():
    print('NIGHTSHADE / HTTP WATCH\n')
    uplink = uplink_interface() or 'wlan0'
    print(f'Watching HTTP on {uplink} for 15 seconds\n')
    rc, out = run(['sudo', '-n', 'timeout', '15', 'ngrep', '-d', uplink,
                   '-W', 'byline', '-q', 'Host:|GET |POST '], 25)
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        print('No HTTP traffic seen'); return
    for line in lines[:14]:
        print(line)


mode = sys.argv[1] if len(sys.argv) > 1 else ''
if mode == 'interfaces':
    interfaces()
elif mode == 'arp':
    arp()
elif mode == 'ports':
    ports()
elif mode == 'responder':
    responder()
elif mode == 'sockets':
    sockets()
elif mode == 'deep-scan':
    deepscan()
elif mode == 'http-watch':
    http_watch()
else:
    sys.exit('Unknown network tool')
