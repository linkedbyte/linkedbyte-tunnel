# coding: utf-8
from enum import IntEnum
from http.server import DEFAULT_ERROR_MESSAGE,DEFAULT_ERROR_CONTENT_TYPE
from http import HTTPStatus
import time
import email
import html
from selectors import DefaultSelector,EVENT_READ,EVENT_WRITE
import socket
import logging
import os
import sys

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_PATH)
from common.message import MessageType,decode_message,encode_message
from common.exception import MessageError
from server_config import ServerConfig
BUFFER_LEN = 1024

class ClientConfig(object):
    '''
    客户端配置,动态类
    '''
    pass
    

class ProxyStatus(object):
    '''
    代理服务器状态,动态类
    '''
    pass

class RequestClient(object):
    '''
    对外服务客户端
    '''
    def __init__(self,sock,addr):
        #连接句柄
        self._sock = sock
        #连接地址
        self._addr = addr
        self._client_id = sock.fileno()
        self._send_buffer = b''
        self._short_link = False
    @property
    def short_link(self):
        return self._short_link
    @property
    def client_id(self):
        return self._client_id
    
    def client_id_bytes(self):
        return int.to_bytes(self._client_id,2,byteorder='big')

    @property
    def sock(self):
        self._sock

    def recv(self):
        buffer = b''
        while True:
            try:
                data = self._sock.recv(BUFFER_LEN)
                if not data:
                    break
                buffer += data
            except BlockingIOError as ex:
                #logging.error(ex)
                break
            except ConnectionResetError as ex:#连接关闭
                logging.error('socket is closed!')
                raise
            except Exception as ex:
                logging.error(ex)
                raise
        #http短连接
        if buffer.find(b'Connection: close') or buffer.find(b'Connection: Close'):
            self._short_link = True

        return buffer

    def append_send_buffer(self,data):
        self._send_buffer += data

    def send(self):
        if not self._send_buffer:
            return
        try:
            ret = self._sock.sendall(self._send_buffer)
            if not ret:
                logging.info('send success, {}'.format(self.addr_to_str()))
                self._send_buffer = b''
            else:
                pass
        except Exception as ex:
            logging.error('send failed ,{}',self.addr_to_str())
            raise

    def addr_to_str(self):
        return "ip = {},port = {}".format(self._addr[0],self._addr[1])


