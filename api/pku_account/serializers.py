"""
Serializers of the 北大账号 mini-program API (``timetable/README.md`` §3.4).

``BindingSerializer`` only documents the response produced by
``pku_account.services.binding_payload``; the views return that dict as is.
"""
from rest_framework import serializers

__all__ = [
    'PkuLoginSerializer',
    'PkuConsentsSerializer',
    'PortalSessionSerializer',
    'ConsentsSerializer',
    'BindingSerializer',
    'ApiErrorSerializer',
]


class PkuLoginSerializer(serializers.Serializer):
    """Credentials for one IAAA login plus optional consent decisions."""

    username = serializers.CharField(
        max_length=32, help_text='北大统一身份认证账号（学号 / 职工号）',
    )
    # write_only + password style: DRF never echoes the value back, neither
    # in validation errors nor in the browsable API / schema examples.
    password = serializers.CharField(
        max_length=128,
        write_only=True,
        trim_whitespace=False,
        style={'input_type': 'password'},
        help_text='统一身份认证密码，仅用于本次登录，不会被保存',
    )
    consent_timetable = serializers.BooleanField(
        required=False, help_text='是否同意平台获取并存储门户课表',
    )
    consent_grades = serializers.BooleanField(
        required=False, help_text='是否同意平台获取并存储成绩',
    )


class PkuConsentsSerializer(serializers.Serializer):
    """Partial update of the consent flags; omitted keys stay unchanged."""

    timetable = serializers.BooleanField(required=False)
    grades = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('请至少提供一个授权项')
        return attrs


class PortalSessionSerializer(serializers.Serializer):
    alive = serializers.BooleanField(
        allow_null=True,
        help_text='true=已有会话且未失效；false=会话已失效；null=没有会话',
    )
    last_ok_at = serializers.DateTimeField(allow_null=True)
    invalid_reason = serializers.CharField(allow_blank=True)


class ConsentsSerializer(serializers.Serializer):
    timetable = serializers.BooleanField()
    grades = serializers.BooleanField()


class BindingSerializer(serializers.Serializer):
    """The ``Binding`` shape; datetimes are naive local ISO 8601 strings."""

    bound = serializers.BooleanField()
    pku_username = serializers.CharField(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)
    last_login_at = serializers.DateTimeField(allow_null=True)
    last_sync_at = serializers.DateTimeField(allow_null=True)
    session = PortalSessionSerializer()
    consents = ConsentsSerializer()
    locked_until = serializers.DateTimeField(allow_null=True)


class ApiErrorSerializer(serializers.Serializer):
    """``{code, message}``; ``message`` is what the mini-program shows."""

    code = serializers.CharField()
    message = serializers.CharField()
