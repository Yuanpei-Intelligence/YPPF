from django.contrib.auth.hashers import BasePasswordHasher, MD5PasswordHasher, mask_hash
import hashlib
from django.contrib import auth
from django.conf import settings
from boottest import local_dict


class MyMD5PasswordHasher(MD5PasswordHasher):
    algorithm = "mymd5"
    salt = ""

    def __init__(self, salt):
        self.salt = salt

    def encode(self, password):
        assert password is not None
        password = (password + self.salt).encode("utf-8")
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
        identifier = (identifier + self.secret).encode("utf-8")
        return hashlib.sha256(identifier).hexdigest().upper()

    def verify(self, identifier, encoded):
        encoded_2 = self.encode(identifier)
        return encoded.upper() == encoded_2.upper()


from app.models import NaturalPerson, Organization, Position


def check_user_type(request):  # return Valid(Bool), otype
    html_display = {}
    if request.user.is_superuser:
        auth.logout(request)
        return False, "", html_display
    if request.user.username[:2] == "zz":
        user_type = "Organization"
        html_display["profile_name"] = "组织主页"
        html_display["profile_url"] = "/orginfo/"
        org = Organization.objects.get(organization_id=request.user)
        html_display["avatar_path"] = get_user_ava(org)
        # 不确定Org的结构，这里先空着（组织就没有头像了）
    else:
        user_type = "Person"
        person = NaturalPerson.objects.activated().get(person_id=request.user)
        html_display["profile_name"] = "个人主页"
        html_display["profile_url"] = "/stuinfo/"
        html_display["avatar_path"] = get_user_ava(person)

    return True, user_type, html_display


def get_user_ava(obj):
    try:
        ava = obj.avatar
        assert ava != ""
        return settings.MEDIA_URL + str(ava)
    except:
        return settings.MEDIA_URL + "avatar/codecat.jpg"


def get_user_left_narbar(
    person, is_myself, html_display
):  # 获取左边栏的内容，is_myself表示是否是自己, person表示看的人
    assert (
        "is_myself" in html_display.keys()
    ), "Forget to tell the website whether this is the user itself!"
    html_display["underground_url"] = local_dict["url"]["base_url"]

    my_org_id_list = Position.objects.activated().filter(person=person).filter(pos=0)
    html_display["my_org_list"] = [w.org for w in my_org_id_list]  # 我管理的组织
    html_display["my_org_len"] = len(html_display["my_org_list"])
    return html_display


def get_org_left_narbar(org, is_myself, html_display):
    assert (
        "is_myself" in html_display.keys()
    ), "Forget to tell the website whether this is the user itself!"
    html_display["switch_org_name"] = org.oname
    return html_display

