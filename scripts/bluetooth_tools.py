#!/usr/bin/env python3
"""Bluetooth section for Nightshade.

Discovery runs through BlueZ over D-Bus (bluetoothctl), which needs no special
privileges. The classic inquiry uses hcitool, which needs CAP_NET_RAW and so
runs through the passwordless sudo configured for the service account.
"""
import re
import subprocess
import sys

ANSI = re.compile(r'\x1b\[[0-9;]*m')
DEVICE = re.compile(r'Device ([0-9A-Fa-f:]{17})\s*(.*)$')
MAC = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


def run(argv, timeout=20):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, ANSI.sub('', (done.stdout or '') + (done.stderr or ''))
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def scan():
    print('NIGHTSHADE / BLUETOOTH SCAN\n')
    rc, out = run(['bluetoothctl', '--timeout', '12', 'scan', 'on'], 22)
    devices = {}
    for line in out.splitlines():
        match = DEVICE.search(line)
        if not match:
            continue
        address, name = match.group(1).upper(), match.group(2).strip()
        if name or address not in devices:
            devices[address] = name or devices.get(address, '')
    print(f'{len(devices)} devices found\n')
    for address, name in list(devices.items())[:12]:
        print(f'{address} {name}'.strip())


def classic():
    print('NIGHTSHADE / CLASSIC INQUIRY\n')
    rc, out = run(['sudo', '-n', 'timeout', '15', 'hcitool', 'scan'], 25)
    found = []
    for line in out.splitlines():
        parts = line.split()
        if parts and MAC.match(parts[0]):
            found.append(parts)
    print(f'{len(found)} devices found\n')
    for parts in found[:12]:
        print(' '.join(parts[:2]))


def info():
    print('NIGHTSHADE / BLUETOOTH ADAPTER\n')
    rc, out = run(['bluetoothctl', 'show'], 8)
    print(out.strip() or 'Controller unavailable')
    rc, out = run(['hciconfig', '-a'], 8)
    details = [line.strip() for line in out.splitlines() if line.strip()]
    if details:
        print()
        print('\n'.join(details[:6]))


def monitor_traffic():
    print('NIGHTSHADE / HCI MONITOR\n')
    rc, out = run(['sudo', '-n', 'timeout', '8', 'btmon'], 15)
    events = {}
    for line in out.splitlines():
        if 'HCI Event:' not in line:
            continue
        name = line.split('HCI Event:', 1)[1]
        name = name.split('(', 1)[0].strip()
        events[name] = events.get(name, 0) + 1
    total = sum(events.values())
    if not total:
        print('No HCI traffic captured'); return
    print(f'{total} HCI events in 8s\n')
    for name, count in sorted(events.items(), key=lambda item: item[1], reverse=True)[:10]:
        print(f'{count:>4}  {name}')


def devices():
    print('NIGHTSHADE / BLUETOOTH DEVICES\n')
    rc, out = run(['bluetoothctl', 'devices'], 10)
    known = [line for line in out.splitlines() if line.startswith('Device ')]
    rc, paired = run(['bluetoothctl', 'paired-devices'], 10)
    pairs = [line for line in paired.splitlines() if line.startswith('Device ')]
    if not pairs and not known:
        print('No devices seen yet'); return
    print(f'{len(pairs)} paired, {len(known)} known\n')
    for line in pairs[:6]:
        print('P ' + line[7:])
    for line in known:
        if line not in pairs:
            print('  ' + line[7:])


def gatt():
    print('NIGHTSHADE / GATT READER\n')
    rc, out = run(['bluetoothctl', '--timeout', '10', 'scan', 'on'], 22)
    address = None
    for line in out.splitlines():
        match = DEVICE.search(line)
        if match:
            address = match.group(1).upper()
            break
    if not address:
        print('No Bluetooth device found'); return
    print(f'{address}\n')
    for addr_type in ('random', 'public'):
        rc, out = run(['sudo', '-n', 'timeout', '15', 'gatttool', '-b', address,
                       '-t', addr_type, '--primary'], 25)
        services = [line for line in out.splitlines()
                    if 'uuid' in line.lower() or 'handle' in line.lower()]
        if services:
            for line in services[:12]:
                print(line.strip())
            return
    print('Could not read services (device may be unconnectable)')
    for line in out.splitlines()[-4:]:
        if line.strip():
            print(line.strip())


def _discover(seconds=8):
    rc, out = run(['bluetoothctl', '--timeout', str(seconds), 'scan', 'on'],
                  seconds + 12)
    for line in out.splitlines():
        match = DEVICE.search(line)
        if match:
            return match.group(1).upper()
    return None


def bt_ping():
    print('NIGHTSHADE / BLUETOOTH PING\n')
    address = _discover()
    if not address:
        print('No Bluetooth device found'); return
    print(f'{address}\n')
    rc, out = run(['sudo', '-n', 'l2ping', '-c', '3', address], 30)
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        print('No reply'); return
    for line in lines[:8]:
        print(line)


def bt_sdp():
    print('NIGHTSHADE / SDP BROWSE\n')
    address = _discover()
    if not address:
        print('No Bluetooth device found'); return
    print(f'{address}\n')
    rc, out = run(['sudo', '-n', 'timeout', '20', 'sdptool', 'browse',
                   address], 35)
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        print('No service records (device may be unconnectable)'); return
    for line in lines[:14]:
        print(line)


mode = sys.argv[1] if len(sys.argv) > 1 else ''
if mode == 'scan':
    scan()
elif mode == 'classic':
    classic()
elif mode == 'info':
    info()
elif mode == 'bt-monitor':
    monitor_traffic()
elif mode == 'bt-devices':
    devices()
elif mode == 'ble-gatt':
    gatt()
elif mode == 'bt-ping':
    bt_ping()
elif mode == 'bt-sdp':
    bt_sdp()
else:
    sys.exit('Unknown bluetooth tool')
