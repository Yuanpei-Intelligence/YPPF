import re

from django import forms


class PasswordResetRequestForm(forms.Form):
    username = forms.CharField(max_length=150)
    action = forms.ChoiceField(
        choices=(("email", "email"), ("wechat", "wechat")))


class PasswordResetForm(forms.Form):
    username = forms.CharField(max_length=150)
    action = forms.ChoiceField(choices=(("reset", "reset"),))
    token = forms.CharField(max_length=512)
    new_password = forms.CharField(
        max_length=256, strip=False, widget=forms.PasswordInput)
    confirm_password = forms.CharField(
        max_length=256, strip=False, widget=forms.PasswordInput)

    def clean_token(self):
        """Reject legacy signed credentials and accept only ASCII short codes."""
        token = self.cleaned_data["token"]
        if re.fullmatch(r"[0-9]{6}", token) is None:
            raise forms.ValidationError("请输入6位数字验证码")
        return token

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("new_password")
        if password != cleaned_data.get("confirm_password"):
            raise forms.ValidationError("两次输入的密码不匹配")
        return cleaned_data
