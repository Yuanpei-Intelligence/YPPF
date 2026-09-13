from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('birthboard', '0018_birthboardcontract_protocol_version'),
    ]

    operations = [
        migrations.AlterField(
            model_name='birthboardcontract',
            name='protocol_version',
            field=models.PositiveIntegerField(default=1, verbose_name='协议版本'),
        ),
    ]
