from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaire', '0003_validate_answersheet_uniqueness'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='answersheet',
            constraint=models.UniqueConstraint(
                fields=('creator', 'survey'),
                name='unique_answersheet_creator_survey',
            ),
        ),
    ]
