from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('birthboard', '0013_birthboardreminderseen'),
    ]

    operations = [
        migrations.AddField(
            model_name='birthboardcontract',
            name='restricted_until',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='限制参与至',
            ),
        ),
        migrations.AddField(
            model_name='birthboardrecord',
            name='display_takedown_pending',
            field=models.BooleanField(
                default=False,
                verbose_name='等待从投放屏下架',
            ),
        ),
        migrations.AlterField(
            model_name='birthboardrecord',
            name='status',
            field=models.CharField(
                choices=[
                    ('waiting_confirm', '等待大家确认'),
                    ('waiting_receiver', '等待寿星确认'),
                    ('waiting_approve', '等待管理员审批'),
                    ('ready', '等待投放'),
                    ('ongoing', '投放进行中'),
                    ('finished', '投放完成'),
                    ('terminated', '已终止'),
                    ('terminated_by_admin', '需要修改'),
                    ('canceled', '已撤销'),
                ],
                default='waiting_confirm',
                max_length=32,
                verbose_name='主流程状态',
            ),
        ),
    ]
