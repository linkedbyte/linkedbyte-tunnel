# coding: utf-8

from selectors import DefaultSelector,EVENT_READ,EVENT_WRITE
import socket
import logging
import logging.handlers
from server_config import ServerConfig
from proxy import HttpProxyClient
import signal
import sys

rotaing_file_handler = logging.handlers.RotatingFileHandler('bit_tunnel_server.log', maxBytes=100*1024, backupCount=100)
rotaing_file_handler.setFormatter(logging.Formatter('%(levelname)s:%(module)s:%(lineno)d:%(funcName)s:%(asctime)s:%(message)s'))

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(levelname)s:%(module)s:%(lineno)d:%(funcName)s:%(asctime)s:%(message)s'))

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(rotaing_file_handler)
logging.getLogger().addHandler(stream_handler)

def signal_handler(signum, frame):
    global g_app_exit
    g_app_exit = True
    logging.info('bit-tunnel server exit!')

signal.signal(signal.SIGINT, signal_handler)  
signal.signal(signal.SIGTERM, signal_handler)
g_app_exit = False

LISTEN_COUNT = 100

ServerConfig.parser()

class Selector(object):
    def __init__(self):
        self._select_handler = DefaultSelector()
        self._proxy_clients = {}

    def listen_proxy(self):
        '''
        客户端代理监听
        '''
        self._proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._proxy_sock.bind((ServerConfig.bind_ip, ServerConfig.bind_port))
        self._proxy_sock.listen(LISTEN_COUNT)
        self._proxy_sock.setblocking(False)
        self._select_handler.register(self._proxy_sock,EVENT_READ,self.proxy_accept)

    def proxy_accept(self,key,mask):
        '''
        客户端代理接入
        '''
        conn, addr = key.fileobj.accept()
        logging.info('accepted ，ip = {}, port = {}'.format(addr[0],addr[1]))
        conn.setblocking(False)
        self._proxy_clients[conn] = HttpProxyClient(conn,addr,self._select_handler)
        self._select_handler.register(conn, EVENT_READ | EVENT_WRITE, self.proxy_proc)

    def proxy_proc(self,key,mask):
        '''
        客户端代理处理方法
        '''
        proxy_client: HttpProxyClient = self._proxy_clients.get(key.fileobj)
        if not proxy_client:
            logging.error('not find proxy client!')
            return
        try:
            if mask == EVENT_READ:
                proxy_client.recv()
            elif mask == EVENT_WRITE:
                proxy_client.send()
            else:
                proxy_client.recv()
                proxy_client.send()
        except Exception as ex:
            logging.error(ex)
            self.dispose(proxy_client)

    def dispose(self,proxy_client):
        self._proxy_clients.pop(proxy_client.sock)
        proxy_client.dispose()

    def dispose_all(self):
        for it in self._proxy_clients.values():
            it.dispose()
        sys.exit(0)

    def event_loop(self):
        while True:
            if g_app_exit:
                break
            try:
                events = self._select_handler.select(timeout=1)
                for key,mask in events:
                    callback = key.data
                    callback(key,mask)
            except OSError as ex:
                logging.error(ex)
        self.dispose_all()

if __name__ == '__main__':
    selector = Selector()
    selector.listen_proxy()
    selector.event_loop()
