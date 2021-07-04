from django.contrib.auth.hashers import BasePasswordHasher,MD5PasswordHasher ,mask_hash  
import hashlib
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

def load_local_json(path='./local_json.json'):
    local_dict = {}
    with open(path) as f:
        local_dict = json.load(f)
    return local_dict