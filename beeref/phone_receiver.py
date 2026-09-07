"""Explicitly started LAN-only image inbox; no cloud or disk uploads."""
import hmac
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PyQt6 import QtCore, QtGui

MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000


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

    def __init__(self, parent=None, bind='0.0.0.0'):
        super().__init__(parent)
        self.token = secrets.token_urlsafe(18)
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log pairing tokens or image data.

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def reply(self, code, body, content_type='text/plain; charset=utf-8'):
                body = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)

            def authorized(self, suffix=''):
                return hmac.compare_digest(self.path, '/' + receiver.token + suffix)

            def do_GET(self):
                if not self.authorized():
                    self.reply(404, 'Not found')
                    return
                self.reply(200, PAGE, 'text/html; charset=utf-8')

            def do_POST(self):
                if not self.authorized('/upload'):
                    self.reply(403, 'Invalid pairing link')
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

        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
        host = next((ip for ip in addresses if ip.startswith(('192.168.', '10.'))),
                    next((ip for ip in addresses if not ip.startswith('127.')), '127.0.0.1'))
        self.server = HTTPServer((bind, 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.url = f'http://{host}:{self.port}/{self.token}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
