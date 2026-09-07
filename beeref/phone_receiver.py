"""Explicitly started, authenticated image inbox for phone uploads."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PyQt6 import QtCore, QtGui
from PyQt6.QtNetwork import QNetworkInterface

MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
PASSWORD_ITERATIONS = 240_000
TUNNEL_URL = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')


def private_runtime_path(filename):
    project = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(project, '.private', filename)


def local_data_path(filename):
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        base = os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    return os.path.join(base, 'References', filename)


def login_path():
    return local_data_path('phone-login.json')


def login_locations():
    return (login_path(), private_runtime_path('phone-login.json'))


def make_login(username, password):
    """Create a salted verifier so the phone password is never stored."""
    if not username or not password:
        raise ValueError('Phone username and password cannot be empty')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt,
                                 PASSWORD_ITERATIONS)
    return {
        'username': username,
        'iterations': PASSWORD_ITERATIONS,
        'salt': base64.b64encode(salt).decode('ascii'),
        'digest': base64.b64encode(digest).decode('ascii'),
    }


def save_login(username, password, path=None):
    locations = (path,) if path else login_locations()
    login = make_login(username, password)
    for location in locations:
        os.makedirs(os.path.dirname(location), exist_ok=True)
        temporary = location + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump(login, stream)
        os.replace(temporary, location)
    return locations[0]


def load_login(path=None):
    locations = (path,) if path else login_locations()
    for location in locations:
        try:
            with open(location, encoding='utf-8') as stream:
                login = json.load(stream)
            required = {'username', 'iterations', 'salt', 'digest'}
            if not required.issubset(login):
                raise ValueError
            return login
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    raise OSError('Phone login is not configured')


def check_authorization(header, login):
    try:
        scheme, encoded = header.split(' ', 1)
        if scheme.lower() != 'basic':
            return False
        username, password = base64.b64decode(encoded, validate=True).decode().split(':', 1)
        salt = base64.b64decode(login['salt'], validate=True)
        expected = base64.b64decode(login['digest'], validate=True)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt,
                                     int(login['iterations']))
        return (hmac.compare_digest(username, login['username'])
                and hmac.compare_digest(actual, expected))
    except (AttributeError, ValueError, TypeError, KeyError):
        return False


def cloudflared_path():
    configured = os.environ.get('REFERENCES_CLOUDFLARED')
    for candidate in (configured, local_data_path('cloudflared.exe'),
                      private_runtime_path('cloudflared.exe'),
                      shutil.which('cloudflared')):
        if candidate and os.path.isfile(candidate):
            return candidate
    raise OSError('Cloudflare Tunnel is not installed for References')


class CloudflareTunnel:
    def __init__(self, port, executable=None, timeout=20):
        executable = executable or cloudflared_path()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.process = subprocess.Popen(
            [executable, 'tunnel', '--url', f'http://127.0.0.1:{port}',
             '--protocol', 'http2', '--no-autoupdate'], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', creationflags=flags)
        lines = queue.Queue()
        self.reader = threading.Thread(target=self._read_output,
                                       args=(lines,), daemon=True)
        self.reader.start()
        try:
            origin = None
            while True:
                line = lines.get(timeout=timeout)
                if line is None:
                    raise OSError('Cloudflare Tunnel stopped before it produced a link')
                match = TUNNEL_URL.search(line)
                if match:
                    origin = match.group(0)
                if origin and 'Registered tunnel connection' in line:
                    self.origin = origin
                    break
        except (queue.Empty, OSError):
            self.stop()
            raise OSError('Cloudflare Tunnel could not create a phone link')

    def _read_output(self, lines):
        for line in self.process.stdout:
            lines.put(line)
        lines.put(None)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.reader.join(timeout=2)


def lan_address(interfaces=None):
    """Prefer a connected LAN adapter, never a tunnel's hostname address."""
    interfaces = QNetworkInterface.allInterfaces() if interfaces is None else interfaces
    for interface in interfaces:
        if interface.type() not in (QNetworkInterface.InterfaceType.Ethernet,
                                    QNetworkInterface.InterfaceType.Wifi):
            continue
        flags = interface.flags()
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp
                and flags & QNetworkInterface.InterfaceFlag.IsRunning):
            continue
        for entry in interface.addressEntries():
            try:
                address = ipaddress.ip_address(entry.ip().toString())
            except ValueError:
                continue
            if (address.version == 4 and not address.is_loopback
                    and not address.is_link_local and not address.is_unspecified):
                return str(address)
    raise OSError('No connected Ethernet or Wi-Fi address found')


