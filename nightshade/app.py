import argparse
import collections
import hmac
import io
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import signal
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import buzzer
from .hardware import Hat, PINS
from .runner import Runner
from .stats import Stats
from .ui import Model, PALETTES, apply_palette

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger('nightshade')


class _DurableFileHandler(logging.FileHandler):
    """File handler that fsyncs every record.

    The handheld is normally powered off by pulling the plug, so anything left
    in the page cache can vanish before it reaches the card. The app logs only
    a handful of lines per boot, so fsyncing each one is free and keeps the log
    readable after a hard cut.
    """

    def emit(self, record):
        super().emit(record)
        try:
            os.fsync(self.stream.fileno())
        except (OSError, ValueError, AttributeError):
            pass


class Application:
    def __init__(self, config, state_dir, simulate=False):
        self.config=config;self.state_dir=Path(state_dir);self.state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        key_path=self.state_dir/'access-key'
        if not key_path.exists():
            fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(24))
        self.access_key=key_path.read_text().strip()
        self.events=queue.Queue(maxsize=128);self.lock=threading.RLock();self.shutdown=threading.Event()
        self.rotation=config['display'].get('rotation',0)
        theme=None
        try:
            saved=json.loads((self.state_dir/'preferences.json').read_text())
            if saved.get('rotation') in (0,90,180,270):self.rotation=saved['rotation']
            theme=saved.get('theme')
        except (OSError,ValueError):pass
        self.runner=Runner(config['scripts'],ROOT)
        self.model=Model(config['scripts'],config.get('sections'),theme=theme)
        self.stats={};self.png=b'';self.hat=None;self.hardware_error='Simulation' if simulate else 'Initializing'
        if not simulate:
            try:
                self.hat=Hat({**config['display'],'rotation':self.rotation},self.emit)
                self.hardware_error=''
            except Exception as exc:
                self.hardware_error=str(exc);LOG.exception('Display unavailable; browser mode remains active')
        self.sessions={};self.attempts=collections.defaultdict(collections.deque)

    def emit(self,key):
        try:self.events.put_nowait(('key',key));return True
        except queue.Full:return False

    def snapshot(self):
        with self.lock:
            return {'page':self.model.page,'selected':self.model.index,'last_key':self.model.last_key,
                'hardware':bool(self.hat),'hardware_error':self.hardware_error,
                'rotation':self.rotation,'theme':self.model.theme,'display':self.config['display']['type'],'stats':dict(self.stats),
                'job':self.runner.snapshot(),'scripts':[{k:s.get(k,'') for k in ('id','name','description','section','page')} for s in self.config['scripts']],
                'sections':[{'id':s['id'],'name':s['name'],'description':s.get('description','')} for s in self.model.sections]}

    def sampler(self):
        source=Stats()
        while not self.shutdown.is_set():
            try:
                stats=source.collect()
                with self.lock:self.stats=stats
            except Exception:LOG.exception('Stats sample failed')
            self.shutdown.wait(3)

    def _save_preferences(self):
        # The handheld is usually powered off by pulling the plug, so
        # flush before the rename for the same reason the log handler
        # above fsyncs: a rotation or theme chosen just before a reboot
        # must not stay in the page cache and vanish.
        prefs={'rotation':self.rotation,'theme':self.model.theme}
        tmp=self.state_dir/'preferences.tmp'
        with open(tmp,'w') as handle:
            json.dump(prefs,handle)
            try:handle.flush();os.fsync(handle.fileno())
            except (OSError,ValueError,AttributeError):pass
        tmp.replace(self.state_dir/'preferences.json')

    def _save_access_key(self,new_key):
        # Atomic replace with an fsync first: the Pi Zero is often
        # power-cycled by pulling the plug, so a key change must not
        # sit only in the page cache.
        tmp=self.state_dir/'access-key.tmp'
        with open(tmp,'w') as handle:
            handle.write(new_key)
            try:handle.flush();os.fsync(handle.fileno())
            except (OSError,ValueError,AttributeError):pass
        os.chmod(tmp,0o600)
        tmp.replace(self.state_dir/'access-key')

    def _job_sounds(self,job):
        """Chime when a job ends; alert on a captured handshake."""
        running=job['status']=='running'
        if self._job_running and not running:
            buzzer.chime()
        if len(job['lines'])>self._job_lines:
            for line in job['lines'][self._job_lines:]:
                if 'handshake captured' in line.lower():
                    buzzer.alert()
                    break
        self._job_running=running;self._job_lines=len(job['lines'])

    def loop(self):
        last_frame=None;last_render=0
        self._job_running=False;self._job_lines=0
        while not self.shutdown.is_set():
            changed=False
            try:
                kind,value=self.events.get(timeout=.1)
                with self.lock:
                    if kind=='run':
                        if self.runner.start(value):self.model.page='output';self.model.scroll=0
                    else:
                        buzzer.click()
                        action=self.model.key(value,self.runner)
                        if action=='rotate':
                            self.rotation=(self.rotation+90)%360
                            if self.hat:self.hat.rotation=self.rotation
                            self._save_preferences();last_frame=None
                        elif action=='theme':
                            names=list(PALETTES)
                            self.model.theme=names[(names.index(self.model.theme)+1)%len(names)]
                            apply_palette(self.model.theme)
                            self._save_preferences();last_frame=None
                changed=True
            except queue.Empty:pass
            if changed or time.monotonic()-last_render>=.5:
                with self.lock:
                    job=self.runner.snapshot()
                    image=self.model.render(self.stats,job,bool(self.hat),self.rotation)
                self._job_sounds(job)
                frame=image.tobytes()
                if frame!=last_frame:
                    buf=io.BytesIO();image.save(buf,format='PNG')
                    with self.lock:self.png=buf.getvalue()
                    if self.hat:
                        try:self.hat.show(image)
                        except Exception as exc:
                            LOG.exception('Display write failed')
                            self.hardware_error=str(exc);self.hat.close();self.hat=None
                    last_frame=frame
                last_render=time.monotonic()

    def close(self):
        self.shutdown.set();self.runner.stop()
        if self.hat:self.hat.close()


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)

        def log_message(self,format,*args):pass

        def send(self,status,body=b'',mime='application/json',cookie=None):
            if not isinstance(body,bytes):body=json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            if cookie:self.send_header('Set-Cookie',cookie)
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass

        def authorized(self):
            try:
                cookies=SimpleCookie(self.headers.get('Cookie',''))
                value=cookies['nightshade'].value
            except (KeyError,ValueError):return False
            with app.lock:
                return app.sessions.get(value,0)>time.monotonic()

        def host_ok(self):
            bind=app.config.get('bind','')
            # When listening on every interface, accept any Host; every
            # privileged endpoint is still gated behind the access key.
            if bind in ('','0.0.0.0','::','*'):
                return True
            expected=f"{bind}:{app.config['port']}"
            return self.headers.get('Host','')==expected

        def do_GET(self):
            if not self.host_ok():return self.send(403,{'error':'Invalid host'})
            path=urlsplit(self.path).path
            assets={'/':('index.html','text/html; charset=utf-8'),'/style.css':('style.css','text/css'),'/app.js':('app.js','application/javascript')}
            if path in assets:
                name,mime=assets[path]
                return self.send(200,(ROOT/'nightshade'/'static'/name).read_bytes(),mime)
            if not self.authorized():return self.send(401,{'error':'Sign in required'})
            if path=='/api/state':return self.send(200,app.snapshot())
            if path=='/api/frame':
                with app.lock:png=app.png
                return self.send(200,png,'image/png')
            self.send(404,{'error':'Not found'})

        def do_POST(self):
            if not self.host_ok():return self.send(403,{'error':'Invalid host'})
            origin=self.headers.get('Origin')
            if origin and origin != 'http://'+self.headers.get('Host',''):
                return self.send(403,{'error':'Invalid origin'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.send(415,{'error':'JSON required'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:return self.send(413,{'error':'Request too large'})
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError()
            except (ValueError,TimeoutError):return self.send(400,{'error':'Invalid request'})
            path=urlsplit(self.path).path
            if path=='/api/login':
                key=data.get('key','')
                now=time.monotonic()
                with app.lock:
                    attempts=app.attempts[self.client_address[0]]
                    while attempts and now-attempts[0]>60:attempts.popleft()
                    if len(attempts)>=5:return self.send(429,{'error':'Wait a minute before trying again'})
                    if not isinstance(key,str) or not hmac.compare_digest(key.encode(),app.access_key.encode()):
                        attempts.append(now);return self.send(401,{'error':'Access key not recognized'})
                    app.sessions={k:v for k,v in app.sessions.items() if v>now}
                    if len(app.sessions)>=32:app.sessions.pop(next(iter(app.sessions)))
                    token=secrets.token_urlsafe(32);app.sessions[token]=now+43200
                return self.send(200,{'ok':True},cookie=f'nightshade={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
            if not self.authorized():return self.send(401,{'error':'Sign in required'})
            if path=='/api/logout':
                try:
                    c=SimpleCookie(self.headers.get('Cookie',''))
                    with app.lock:app.sessions.pop(c['nightshade'].value,None)
                except KeyError:pass
                return self.send(200,{'ok':True},cookie='nightshade=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if path=='/api/access':
                new_key=data.get('key')
                if (not isinstance(new_key,str) or not 4<=len(new_key)<=64
                        or not new_key.isprintable() or new_key.strip()!=new_key):
                    return self.send(400,{'error':'Key must be 4-64 printable characters'})
                with app.lock:
                    try:app._save_access_key(new_key)
                    except OSError:return self.send(500,{'error':'Could not write key'})
                    app.access_key=new_key
                return self.send(200,{'ok':True})
            if path=='/api/key':
                key=data.get('key')
                if not isinstance(key,str) or key not in PINS:return self.send(400,{'error':'Unknown button'})
                if not app.emit(key):return self.send(429,{'error':'Input queue full'})
                return self.send(200,{'ok':True})
            if path=='/api/run':
                ident=data.get('id')
                if not isinstance(ident,str) or ident not in app.runner.scripts:return self.send(400,{'error':'Unknown script'})
                if app.runner.scripts[ident].get('page'):return self.send(400,{'error':'Panel page only'})
                with app.lock:
                    if app.runner.snapshot()['status'] in ('running','stopping'):return self.send(409,{'error':'A script is already running'})
                    # Run under the same lock as physical controls; no command text from the browser.
                    if not app.runner.start(ident):return self.send(409,{'error':'Script could not start'})
                    app.model.page='output';app.model.scroll=0
                return self.send(200,{'ok':True})
            self.send(404,{'error':'Not found'})
    return Handler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default=str(ROOT/'config.json'))
    parser.add_argument('--state-dir',default=str(Path.home()/'.local/state/nightshade'))
    parser.add_argument('--simulate',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    state_dir=Path(args.state_dir);state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        # Mirror logs into the state directory so failures survive a reboot;
        # the systemd journal is not persistent on this device.
        file_log=_DurableFileHandler(state_dir/'nightshade.log')
        file_log.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logging.getLogger().addHandler(file_log)
    except OSError:
        pass
    config=json.loads(Path(args.config).read_text())
    # Bring the panel up before touching the network. The bind address may be a
    # Tailscale address that does not exist until tailscaled starts, and the
    # handheld UI must work off-grid regardless.
    app=Application(config,args.state_dir,args.simulate)
    LOG.info('Display ready (hardware=%s); starting interface',bool(app.hat))

    server=[None]

    def serve():
        while not app.shutdown.is_set():
            try:
                started=ThreadingHTTPServer((config['bind'],config['port']),handler_for(app))
            except OSError as exc:
                LOG.warning('Web interface unavailable on %s:%s (%s); retrying in 5s',
                            config['bind'],config['port'],exc)
                app.shutdown.wait(5);continue
            started.daemon_threads=True;server[0]=started
            LOG.info('Nightshade listening on %s:%s; hardware=%s',
                     config['bind'],config['port'],bool(app.hat))
            started.serve_forever()
            return

    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:app.shutdown.set())
    workers=[threading.Thread(target=app.sampler,daemon=True),threading.Thread(target=serve,daemon=True)]
    for worker in workers:worker.start()
    try:app.loop()
    finally:
        app.shutdown.set()
        if server[0]:
            server[0].shutdown();server[0].server_close()
        app.close()

if __name__=='__main__':main()