class BaseProxyClient(object):
    def __init__(self,sock,addr,select_handler):
        #连接句柄
        self._sock = sock
        #连接地址
        self._addr = addr
        #接收缓冲区
        self._recv_buffer = b''
        #发送缓冲区
        self._send_buffer = b''
        self._select_handler = select_handler
        self._request_sock = None
        self._request_clients = {}
        #代理状态
        self._proxy_status = ProxyStatus()
        self._client_config = ClientConfig()
        #超过60秒发送keep alive
        self._last_act_time = int(time.time())
    
    @property
    def proxy_status(self):
        self._proxy_status
    @proxy_status.setter
    def proxy_status(self,value):
        self._proxy_status = value
    
    def get_request_client_for_id(self,client_id):
        '''
        根据client_id获取 request_client
        '''
        for it in self._request_clients.values():
            if it.client_id == client_id:
                return it
        return None

    def addr_to_str(self):
        return "ip = {},port = {}".format(self._addr[0],self._addr[1])

    @property
    def sock(self):
        return self._sock
    def set_proxy_ip(self):
        '''
        根据客户端上报的proxy_hostname生成proxy_ip
        '''
        if self._client_config.proxy_hostname:
            pass
        self._client_config.proxy_ip = ServerConfig.bind_ip

    def listen_request(self):
        '''
        对外服务监听
        '''
        self._request_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._request_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._request_sock.bind((self._client_config.proxy_ip, self._client_config.proxy_port))
        self._request_sock.listen(5)
        self._request_sock.setblocking(False)
        self._select_handler.register(self._request_sock,EVENT_READ,self.request_accept)
    
    def request_accept(self,key,mask):
        '''
        对外服务接入
        '''
        conn, addr = key.fileobj.accept()
        logging.info('request accepted ，ip = {}, port = {}'.format(addr[0],addr[1]))
        conn.setblocking(False)
        self._request_clients[conn] = RequestClient(conn,addr)
        self._select_handler.register(conn, EVENT_READ | EVENT_WRITE, self.request_proc)

    def request_proc(self,key,mask):
        request_client: RequestClient = self._request_clients.get(key.fileobj)
        if not request_client:
            logging.error('not find request client')
        try:
            if mask == EVENT_READ:
                data = request_client.recv()
                if data:
                    logging.debug('request for client id = {}'.format(request_client.client_id))
                    #编码成data数据包,添加2字节的request client ID
                    data = request_client.client_id_bytes() + data
                    msg = encode_message(MessageType.DATA,len(data),data)
                    self._send_buffer += msg

            elif mask == EVENT_WRITE:
                request_client.send()
            else:
                data = request_client.recv()
                if data:
                    #编码成data数据包,添加2字节的request client ID
                    data = request_client.client_id_bytes() + data
                    msg = encode_message(MessageType.DATA,len(data),data)
                    self._send_buffer += msg
                request_client.send()
        except Exception as ex:
            logging.error(ex)
            self._request_clients.pop(request_client.sock)
            self._select_handler.unregister(request_client.sock)
            request_client.sock.close()
    
    def dispose(self):
        #销毁request client
        for it in self._request_clients.values():
            if it.sock:
                self._select_handler.unregister(it.sock)
        if self._request_sock:
            self._select_handler.unregister(self._request_sock)
            self._request_sock.close()
        #销毁代理客户端
        try:
            self._select_handler.unregister(self._sock)
            self._sock.close()
        except Exception as ex:
            logging.error(ex)
        

