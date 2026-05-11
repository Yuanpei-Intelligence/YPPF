from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class BirthboardForm(forms.Form):
    receiver = forms.ModelChoiceField(queryset=User.objects.all(), label="被祝福用户", required=True)
    senders = forms.ModelMultipleChoiceField(queryset=User.objects.all(), label="送出用户", required=True)
    image = forms.ImageField(label="图片", required=True)
    date = forms.DateField(label="投放日期", required=True, widget=forms.DateInput(attrs={'type': 'date'}))
    mode = forms.ChoiceField(label="投放模式", choices=[
        (0, '35元气值/1天'),
        (1, '60元气值/3天'),
        (2, '1000元气值/1年'),
    ], required=True)
    is_anonymous = forms.BooleanField(label="匿名", required=False)
