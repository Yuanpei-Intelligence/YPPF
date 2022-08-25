from django import forms
from django.db.models import fields


class UserForm(forms.Form):
    username = forms.CharField(label="username", max_length=128)
    password = forms.CharField(
        label="password", max_length=256, widget=forms.PasswordInput
    )


# 设置字段的 widget 的 multiple HTML 属性
class FileFieldForm(forms.Form):
    file_field = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"multiple": True})
    )

