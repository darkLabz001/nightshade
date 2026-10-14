#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys

mode=sys.argv[1]
if mode=='health':
    print('NIGHTSHADE / VITAL SIGNS\n')
    print('Host:',socket.gethostname())
    print('Uptime:',Path('/proc/uptime').read_text().split()[0],'seconds')
    try:print('Temperature:',int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000,'C')
    except OSError:print('Temperature unavailable')
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith(('MemTotal:','MemAvailable:')):print(line)
    d=shutil.disk_usage('/');print('Free storage:',round(d.free/1024**3,1),'GiB')
elif mode=='gateway':
    p=subprocess.run(['ip','-j','route','show','default'],capture_output=True,text=True,check=True)
    routes=json.loads(p.stdout)
    if not routes or not routes[0].get('gateway'):sys.exit('No default gateway found')
    gateway=routes[0]['gateway'];print('Gateway:',gateway,flush=True)
    sys.exit(subprocess.run(['ping','-n','-c','4','-W','2',gateway]).returncode)
elif mode=='dns':
    print('Resolving example.com',flush=True)
    for ip in sorted({r[4][0] for r in socket.getaddrinfo('example.com',443)}):print(ip)
else:sys.exit('Unknown diagnostic')
