from django.db import migrations, models
from django.utils.crypto import salted_hmac


def populate_password_digests(apps, schema_editor):
    challenge_model = apps.get_model("app", "PasswordResetChallenge")
    for challenge in challenge_model.objects.select_related("user").iterator():
        challenge.password_digest = salted_hmac(
            "app.password-reset.password-state",
            challenge.user.password,
        ).hexdigest()
        challenge.save(update_fields=["password_digest"])


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0018_alter_passwordresetchallenge_expires_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="passwordresetchallenge",
            name="password_digest",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(
            populate_password_digests,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="passwordresetchallenge",
            name="password_digest",
            field=models.CharField(max_length=64),
        ),
    ]
