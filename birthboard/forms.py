from django import forms
from django.contrib.auth import get_user_model

from birthboard.config import CONFIG
from birthboard.models import BirthboardRejectedIssue

User = get_user_model()

__all__ = ['BirthboardForm', 'BirthboardRejectForm']


class BirthboardForm(forms.Form):
    receiver = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label='被祝福用户',
        required=True,
    )
    senders = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label='送出用户',
        required=True,
    )
    image = forms.ImageField(label="图片", required=True)
    date = forms.DateField(label="投放日期", required=True, widget=forms.DateInput(attrs={'type': 'date'}))
    mode = forms.ChoiceField(label="投放模式", choices=[
        (0, '35元气值/1天'),
        (1, '60元气值/3天'),
        (2, '10000元气值/1年'),
    ], required=True)
    is_anonymous = forms.BooleanField(label="匿名", required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        eligible_users = User.objects.filter(
            utype__in=User.Type.Persons(),
            active=True,
        )
        self.fields['receiver'].queryset = eligible_users
        self.fields['senders'].queryset = eligible_users

    def clean_senders(self):
        """Require the authenticated creator to be a paying sender."""
        senders = self.cleaned_data['senders']
        if senders.count() > CONFIG.max_senders:
            raise forms.ValidationError(
                f'送出者人数不能超过 {CONFIG.max_senders} 人。'
            )
        if self.user is None or not senders.filter(pk=self.user.pk).exists():
            raise forms.ValidationError('发起人必须包含在送出者列表中。')
        return senders

    def clean_image(self):
        """Reject oversized uploads before image processing or persistence."""
        image = self.cleaned_data['image']
        if image.size > CONFIG.max_image_bytes:
            limit_mb = CONFIG.max_image_bytes // (1024 * 1024)
            raise forms.ValidationError(f'图片大小不能超过 {limit_mb} MB。')
        return image


class BirthboardRejectForm(forms.Form):
    """Validate the server-side contract for an administrator rejection."""
    reasons = forms.MultipleChoiceField(
        choices=BirthboardRejectedIssue.REASON_CHOICES,
        required=True,
    )
    detail = forms.CharField(required=True, max_length=1000, strip=True)
    restrict = forms.BooleanField(
        label='限制发起人 30 天',
        required=False,
    )
