# coding: utf-8
'''
local_server <-------- tunnel_client ---------> tunnel_server
'''
import logging
import logging.handlers
from selectors import DefaultSelector,EVENT_READ,EVENT_WRITE
import socket
from queue import Queue
from threading import Thread
import traceback
import sys
import os
import configparser
import signal

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_PATH)

from common.message import MessageType,decode_message,encode_message
from common.exception import MessageError,ClientCloseError
import time

rotaing_file_handler = logging.handlers.RotatingFileHandler('linkedbyte_tunnel_client.log', maxBytes=100*1024, backupCount=100)
rotaing_file_handler.setFormatter(logging.Formatter('%(levelname)s:%(module)s:%(lineno)d:%(funcName)s:%(asctime)s:%(message)s'))

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(levelname)s:%(module)s:%(lineno)d:%(funcName)s:%(asctime)s:%(message)s'))

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(rotaing_file_handler)
logging.getLogger().addHandler(stream_handler)

g_app_exit = False

def signal_handler(signum, frame):
    global g_app_exit
    g_app_exit = True
    logging.info('linkedbyte-tunnel client exit!')

signal.signal(signal.SIGINT, signal_handler)  
signal.signal(signal.SIGTERM, signal_handler)


BUFFER_LEN = 1024
#每30秒发送一次keep alive
KEEP_ALIVE = 30
#发送3次后没有收到回应则关闭链路
KEEP_ALIVE_RETRY = 3

DEFAULT_SERVER_IP = '192.168.3.178'
DEFAULT_SERVER_PORT = 6800
DEFAULT_LOCAL_IP = '127.0.0.1'
DEFAULT_LOCAL_PORT = 80
DEFAULT_PROXY_PORT = 7801
DEFAULT_USERNAME = 'test'
DEFAULT_PASSWORD = '12345678'

class Config():
    server_ip = ''
    server_port = 6800
    local_ip = ''
    #本地被代理服务端口
    local_port = 80
    #对外代理服务域名
    proxy_hostname = ''
    #对外代理服务端口
    proxy_port = 7801
    ini_path = ''
    username = ''
    password = ''

    @classmethod
    def parser(cls):
        cls.ini_path = os.path.dirname(os.path.realpath(__file__))
        cls.ini_path = os.path.join(cls.ini_path,'lbtc.ini')
        conf = configparser.ConfigParser()
        conf.read(cls.ini_path, encoding="utf-8")

        try:
            common_conf = conf['common']
        except Exception as ex:
            logging.error('parser ini error!')
            logging.error(ex)
        else:
            cls.server_ip = common_conf.get('server_ip',DEFAULT_SERVER_IP)
            cls.server_port = common_conf.getint('server_port',DEFAULT_SERVER_PORT)
            cls.username = common_conf.get('username',DEFAULT_USERNAME)
            cls.password = common_conf.get('password',DEFAULT_PASSWORD)
        
        try:
            proxy_conf = conf['proxy']
        except Exception as ex:
            pass
        else:
            cls.local_ip = http_conf.get('local_ip',DEFAULT_LOCAL_IP)
            cls.local_port = http_conf.getint('local_port',DEFAULT_LOCAL_PORT)
            cls.proxy_hostname = http_conf.get('proxy_domain')
            cls.proxy_port = http_conf.getint('proxy_port',DEFAULT_PROXY_PORT)

#初始化配置
Config.parser()

