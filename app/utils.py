from django.contrib.auth.hashers import BasePasswordHasher,MD5PasswordHasher ,mask_hash  
import hashlib
import json
from django.contrib import auth
from django.conf import settings

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
    with open(path, encoding='unicode_escape') as f:
        local_dict = json.load(f)
    return local_dict


def check_user_type(request): # return Valid(Bool), type
    from app.models import NaturalPerson, Organization
    html_display = {}
    if request.user.is_superuser:
        auth.logout(request)
        return False,'', html_display
    if request.user.username[:2] == 'zz':
        user_type = 'Organization'
        html_display['profile_name'] = '组织主页'
        html_display['profile_url'] = '/orginfo/'
        org = Organization.objects.get(oid=request.user)
        html_display['avatar_path'] = get_user_ava(org)
        # 不确定Org的结构，这里先空着（组织就没有头像了）
    else:
        user_type = 'Person'
        person = NaturalPerson.objects.activated().get(pid=request.user)
        html_display['profile_name'] = '个人主页'
        html_display['profile_url'] = '/stuinfo/'
        html_display['avatar_path'] = get_user_ava(person)
        
    return True, user_type, html_display

def get_user_ava(obj):
    try:
        ava = obj.avatar
        assert ava != ''
        return  settings.MEDIA_URL + str(ava)
    except:
        return settings.MEDIA_URL + 'avatar/codecat.jpg'
