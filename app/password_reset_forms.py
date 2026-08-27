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

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("new_password")
        if password != cleaned_data.get("confirm_password"):
            raise forms.ValidationError("两次输入的密码不匹配")
        return cleaned_data
