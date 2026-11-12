from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('Appointment', '0008_participant_preview_weeks'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='room',
            options={
                'ordering': ['Rid'],
                'permissions': [
                    ('can_book_example_rooms', '可预约样例房间'),
                    ('can_access_rooms_freely', '随意进出会议室'),
                ],
                'verbose_name': '房间',
                'verbose_name_plural': '房间',
            },
        ),
        migrations.AddField(
            model_name='room',
            name='allow_free_access',
            field=models.BooleanField(
                default=False,
                help_text='预约结束时，保留具有“随意进出会议室”权限的参与者在本房间的门禁权限。',
                verbose_name='是否可被随意进出',
            ),
        ),
    ]
