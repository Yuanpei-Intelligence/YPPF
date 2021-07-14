from django.contrib.auth.hashers import BasePasswordHasher,MD5PasswordHasher ,mask_hash  
import hashlib
import json
class MyMD5PasswordHasher(MD5PasswordHasher):  
    algorithm = "mymd5"
    salt = "" 
    def __init__(self,salt):
        self.salt = salt

    def encode(self, password):  
        assert password is not None  
        password = (password+self.salt).encode('utf-8')
        hash = hashlib.md5(password).hexdigest().upper()  
        return hash  
  
    def verify(self, password, encoded):
        encoded_2 = self.encode(password)  
        return encoded.upper() == encoded_2.upper()  

class MySHA256Hasher(object):
    def __init__(self, secret):
        self.secret = secret

    def encode(self, identifier):
        assert identifier is not None
        identifier = (identifier + self.secret).encode('utf-8')
        return hashlib.sha256(identifier).hexdigest().upper()

    def verify(self, identifier, encoded):
        encoded_2 = self.encode(identifier)
        return encoded.upper() == encoded_2.upper()

def load_local_json(path='./local_json.json'):
    local_dict = {}
    with open(path, encoding='utf_8') as f:
        local_dict = json.load(f)
    return local_dict
