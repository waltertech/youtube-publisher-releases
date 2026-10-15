import json,sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Resources/payload'))
import local_transport as transport
from file_adapter import CDP
from websockets.sync.server import serve

class LocalTransportTests(unittest.TestCase):
 def test_only_loopback_bypasses_proxy(self):
  for host in ['127.0.0.1','127.0.0.2','localhost','[::1]']:
   self.assertEqual(transport.websocket_options('ws://'+host+':1234'),{'proxy':None})
  for host in ['localhost.example.com','192.168.1.4','example.com']:
   self.assertEqual(transport.websocket_options('wss://'+host),{})
  with patch.object(transport.urllib.request,'urlopen') as external:
   transport.urlopen('https://github.com/',timeout=1)
   external.assert_called_once()
 def test_real_cdp_connection_under_system_proxy(self):
  def handler(ws):
   message=json.loads(ws.recv());ws.send(json.dumps({'id':message['id'],'result':{'ok':True}}))
  with serve(handler,'127.0.0.1',0) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    for proxies in [{},{'socks':'socks5://127.0.0.1:1'},{'http':'http://127.0.0.1:1','https':'http://127.0.0.1:1'}]:
     with self.subTest(proxies=proxies),patch('urllib.request.getproxies',return_value=proxies),patch('urllib.request.proxy_bypass',return_value=False):
      c=CDP(f'ws://127.0.0.1:{server.socket.getsockname()[1]}');self.assertTrue(c.call('Browser.getVersion')['ok']);c.close()
   finally:server.shutdown();thread.join(timeout=3)
 def test_real_http_under_system_proxy(self):
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'ok')
   def log_message(self,*args):pass
  with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    for proxies in [{},{'socks':'socks5://127.0.0.1:1'},{'http':'http://127.0.0.1:1'}]:
     with self.subTest(proxies=proxies),patch('urllib.request.getproxies',return_value=proxies),patch('urllib.request.proxy_bypass',return_value=False):
      with transport.urlopen(f'http://127.0.0.1:{server.server_port}',timeout=2) as r:self.assertEqual(r.read(),b'ok')
   finally:server.shutdown();thread.join(timeout=3)
