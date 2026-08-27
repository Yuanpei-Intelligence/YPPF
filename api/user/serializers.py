"""Serializers for current-user mini-program APIs."""

from rest_framework import serializers


class MeResponseSerializer(serializers.Serializer):
    """Current authenticated account and classified profile."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.CharField()
    utype = serializers.CharField()
    active = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    is_person = serializers.BooleanField()
    is_org = serializers.BooleanField()
    avatar_url = serializers.CharField()
    wallpaper_url = serializers.CharField()
    absolute_url = serializers.CharField()
    profile = serializers.DictField()


class DailyLoginResponseSerializer(serializers.Serializer):
    """Response serializer for daily login (sign-in) endpoint."""

    message = serializers.CharField(
        help_text="Sign-in result or status message",
    )
