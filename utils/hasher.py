import hashlib


class MyMD5Hasher(object):

    def __init__(self, salt: str):
        self.salt = salt

    def encode(self, message: str) -> str:
        assert message is not None
        message_encoded = (message + self.salt).encode("utf-8")
        return hashlib.md5(message_encoded).hexdigest().upper()

    def verify(self, message: str, encoded: str) -> bool:
        return encoded.upper() == self.encode(message).upper()


class MySHA256Hasher(object):
    def __init__(self, secret: str):
        self.secret = secret

    def encode(self, identifier: str) -> str:
        assert identifier is not None
        plain = (identifier + self.secret).encode("utf-8")
        return hashlib.sha256(plain).hexdigest().upper()

    def verify(self, identifier: str, encoded: str) -> bool:
        return encoded.upper() == self.encode(identifier).upper()
