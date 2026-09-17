from django.apps import AppConfig
from django.db.models.signals import post_delete


class AcademicRecordConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academic_record'
    verbose_name = '成绩记录'

    def ready(self) -> None:
        # Imported here: the receivers touch models, which are not loaded
        # before the app registry is ready.
        from pku_account.models import PkuAccount
        from pku_account.signals import consent_changed
        from academic_record.receivers import (
            on_binding_deleted,
            on_consent_changed,
        )

        consent_changed.connect(
            on_consent_changed,
            dispatch_uid='academic_record.on_consent_changed',
        )
        post_delete.connect(
            on_binding_deleted, sender=PkuAccount,
            dispatch_uid='academic_record.on_binding_deleted',
        )