def decode_image(data):
    buffer = QtCore.QBuffer()
    buffer.setData(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    reader = QtGui.QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        raise ValueError('Unsupported image or image exceeds 40 megapixels')
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode image; use JPEG, PNG or WebP')
    return image


PAGE = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>References</title><style>body{font:18px system-ui;background:#202225;color:white;
max-width:480px;margin:40px auto;padding:20px}button,input{font:inherit;margin:16px 0;
max-width:100%}button{padding:14px}</style><h1>References</h1>
<p>Choose an image to replace the selected or locked reference on your PC.</p>
<input id="file" type="file" accept="image/*"><br><button id="send">Send to PC</button>
<p id="status"></p><script>
send.onclick=async()=>{const f=file.files[0];if(!f)return;
if(f.size>20971520){statusText('Image must be under 20 MB');return;}
send.disabled=true;statusText('Sending...');try{const r=await fetch(location.pathname+'/upload',
{method:'POST',body:f,headers:{'Content-Type':'application/octet-stream'}});
statusText(await r.text());}catch(e){statusText('Cannot reach PC. Check Wi-Fi and receiver.');}
finally{send.disabled=false;}};function statusText(s){document.getElementById('status').textContent=s;}
</script>'''


class PhoneReceiver(QtCore.QObject):
    image_received = QtCore.pyqtSignal(object)

    def __init__(self, parent=None, bind='0.0.0.0', login=None,
                 cloudflare=False, tunnel_factory=CloudflareTunnel):
        super().__init__(parent)
        self.token = secrets.token_urlsafe(18)
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log pairing tokens or image data.

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def reply(self, code, body, content_type='text/plain; charset=utf-8',
                      headers=None):
                body = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def authorized(self, suffix=''):
                return hmac.compare_digest(self.path, '/' + receiver.token + suffix)

            def logged_in(self):
                if receiver.login is None:
                    return True
                if check_authorization(self.headers.get('Authorization'), receiver.login):
                    return True
                self.reply(401, 'Login required', headers={
                    'WWW-Authenticate': 'Basic realm="References phone upload", charset="UTF-8"'})
                return False

            def do_GET(self):
                if not self.authorized():
                    self.reply(404, 'Not found')
                    return
                if not self.logged_in():
                    return
                self.reply(200, PAGE, 'text/html; charset=utf-8')

            def do_POST(self):
                if not self.authorized('/upload'):
                    self.reply(403, 'Invalid pairing link')
                    return
                if not self.logged_in():
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length <= 0 or length > MAX_UPLOAD:
                        self.reply(413, 'Image must be between 1 byte and 20 MB')
                        return
                    data = self.rfile.read(length)
                    if len(data) != length:
                        raise ValueError('Incomplete upload')
                    image = decode_image(data)
                except (ValueError, OSError) as error:
                    self.reply(400, str(error))
                    return
                receiver.image_received.emit(image)
                self.reply(202, 'Sent to References. Check the reference on your PC.')

        self.login = login
        self.tunnel = None
        host = lan_address() if bind == '0.0.0.0' else bind
        self.server = HTTPServer((bind, 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.url = f'http://{host}:{self.port}/{self.token}'
        if cloudflare:
            for _ in range(2):
                try:
                    self.tunnel = tunnel_factory(self.port)
                    break
                except OSError:
                    continue
            if self.tunnel is None:
                self.stop()
                raise OSError('Cloudflare could not create a link after two attempts')
            self.url = f'{self.tunnel.origin}/{self.token}'

    def stop(self):
        if self.tunnel is not None:
            self.tunnel.stop()
            self.tunnel = None
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
