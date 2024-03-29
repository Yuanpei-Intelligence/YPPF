# Generated by Django 4.2.5 on 2023-10-20 22:30

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_rename_participant_participation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participation',
            name='activity',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='app.activity'),
        ),
        migrations.AlterField(
            model_name='participation',
            name='person',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='app.naturalperson'),
        ),
    ]
