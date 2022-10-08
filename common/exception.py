# coding: utf-8
class BaseError(Exception):
    def __init__(self,msg,code=None):
        self._msg = msg
        self._code = code
    
    @property
    def msg(self):
        return self._msg
    @property
    def code(self):
        return self._code
    
    def __str__(self):
        if self._code:
            return 'msg = {},code = {}'.format(self._msg,self._code)
        else:
            return 'msg = {}'.format(self._msg)

class MessageError(BaseError):
    def __init__(self, msg, code):
        super().__init__(msg, code)

class ClientCloseError(BaseError):
    def __init__(self, msg, code):
        super().__init__(msg, code)

if __name__ == '__main__':
    a = BaseError('a','b')
    print(a)
