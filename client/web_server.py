from http.server import BaseHTTPRequestHandler
import urllib.parse
import datetime
import email.utils
import mimetypes
import posixpath
import os
import socketserver
from http import HTTPStatus
from functools import partial
import shutil
import json

class BitTunnelHTTPReqeustHandler(BaseHTTPRequestHandler):
    server_version = "BitTunnel-HTTP/1.0"
    extensions_map = _encodings_map_default = {
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.jpeg': 'image/jpeg',
        '.jpg': 'image/jpeg'
    }
    default_content_type = "application/json"
    default_res_content = "{'status':%(code)d,'message':'%(message)s','data':'%(data)s'}"

    def __init__(self, *args, directory = None,**kwargs):
        if directory is None:
            directory = os.getcwd()
        self.directory = directory
        super().__init__(*args, **kwargs)

    def do_GET(self):
        path = self.translate_path(self.path)
        local_file = None
        ctype = self.guess_type(path)
        if path.endswith("/"):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        try:
            local_file = open(path, 'rb')
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        try:
            fs = os.fstat(local_file.fileno())
            if ("If-Modified-Since" in self.headers
                    and "If-None-Match" not in self.headers):
                try:
                    ims = email.utils.parsedate_to_datetime(
                        self.headers["If-Modified-Since"])
                except (TypeError, IndexError, OverflowError, ValueError):
                    pass
                else:
                    if ims.tzinfo is None:
                        ims = ims.replace(tzinfo=datetime.timezone.utc)
                    if ims.tzinfo is datetime.timezone.utc:
                        last_modif = datetime.datetime.fromtimestamp(
                            fs.st_mtime, datetime.timezone.utc)
                        last_modif = last_modif.replace(microsecond=0)

                        if last_modif <= ims:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.end_headers()
                            local_file.close()
                            return None
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", ctype)
            self.send_header("Content-Length", str(fs[6]))
            self.send_header("Last-Modified",self.date_time_string(fs.st_mtime))
            self.end_headers()
            shutil.copyfileobj(local_file, self.wfile)
        except:
            local_file.close()
            raise
    
    def do_POST(self):
        length = self.headers.get('content-length')
        try:
            nbytes = int(length)
        except (TypeError, ValueError):
            nbytes = 0
        if nbytes > 0:
            data = self.rfile.read(nbytes)
            self.serve_command(data)
        else:
            self.send_error(HTTPStatus.BAD_REQUEST,'Invalid post')

    def serve_command(self,post_content):
        body = self.default_res_content % {'code':500,'message':'json format error','data':''}
        try:
            params = json.loads(post_content)
            command = params.get('command',None)
            match command:
                case 'status':
                    pass
                case _:
                    pass
        except Exception as ex:
            pass
        
        body = body.encode('UTF-8', 'replace')
        self.send_response(HTTPStatus.OK)
        self.send_header('Connection', 'close')
        self.send_header("Content-Type", self.default_content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guess_type(self, path):
        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        guess, _ = mimetypes.guess_type(path)
        if guess:
            return guess
        return 'application/octet-stream'

    def translate_path(self, path):
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        trailing_slash = path.rstrip().endswith('/')
        try:
            path = urllib.parse.unquote(path, errors='surrogatepass')
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        words = path.split('/')
        words = filter(None, words)
        path = self.directory
        for word in words:
            if os.path.dirname(word) or word in (os.curdir, os.pardir):
                continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path

if __name__  == '__main__':
    PORT = 8000

    Handler = partial(BitTunnelHTTPReqeustHandler,directory = './dist')
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()
