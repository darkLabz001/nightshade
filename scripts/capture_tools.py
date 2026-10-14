#!/usr/bin/env python3
"""Packet-capture section for Nightshade.

tcpdump and capinfos need CAP_NET_RAW, so they run through the passwordless
sudo configured for the service account. Captures are written under the
service state directory (~/.local/state/nightshade/captures), the only place
the sandboxed service can write.
"""
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / '.local' / 'state' / 'nightshade'
CAPTURES = STATE / 'captures'


def run(argv, timeout=25):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def sniff():
    print('NIGHTSHADE / PACKET SNIFF\n')
    CAPTURES.mkdir(parents=True, exist_ok=True)
    out = CAPTURES / 'tcpdump.pcap'
    print('Capturing 15s on wlan0...\n')
    run(['sudo', '-n', 'timeout', '15', 'tcpdump', '-i', 'wlan0', '-nn', '-w', str(out)], 25)
    rc, data = run(['sudo', '-n', 'tcpdump', '-nn', '-r', str(out)], 20)
    lines = [line for line in data.splitlines() if line.strip()]
    size = out.stat().st_size if out.exists() else 0
    print(f'{len(lines)} packets, {size // 1024}K -> {out.name}\n')
    for line in lines[:8]:
        # tcpdump prefixes each line with a timestamp; drop it for the panel.
        print(line.split(' ', 1)[-1] if ' IP ' in line or ' ARP' in line else line)


def pcaps():
    print('NIGHTSHADE / SAVED CAPTURES\n')
    files = [f for f in CAPTURES.glob('*') if f.is_file()] if CAPTURES.exists() else []
    if not files:
        print('No captures yet'); return
    files.sort(key=lambda f: f.stat().st_mtime)
    for item in files[-14:]:
        print(f'{item.name:<26} {item.stat().st_size // 1024}K')


def last():
    print('NIGHTSHADE / CAPTURE SUMMARY\n')
    files = [f for f in CAPTURES.glob('*') if f.is_file()] if CAPTURES.exists() else []
    if not files:
        print('No captures yet'); return
    newest = max(files, key=lambda f: f.stat().st_mtime)
    print(newest.name + '\n')
    rc, out = run(['sudo', '-n', 'capinfos', str(newest)], 20)
    wanted = ('Number of packets', 'Capture duration', 'Average packet size',
              'File size', 'Packet size limit')
    for line in out.splitlines():
        if line.strip().startswith(wanted):
            print(line.strip())


def analyse():
    print('NIGHTSHADE / PACKET ANALYSIS\n')
    files = [f for f in CAPTURES.glob('*') if f.is_file()] if CAPTURES.exists() else []
    if not files:
        print('No captures yet'); return
    newest = max(files, key=lambda f: f.stat().st_mtime)
    print(newest.name + '\n')
    rc, out = run(['sudo', '-n', 'tshark', '-r', str(newest), '-q', '-z', 'io,phs'], 40)
    print('Protocols')
    for line in out.splitlines()[:14]:
        if line.strip():
            print(line)
    rc, out = run(['sudo', '-n', 'tshark', '-r', str(newest), '-q', '-z', 'conv,ip'], 40)
    print('\nTop conversations')
    for line in out.splitlines()[:8]:
        if line.strip():
            print(line)


def stream():
    print('NIGHTSHADE / STREAM FOLLOW\n')
    files = [f for f in CAPTURES.glob('*') if f.is_file()] if CAPTURES.exists() else []
    if not files:
        print('No captures yet'); return
    newest = max(files, key=lambda f: f.stat().st_mtime)
    print(newest.name + '\n')
    rc, out = run(['sudo', '-n', 'tshark', '-r', str(newest), '-q',
                   '-z', 'follow,tcp,ascii,0'], 40)
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        print('No TCP stream in this capture'); return
    for line in lines[:24]:
        print(line)


mode = sys.argv[1] if len(sys.argv) > 1 else ''
if mode == 'sniff':
    sniff()
elif mode == 'pcaps':
    pcaps()
elif mode == 'last':
    last()
elif mode == 'analyse':
    analyse()
elif mode == 'stream':
    stream()
else:
    sys.exit('Unknown capture tool')