class HttpProxyClient(BaseProxyClient):
    server_version = 'BitTunnel/0.9.0'
    protocol_version = 'HTTP/1.0'

    def __init__(self, sock, addr, select_handler):
        super().__init__(sock, addr, select_handler)
        
        self._headers_buffer = []
        self._body_buffer = b''

    def send_header(self,keyword, value):
        self._headers_buffer.append(
            ("%s: %s\r\n" % (keyword, value)).encode('latin-1', 'strict')
        )
    def end_header(self):
        self._headers_buffer.append(b"\r\n")

    def date_time_string(self, timestamp=None):
        """Return the current date and time formatted for a message header."""
        if timestamp is None:
            timestamp = time.time()
        return email.utils.formatdate(timestamp, usegmt=True)
    def keep_alive(self):
        '''
        超过60秒发送keep alive 消息,测试客户端是否存活
        '''
        if self._last_act_time+60 < int(time.time()):
            logging.debug('send keep alive...')
            data = encode_message(MessageType.KEEP_ALIVE,1,b'\x00')
            self._send_buffer += data
            #self._sock.sendall(data)
            self._last_act_time = int(time.time())

    def send(self):
        if not self._send_buffer:
            self.keep_alive()
        else:
            try:
                ret = self._sock.sendall(self._send_buffer)
                if not ret:
                    logging.debug('send success, {}'.format(self.addr_to_str()))
                    self._send_buffer = b''
                else:
                    pass
            except Exception as ex:
                logging.error(ex)

    def recv(self):
        while True:
            try:
                data = self._sock.recv(BUFFER_LEN)
                if not data:
                    break
                logging.debug('recv data,current len = {},recv len = {}'.format(len(self._recv_buffer),len(data)))
                self._recv_buffer += data
                self._last_act_time = int(time.time())
            except BlockingIOError as ex:
                #logging.error(ex)
                break
            except ConnectionResetError as ex:#连接关闭
                logging.error(ex)
                raise
            except Exception as ex:
                logging.error(ex)
                raise

        #解析数据包
        while len(self._recv_buffer) > 0:
            try:
                message_type,message_length,body,data = decode_message(self._recv_buffer)
                if message_type == MessageType.SIGN_IN:
                    body = body.decode('utf-8').split(':')
                    if len(body) < 2:
                        pass
                    else:
                        self._client_config.username = body[0]
                        self._client_config.password = body[1]
                        self._send_buffer += encode_message(MessageType.SIGN_IN_ACK,1,b'\x00')
                        #认证成功，启动对外服务的监听
                        logging.info('sign in success, start listen request...')
                    
                elif message_type == MessageType.CLIENT_CONF:
                    body = body.decode('utf-8').split(':')
                    if len(body) < 2:#配置信息错误 proxy_hostname:proxy_port
                        pass
                    else:
                        self._client_config.proxy_hostname = body[0]
                        self.set_proxy_ip()
                        try:
                            self._client_config.proxy_port = int(body[1])
                        except Exception as ex:
                            logging.error('proxy port error!')
                            self._send_buffer += encode_message(MessageType.CLIENT_CONF_ERROR,1,b'\x00')
                        else:
                            self._send_buffer += encode_message(MessageType.CLIENT_CONF_ACK,1,b'\x00')
                            logging.info('client conf success!')
                            self.listen_request()
                elif message_type == MessageType.SIGN_OUT:
                    logging.info('sign out!')
                    temp = encode_message(MessageType.SIGN_OUT_ACK,1,b'\x00')
                    self._sock.sendall(temp)
                    self.dispose()

                elif message_type == MessageType.DATA:
                    #把从代理客户端收到的消息,转交给request client 发送
                    logging.debug('data packet...')
                    request_client_id = int.from_bytes(body[0:2],byteorder='big')
                    request_client = self.get_request_client_for_id(request_client_id)
                    if request_client:
                        logging.debug('request client id = {} will send!'.format(request_client_id))
                        request_client.append_send_buffer(body[2:])
                    else:
                        logging.error('not find request client , client_id = {}'.format(request_client_id))
                elif message_type == MessageType.KEEP_ALIVE:
                    self._send_buffer += encode_message(MessageType.KEEP_ALIVE,1,b'\x00')
                    logging.info('keep alive...')
                elif message_type == MessageType.LOCAL_SERVICE_ERROR:
                    #给代理客户端回应ACK
                    self._send_buffer += encode_message(MessageType.LOCAL_SERVICE_ERROR_ACK,1,b'\x00')
                    #给request client 回应错误消息
                    request_client_id = int.from_bytes(body[0:2],byteorder='big')
                    request_client = self.get_request_client_for_id(request_client_id)
                    if request_client:
                        content = self.error_content(
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
                            HTTPStatus.INTERNAL_SERVER_ERROR.description)
                        logging.debug('request client id = {} ,error msg will send!'.format(request_client_id))
                        request_client.append_send_buffer(content)
                    else:
                        logging.error('not find request client , client_id = {}'.format(request_client_id))

                else:
                    logging.error('unknow message!')
                self._recv_buffer = data
            except MessageError as ex:
                logging.error(ex)
                break
            except Exception as e:
                logging.error(e)
                break

    def error_content(self,code, message=None, explain=None):
        self._headers_buffer.clear()
        self._headers_buffer.append(("%s %d %s\r\n" %
                    (self.protocol_version, code, message)).encode(
                        'latin-1', 'strict'))
        error_message_format = DEFAULT_ERROR_MESSAGE
        error_content_type = DEFAULT_ERROR_CONTENT_TYPE
        content = (error_message_format % {
                'code': code,
                'message': html.escape(message, quote=False),
                'explain': html.escape(explain, quote=False)
            })
        body = content.encode('UTF-8', 'replace')
        self.send_header('Server', self.server_version)
        self.send_header('Date', self.date_time_string())
        self.send_header("Content-Type", error_content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_header()

        return b''.join(self._headers_buffer) + body