class ProxyClient(object):
    def __init__(self,ip,port,select_handler):
        self._ip = ip
        self._port = port
        #接收缓冲区
        self._recv_buffer = b''
        #发送缓冲区
        self._send_buffer = b''
        self._is_signin = False
        #最后一个数据包的时间
        self._last_time = int(time.time())
        self._sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self._sock.connect((self._ip,self._port))
        self._sock.setblocking(False)
        self._local_clients = {}
        self._select_handler = select_handler

    def keep_alive(self):
        '''
        超过30秒发送keep alive 消息
        '''
        if self._last_time+KEEP_ALIVE < int(time.time()):
            logging.debug('send keep alive...')
            data = encode_message(MessageType.KEEP_ALIVE,1,b'\x00')
            self._send_buffer += data
            #self._sock.sendall(data)
            self._last_time = int(time.time())
    
    def signin(self):
        '''
        登录
        '''
        body = bytes(Config.username,'utf-8') + b':' + bytes(Config.password,'utf-8')
        msg = encode_message(MessageType.SIGN_IN,len(body),body)
        self._sock.sendall(msg)
    def conf(self):
        '''
        客户端配置
        '''
        body = bytes(Config.proxy_hostname,'utf-8') + b':' + bytes(str(Config.proxy_port),'utf-8')
        msg = encode_message(MessageType.CLIENT_CONF,len(body),body)
        self._send_buffer += msg
    def signout(self):
        '''
        登出
        '''
        msg = encode_message(MessageType.SIGN_OUT.value,1,b'\x00')
        self._sock.sendall(msg)
        time.sleep(1)
        self.dispose()
    
    def dispose(self):
        try:
            for it in self._local_clients.values():
                self._select_handler.unregister(it.sock)
                it.sock.close()
            self._local_clients.clear()
            if self.sock:
                self._select_handler.unregister(self.sock)
                self.sock.close()
        except Exception as ex:
            logging.error(ex)
        

    @property
    def is_signin(self):
        return self._is_signin

    @is_signin.setter
    def is_signin(self,value):
        self._is_signin = value

    @property
    def sock(self):
        return self._sock

    def send(self):
        if not self._send_buffer:
            self.keep_alive()
        else:
            try:
                if g_app_exit:
                    self.signout() 
                ret = self._sock.sendall(self._send_buffer)
                if not ret:
                    logging.info('send success, ip = {},port = {}'.format(self._ip,self._port))
                    self._send_buffer = b''
            except Exception as ex:
                logging.error(ex)
                raise

    def recv(self):
        while True:
            try:
                data = self._sock.recv(BUFFER_LEN)
                if not data:
                    break
                logging.debug('recv data,current len = {},recv len = {}'.format(len(self._recv_buffer),len(data)))
                self._recv_buffer += data
            except BlockingIOError as ex:
                #logging.error(ex)
                break
            except ConnectionResetError as ex1:#连接关闭
                logging.error('server socket is closed!')
                raise
            except Exception as ex:
                traceback.print_exc()
                logging.error(ex)
                raise
        #解析数据包
        while len(self._recv_buffer) > 2+4:
            try:
                message_type,message_length,body,data = decode_message(self._recv_buffer)
                if message_type == MessageType.SIGN_IN_ACK.value:
                    #登录成功
                    self.is_signin = True
                    logging.info('client sign in success!')
                    self.conf()
                elif message_type == MessageType.CLIENT_CONF_ACK.value:
                    #上报配置成功
                    logging.info('client conf success!')
                elif message_type == MessageType.SIGN_OUT_ACK.value:
                    #关闭local clients

                    #通知Selector
                    raise ClientCloseError('client will close!')
                elif message_type == MessageType.DATA.value:
                    local_client_id = int.from_bytes(body[0:2],byteorder='big')
                    local_client = self.get_local_client_for_id(local_client_id)
                    if local_client:
                        pass
                    else:
                        logging.info('create local client ,client id = {}'.format(local_client_id))
                        try:
                            local_client = LocalClient(Config.local_ip,Config.local_port)
                            local_client.client_id = local_client_id
                            self._local_clients[local_client.sock] = local_client
                            self._select_handler.register(local_client.sock,EVENT_READ|EVENT_WRITE,self.local_client_proc)
                        except Exception as ex:
                            logging.error(ex)
                            #被代理服务未启动
                            logging.debug('local service error!')
                            msg = encode_message(MessageType.LOCAL_SERVICE_ERROR.value,2,body[0:2])
                            self._send_buffer += msg
                    if local_client:
                        local_client.append_send_buffer(body[2:].replace(
                            bytes(str(Config.proxy_port),encoding='utf-8'),
                            bytes(str(Config.local_port),encoding='utf-8')))
                    
                elif message_type == MessageType.KEEP_ALIVE:
                    logging.info('keep alive ack!')
                elif message_type == MessageType.LOCAL_SERVICE_ERROR_ACK:
                    logging.info('local service error ack!')
                else:
                    logging.error('unknow message!')
                self._recv_buffer = data
            except MessageError as ex:
                logging.error(ex)
                break
            except Exception as e:
                logging.error(e)
                traceback.print_exc()
                raise
    def get_local_client_for_id(self,client_id):
        '''
        根据client_id获取 local_client
        '''
        for it in self._local_clients.values():
            if it.client_id == client_id:
                return it
        return None

    def local_client_proc(self,key,mask):
        local_client: LocalClient = self._local_clients[key.fileobj]
        if not local_client:
            logging.error("not find local client!")
            return
        try:
            if mask == EVENT_READ:
                data = local_client.recv()
                if data:
                    #编码成data数据包,添加2字节的local client ID
                    data = local_client.client_id_bytes() + data
                    ret = encode_message(MessageType.DATA,len(data),data)
                    self._send_buffer += ret
            elif mask == EVENT_WRITE:
                local_client.send()
            else:
                data = local_client.recv()
                if data:
                    #编码成data数据包,添加2字节的local client ID
                    data = local_client.client_id_bytes() + data
                    ret = encode_message(MessageType.DATA.value,len(data),data)
                    self._send_buffer += ret
                local_client.send()
        except Exception as ex:
            logging.error(ex)
            self._local_clients.pop(local_client.sock)
            self._select_handler.unregister(local_client.sock)
            local_client.sock.close()

