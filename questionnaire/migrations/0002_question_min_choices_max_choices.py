from django.db import migrations, models


def set_defaults_for_existing_multiple_questions(apps, schema_editor):
    """Set min_choices=1 for existing MULTIPLE questions (max_choices remains NULL)."""
    Question = apps.get_model('questionnaire', 'Question')
    Question.objects.filter(type='MULTIPLE').update(min_choices=1)


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaire', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='max_choices',
            field=models.PositiveIntegerField(
                blank=True, help_text='仅多选题有效：回答此题最多可以选择的选项数，留空表示无上限',
                null=True, verbose_name='最多选择数'),
        ),
        migrations.AddField(
            model_name='question',
            name='min_choices',
            field=models.PositiveIntegerField(
                default=1, help_text='仅多选题有效：回答此题至少需要选择的选项数',
                verbose_name='最少选择数'),
        ),
        migrations.RunPython(
            set_defaults_for_existing_multiple_questions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
