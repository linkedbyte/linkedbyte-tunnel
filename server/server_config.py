#coding: utf-8
import sys
import os
import configparser

class ServerConfig():
    bind_ip = '0.0.0.0'
    bind_port = 9177
    ini_path = './bts.ini'

    @classmethod
    def parser(cls):
        ini_path = os.path.dirname(os.path.realpath(__file__))
        ini_path = os.path.join(ini_path,'config.ini')
        conf = configparser.ConfigParser()
        conf.read(ini_path, encoding="utf-8")
        try:
            item_common = conf['common']
        except Exception as ex:
            pass
        else:
            cls.bind_ip = item_common.get('bind_ip','0.0.0.0')
            cls.bind_port = item_common.getint('bind_port',9177)