class LocalClient(object):
    def __init__(self,ip,port):
        self._ip = ip
        self._port = port
        self._client_id = None
        self._sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self._sock.connect((self._ip,self._port))
        self._sock.setblocking(False)
        self._send_buffer = b''
    @property
    def client_id(self):
        return self._client_id
    def client_id_bytes(self):
        return int.to_bytes(self._client_id,2,byteorder='big')

    @client_id.setter
    def client_id(self,value):
        self._client_id = value

    def append_send_buffer(self,data):
        self._send_buffer += data

    @property
    def sock(self):
        return self._sock
    def send(self):
        if not self._send_buffer:
            return
        try:
            ret = self._sock.sendall(self._send_buffer)
            if not ret:
                logging.info('send success!')
                self._send_buffer = b''
            else:
                pass
        except Exception as ex:
            logging.error('send failed {}')
            raise

    def recv(self):
        buffer = b''
        while True:
            try:
                data = self._sock.recv(1024)
                if not data:
                    break
                buffer += data
            except BlockingIOError as ex:
                #logging.error(ex)
                break
            except ConnectionResetError as ex1:#连接关闭
                logging.error('socket is closed!')
                raise
        return buffer

class Selector(object):
    def __init__(self):
        self._select_handler = DefaultSelector()
        self._proxy_client = None

    @property
    def select_handler(self):
        return self._select_handler

    def connected(self):
        if g_app_exit:
            sys.exit(0)
        try:
            self._proxy_client = ProxyClient(Config.server_ip,Config.server_port,self._select_handler)
            #登录
            self._proxy_client.signin()
            time.sleep(2)
        except ConnectionRefusedError as ex:
            logging.error('client to server connected failed for refused.')
            time.sleep(5)
            self.connected()
            #raise
        except BlockingIOError as ex:
            logging.error('client to server connected failed.')
            raise
        except Exception as ex:
            logging.error(ex)
            raise
        else:
            self._select_handler.register(self._proxy_client.sock,EVENT_WRITE|EVENT_READ,self.proxy_client_proc)


    def proxy_client_proc(self,key,mask):
        try:
            if mask == EVENT_READ:
                self._proxy_client.recv()
            elif mask == EVENT_WRITE:
                self._proxy_client.send()
            else:
                self._proxy_client.recv()
                self._proxy_client.send()
        except Exception as ex:
            self._proxy_client.dispose()
            self._proxy_client = None


    def event_loop(self):
        try:
            self.connected()
        except Exception as ex:
            logging.error(ex)
        else:
            while True:
                if g_app_exit:
                    break
                try:
                    events = self.select_handler.select()
                    for key,mask in events:
                        callback = key.data
                        callback(key,mask)
                except Exception as ex:
                    logging.error(ex)
                    break
            if self._proxy_client:
                self._proxy_client.dispose()
            if g_app_exit:
                sys.exit(0)
        self.event_loop()


if __name__ == '__main__':
    print('start proxy ...')
    selector = Selector()
    selector.event_loop()
