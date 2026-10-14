import http.client
import importlib.util
import json
from pathlib import Path
import os
import tempfile
import threading
import time
import unittest
import sys
import types
from unittest import mock
from http.server import ThreadingHTTPServer
from PIL import Image
from nightshade.app import Application, handler_for
from nightshade.hardware import rgb565
from nightshade.runner import Runner
from nightshade.ui import Model

ROOT=Path(__file__).resolve().parent.parent

class HardwareTests(unittest.TestCase):
    def test_spi_color_byte_order(self):
        image=Image.new('RGB',(3,1));image.putdata([(255,0,0),(0,255,0),(0,0,255)])
        self.assertEqual(rgb565(image),bytes.fromhex('f80007e0001f'))

    def _probe(self,chips,order='status'):
        # There is no /dev/gpiochip* off the Pi, so stand in for lgpio. chips
        # maps a chip index to (name, label, lines); order selects the return
        # shape: lgpio's documented [status, lines, name, label] or the older
        # (name, label, lines).
        def gpiochip_open(index):
            if index not in chips: raise OSError('no such chip')
            return index + 100
        def gpio_get_chip_info(handle):
            name,label,lines=chips[handle-100]
            return [0,lines,name,label] if order=='status' else [name,label,lines]
        module=types.ModuleType('lgpio')
        module.error=OSError;module.gpiochip_open=gpiochip_open
        module.gpiochip_close=lambda handle:None
        module.gpio_get_chip_info=gpio_get_chip_info
        from nightshade import hardware
        with mock.patch.dict(sys.modules,{'lgpio':module}):
            return hardware._lgpio_chip()

    def test_lgpio_chip_probe(self):
        # gpiozero assumes the SoC controller is chip 0. That only holds if
        # nothing registered ahead of it, which is exactly what this image
        # cannot guarantee, so the probe must find it either way.
        for order in ('status','tuple'):
            self.assertEqual(self._probe({0:('gpiochip0','pinctrl-bcm2835',54),
                                          1:('gpiochip1','gpio-raspberrypi-exp-gpio',8)},order),0)
            self.assertEqual(self._probe({0:('gpiochip0','gpio-raspberrypi-exp-gpio',8),
                                          1:('gpiochip1','pinctrl-bcm2835',54)},order),1)
            self.assertEqual(self._probe({0:('gpiochip0','3f200000.gpio',54)},order),0)
            # No name to trust: fall back to the chip with the most lines.
            self.assertEqual(self._probe({0:('gpiochip0','gpio-a',8),
                                          1:('gpiochip1','gpio-b',54)},order),1)
            # lgpio unusable: signal the caller to use the documented default.
            self.assertIsNone(self._probe({},order))

class RunnerTests(unittest.TestCase):
    def test_allowlist_and_single_job(self):
        r=Runner([{'id':'sleep','name':'Sleep','argv':[sys.executable,'-c','import time; print("ready",flush=True);time.sleep(30)'],'timeout':5}],ROOT)
        with self.assertRaises(ValueError):r.start('unregistered')
        self.assertTrue(r.start('sleep'));self.assertFalse(r.start('sleep'))
        r.stop();deadline=time.monotonic()+4
        while r.snapshot()['status']=='stopping' and time.monotonic()<deadline:time.sleep(.03)
        self.assertEqual(r.snapshot()['status'],'stopped')

    def test_timeout_kills_stubborn_child(self):
        code='import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"]); print("spawned",flush=True);time.sleep(30)'
        r=Runner([{'id':'child','name':'Child','argv':[sys.executable,'-c',code],'timeout':.3}],ROOT)
        r.start('child');deadline=time.monotonic()+5
        while r.snapshot()['status'] in ('running','stopping') and time.monotonic()<deadline:time.sleep(.04)
        self.assertEqual(r.snapshot()['status'],'stopped')
        self.assertTrue(any('timed out' in line for line in r.snapshot()['lines']))

    def test_physical_launch_requires_confirmation(self):
        scripts=[{'id':'x','name':'X','argv':[sys.executable,'-c','print(42)']}]
        model=Model(scripts);runner=Runner(scripts,ROOT)
        model.key('DOWN',runner);model.key('DOWN',runner);model.key('OK',runner)
        self.assertEqual(model.page,'scripts')
        model.key('OK',runner);self.assertEqual(model.page,'confirm')
        self.assertEqual(runner.snapshot()['status'],'idle')
        model.key('KEY1',runner);self.assertEqual(model.page,'scripts')
        model.key('KEY2',runner);self.assertEqual(model.page,'home')

