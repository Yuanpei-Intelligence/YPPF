"""
Serializers for mini program login/binding flow.
"""
from rest_framework import serializers


class WxCodeSerializer(serializers.Serializer):
    """Validate the code returned by ``wx.login``."""

    code = serializers.CharField(max_length=128, help_text="wx.login temporary code")


class WxBindSerializer(serializers.Serializer):
    """
    Validate credentials and the signed openid returned by the code login step.
    """

    username = serializers.CharField(max_length=150, help_text="Django username")
    password = serializers.CharField(max_length=128, help_text="Account password")
    signed_openid = serializers.CharField(help_text="Signed openid issued by backend")

