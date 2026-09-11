"""Website code login. Account/IP/device budgets are shared with password reset."""
import secrets
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils.crypto import constant_time_compare, salted_hmac

from generic.models import User
from app.models import LoginChallenge, NaturalPerson, PasswordResetChallenge
from app import utils


def login_code_digest(user_id, code):
    return salted_hmac('app.website-login.code-v1', f'{user_id}:{code}').hexdigest()


def password_state(password):
    return salted_hmac('app.website-login.password-state', password).hexdigest()


def prepare_login_delivery(request, username, channel, *, now=None):
    now = now or datetime.now()
    if not utils.check_password_reset_request_rate(request, username, now=now):
        return None
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None or not user.is_person() or not user.is_valid():
            return None
        person = NaturalPerson.objects.filter(person_id=user).first()
        if person is None:
            return None
        if channel == 'email':
            try:
                validate_email(person.email or '')
            except ValidationError:
                return None
        for _ in range(10):
            code = f'{secrets.randbelow(1_000_000):06d}'
            digest = login_code_digest(user.pk, code)
            if (not LoginChallenge.objects.filter(token_digest=digest).exists()
                    and not PasswordResetChallenge.objects.filter(
                        token_digest=utils._password_reset_code_digest(user.pk, code)).exists()):
                break
        else:
            raise RuntimeError('Login code generation exhausted retries')
        LoginChallenge.objects.filter(user=user, consumed_at__isnull=True,
                                      invalidated_at__isnull=True).update(invalidated_at=now)
        LoginChallenge.objects.create(
            user=user, token_digest=digest, password_digest=password_state(user.password),
            created_at=now, expires_at=now + timedelta(seconds=utils.PASSWORD_RESET_TOKEN_SECONDS))
        return ((person.name, person.email, code) if channel == 'email'
                else (user.username, code))


def consume_login_code(request, username, code, *, now=None):
    """Consume only LOGIN proof; never change passwords or set a reset bypass."""
    now = now or datetime.now()
    username, ip, device = utils._password_reset_context(request, username)
    identifiers = utils._password_reset_verification_identifiers(username, ip, device)
    if not utils._consume_password_reset_limits(identifiers, utils.PASSWORD_RESET_VERIFY_LIMITS, now):
        return None
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdecimal():
        return None
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username__iexact=username).first()
        if user is None or not user.is_person() or not user.is_valid():
            return None
        if not NaturalPerson.objects.filter(person_id=user).exists():
            return None
        challenge = LoginChallenge.objects.select_for_update().filter(
            user=user, consumed_at__isnull=True, invalidated_at__isnull=True).order_by('-pk').first()
        if challenge is None:
            return None
        valid = (now < challenge.expires_at
                 and challenge.failed_attempts < utils.PASSWORD_RESET_TOKEN_ATTEMPTS
                 and constant_time_compare(challenge.token_digest, login_code_digest(user.pk, code))
                 and constant_time_compare(challenge.password_digest, password_state(user.password)))
        if not valid:
            challenge.failed_attempts += 1
            if challenge.failed_attempts >= utils.PASSWORD_RESET_TOKEN_ATTEMPTS:
                challenge.invalidated_at = now
            challenge.save(update_fields=['failed_attempts', 'invalidated_at'])
            return None
        challenge.consumed_at = now
        challenge.save(update_fields=['consumed_at'])
        return user
