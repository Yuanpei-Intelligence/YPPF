from django import forms


class StrictBooleanField(forms.Field):
    """只接受 JSON 布尔值，拒绝字符串或 0/1。"""

    def to_python(self, value):
        if isinstance(value, bool):
            return value
        raise forms.ValidationError('status must be a boolean', code='invalid')


class ShowPositionStatusForm(forms.Form):
    """个人职务展示开关的窄输入校验。"""

    id = forms.IntegerField(min_value=1)
    status = StrictBooleanField()
