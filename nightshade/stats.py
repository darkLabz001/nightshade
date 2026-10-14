import json
import os
from pathlib import Path
import shutil
import socket
import subprocess


def run(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired): return ''


class Stats:
    def __init__(self): self.previous = None

    def collect(self):
        result = {'hostname':socket.gethostname(), 'cpu':0, 'temperature':None,
                  'memory':0, 'disk':0, 'uptime':'—', 'addresses':[], 'gateway':'—',
                  'ssid':'—', 'tailscale':'Unavailable', 'tail_ip':'—'}
        try:
            ticks = list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
            total, idle = sum(ticks), ticks[3] + ticks[4]
            if self.previous:
                dt = total-self.previous[0]
                result['cpu'] = round(100*(1-(idle-self.previous[1])/dt),1) if dt else 0
            self.previous = total,idle
            mem = {l.split(':')[0]:int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines()}
            result['memory'] = round(100*(1-mem['MemAvailable']/mem['MemTotal']),1)
            seconds = int(float(Path('/proc/uptime').read_text().split()[0]))
            result['uptime'] = f'{seconds//3600}h {(seconds%3600)//60}m'
            disk = shutil.disk_usage('/')
            result['disk'] = round(100*disk.used/disk.total,1)
        except (OSError, ValueError, KeyError): pass
        try: result['temperature'] = round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000,1)
        except (OSError, ValueError): pass
        try:
            for iface in json.loads(run(['ip','-j','-4','addr']) or '[]'):
                if iface['ifname']=='lo': continue
                for address in iface.get('addr_info',[]):
                    result['addresses'].append({'interface':iface['ifname'],'ip':address['local']})
            routes = json.loads(run(['ip','-j','route','show','default']) or '[]')
            if routes: result['gateway'] = routes[0].get('gateway','—')
            tail = json.loads(run(['tailscale','status','--json']) or '{}')
            result['tailscale'] = tail.get('BackendState','Unavailable')
            result['tail_ip'] = next((ip for ip in (tail.get('TailscaleIPs') or []) if ':' not in ip),'—')
            result['ssid'] = run(['iwgetid','-r']) or '—'
            if result['ssid']=='—':
                cached=run(['nmcli','-t','-f','ACTIVE,SSID','device','wifi','list','--rescan','no'])
                result['ssid']=next((line[4:].replace(r'\:',':') for line in cached.splitlines() if line.startswith('yes:')),'—')
        except (ValueError,KeyError): pass
        return result
