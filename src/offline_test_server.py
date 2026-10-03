"""A local server that can pretend the network is gone, for testing offline use.

    python src/offline_test_server.py            serves site/ on :8777

The mode is read from src/.offline_mode on every request, so it can be flipped
while a browser stays on the same origin - which matters, because the service
worker and everything it saved belong to that origin:

    normal   serve files                       (the default)
    down     drop the connection unanswered    as with no signal at all
    portal   answer everything with a login    as refuge or hotel wifi does
             page, status 200, text/html       before you sign in
    error    503 for everything                a broken server
    portal-except-sw                           portal, but sw.js itself served,
                                               so a service-worker UPDATE runs
                                               its install behind the portal

Normal responses carry Cache-Control: no-store so the browser's HTTP cache
never holds anything: whatever loads while the mode is "down" must have come
from the service worker's own cache, which is the thing being tested.
"""
import http.server, os, socket, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODE_FILE = os.path.join(HERE, '.offline_mode')
PORTAL = (b'<!doctype html><html><head><title>Wi-Fi login</title></head>'
          b'<body><h1>Refuge Wi-Fi</h1><p>Please accept the terms to continue.</p></body></html>')


def mode():
    try:
        return open(MODE_FILE).read().strip() or 'normal'
    except OSError:
        return 'normal'


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        m = mode()
        if m == 'down':
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if m == 'portal-except-sw' and self.path.split('?')[0].endswith('/sw.js'):
            m = 'normal'
        if m in ('portal', 'portal-except-sw'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(PORTAL)))
            self.end_headers()
            self.wfile.write(PORTAL)
            return
        if m == 'error':
            self.send_error(503, 'Service Unavailable')
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    print('serving %s on http://localhost:8777  (mode file: %s)' % (ROOT, MODE_FILE))
    Server(('', 8777), Handler).serve_forever()
