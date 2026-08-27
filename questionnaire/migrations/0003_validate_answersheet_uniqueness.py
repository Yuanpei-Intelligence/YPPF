from django.db import migrations
from django.db.models import Count


def validate_answersheet_uniqueness(apps, schema_editor):
    """Abort rather than silently discard historical duplicate sheets."""
    AnswerSheet = apps.get_model('questionnaire', 'AnswerSheet')
    duplicate_exists = (
        AnswerSheet.objects.using(schema_editor.connection.alias)
        .values('creator_id', 'survey_id')
        .annotate(record_count=Count('id'))
        .filter(record_count__gt=1)
        .exists()
    )
    if duplicate_exists:
        raise RuntimeError(
            'Duplicate questionnaire answer sheets exist for the same '
            'creator and survey. Back up the database, reconcile them '
            'according to the business retention policy, and rerun migrate. '
            'This migration deliberately does not delete submitted answers.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaire', '0002_question_min_choices_max_choices'),
    ]

    operations = [
        migrations.RunPython(
            validate_answersheet_uniqueness,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
