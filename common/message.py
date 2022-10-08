# coding: utf-8

from enum import Enum, IntEnum
from common.exception import MessageError
'''
message
2   | 2 |...
type|len|data
'''
#message_type + data_length
HEADER_LENGTH = 2 + 4


class MessageType(IntEnum):
    #链路保持，每30秒发送一次，消息体为b'00'
    KEEP_ALIVE = 0x0000
    #登录
    SIGN_IN = 0X0001
    SIGN_IN_ACK = 0X1001
    #登出
    SIGN_OUT = 0x0002
    SIGN_OUT_ACK = 0X1002
    #透传数据包
    DATA = 0X0008
    #客户端上传配置
    CLIENT_CONF = 0X0003
    CLIENT_CONF_ERROR = 0X8003
    CLIENT_CONF_ACK = 0X1003

    #本地服务错误
    LOCAL_SERVICE_ERROR = 0X0004
    LOCAL_SERVICE_ERROR_ACK = 0x8004


def encode_message(message_type,len,data):
    message = b''
    message += int.to_bytes(message_type,length=2,byteorder='big')
    message += int.to_bytes(len,length=4,byteorder='big')
    message += data
    return message

def decode_message(buffer):
    if len(buffer) < HEADER_LENGTH:
        raise MessageError('len = {} ,too short'.format(len(buffer)),0) 
    message_type = int.from_bytes(buffer[0:2],byteorder='big')
    message_length = int.from_bytes(buffer[2:6],byteorder='big')
    body = b''
    data = b''
    if len(buffer) >= HEADER_LENGTH+message_length:
        body = buffer[HEADER_LENGTH:HEADER_LENGTH + message_length]
        data = buffer[HEADER_LENGTH+message_length:]
    else:
        raise MessageError('error message, body is short!',-1)

    return message_type,message_length,body,data


if __name__ == '__main__':
    print(MessageType.KEEP_ALIVE.name,MessageType.KEEP_ALIVE)
    print(int.to_bytes(MessageType.SIGN_IN.value,length=4,byteorder='big'))
