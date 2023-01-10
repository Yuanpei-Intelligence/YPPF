import hashlib


class MySHA256Hasher(object):
    def __init__(self, secret: str):
        self.secret = secret

    def encode(self, identifier: str) -> str:
        assert identifier is not None
        plain = (identifier + self.secret).encode("utf-8")
        return hashlib.sha256(plain).hexdigest().upper()

    def verify(self, identifier: str, encoded: str) -> bool:
        encoded_2 = self.encode(identifier)
        return encoded.upper() == encoded_2.upper()