class SectionTests(unittest.TestCase):
    def test_sections_derived_from_scripts(self):
        scripts=[{'id':'a','name':'A','section':'wifi','argv':[sys.executable,'-c','print(1)']},
                 {'id':'b','name':'B','section':'wifi','argv':[sys.executable,'-c','print(2)']},
                 {'id':'c','name':'C','section':'ble','argv':[sys.executable,'-c','print(3)']}]
        model=Model(scripts)
        self.assertEqual([s['id'] for s in model.sections],['wifi','ble'])
        self.assertEqual([s['name'] for s in model.sections],['Wi-Fi','Bluetooth'])
        self.assertEqual([s['id'] for s in model.by_section['wifi']],['a','b'])

    def test_single_section_stays_flat(self):
        # One section must behave like the old flat script list, so a simple
        # config keeps the direct Scripts -> confirm flow.
        scripts=[{'id':'a','name':'A','argv':[sys.executable,'-c','print(1)']}]
        model=Model(scripts);runner=Runner(scripts,ROOT)
        model.key('DOWN',runner);model.key('DOWN',runner);model.key('OK',runner)
        self.assertEqual(model.page,'scripts')
        model.key('OK',runner);self.assertEqual(model.page,'confirm')

    def test_section_navigation(self):
        scripts=[{'id':'a','name':'A','section':'wifi','argv':[sys.executable,'-c','print(1)']},
                 {'id':'b','name':'B','section':'ble','argv':[sys.executable,'-c','print(2)']}]
        sections=[{'id':'wifi','name':'Wi-Fi'},{'id':'ble','name':'Bluetooth'}]
        model=Model(scripts,sections);runner=Runner(scripts,ROOT)
        model.key('DOWN',runner);model.key('DOWN',runner);model.key('OK',runner)
        self.assertEqual(model.page,'sections')
        self.assertEqual(model.section['id'],'wifi')
        model.key('OK',runner);self.assertEqual(model.page,'scripts')
        self.assertEqual([s['id'] for s in model.visible_scripts()],['a'])
        model.key('KEY1',runner);self.assertEqual(model.page,'sections')
        model.key('DOWN',runner);model.key('OK',runner);model.key('OK',runner)
        self.assertEqual(model.page,'confirm')
        self.assertEqual(model.visible_scripts()[model.index]['id'],'b')


class WifiAdapterTests(unittest.TestCase):
    """Auto-detection of the monitor-mode adapter (e.g. an Alfa)."""

    @staticmethod
    def _load():
        spec = importlib.util.spec_from_file_location(
            'wifi_tools', ROOT / 'scripts' / 'wifi_tools.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _fake_run(routes, interfaces):
        def run(argv, timeout=25, stdin=None):
            command = ' '.join(argv)
            if command.startswith('ip -j route'):
                return 0, json.dumps(routes)
            if command.startswith('iw dev'):
                return 0, interfaces
            return 0, ''
        return run

    def test_prefers_external_adapter(self):
        wifi = self._load()
        with mock.patch.object(wifi, 'run', side_effect=self._fake_run(
                [{'dev': 'wlan0'}],
                'phy#0\n\tInterface wlan0\n\t\ttype managed\n'
                '\tInterface wlan1\n\t\ttype managed\n')):
            self.assertEqual(wifi.wifi_adapter(), 'wlan1')

    def test_falls_back_to_uplink(self):
        wifi = self._load()
        with mock.patch.object(wifi, 'run', side_effect=self._fake_run(
                [{'dev': 'wlan0'}],
                'phy#0\n\tInterface wlan0\n\t\ttype managed\n')):
            self.assertEqual(wifi.wifi_adapter(), 'wlan0')

    def test_config_pins_adapter(self):
        wifi = self._load()
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        handle.write('{"wifi": {"adapter": "wlan2"}}')
        handle.close()
        try:
            with mock.patch.object(wifi, 'CONFIG', Path(handle.name)):
                self.assertEqual(wifi.wifi_adapter(), 'wlan2')
        finally:
            os.unlink(handle.name)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        config={'bind':'127.0.0.1','port':0,'display':{'type':'ST7789_240'},'scripts':[]}
        self.app=Application(config,self.tmp.name,simulate=True)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        config['port']=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.host=f'127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.tmp.cleanup()

    def request(self,path,data=None,cookie=None,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={}
        if cookie:headers['Cookie']=cookie
        if origin:headers['Origin']=origin
        if data is not None:headers['Content-Type']='application/json'
        c.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers)
        r=c.getresponse();result=r.status,dict(r.getheaders()),r.read();c.close();return result

    def test_auth_origin_and_input(self):
        self.assertEqual(self.request('/api/state')[0],401)
        self.assertEqual(self.request('/api/key',{'key':'OK'})[0],401)
        self.assertEqual(self.request('/api/login',{'key':self.app.access_key},origin='http://evil.example')[0],403)
        status,headers,_=self.request('/api/login',{'key':self.app.access_key})
        self.assertEqual(status,200);cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],200)
        self.assertEqual(self.request('/api/key',{'key':'OK'},cookie)[0],200)
        self.assertEqual(self.app.events.get_nowait(),('key','OK'))
        self.assertEqual(self.request('/api/run',{'id':'/bin/sh'},cookie)[0],400)
        self.assertEqual(self.request('/api/key',{'key':[]},cookie)[0],400)
        self.assertEqual(self.request('/api/logout',{},cookie)[0],200)
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],401)

    def test_login_rate_limit(self):
        for _ in range(5):self.assertEqual(self.request('/api/login',{'key':'bad'})[0],401)
        self.assertEqual(self.request('/api/login',{'key':'bad'})[0],429)

if __name__=='__main__':unittest.main()
