from django import forms

class UserForm(forms.Form):
    username = forms.CharField(label='username', max_length=128)
    password = forms.CharField(label='password', max_length=256, widget=forms.PasswordInput)