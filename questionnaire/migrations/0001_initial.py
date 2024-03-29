# Generated by Django 4.2.3 on 2023-10-18 18:25

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AnswerSheet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('create_time', models.DateTimeField(auto_now_add=True, verbose_name='填写时间')),
                ('status', models.SmallIntegerField(choices=[(0, '存为草稿'), (1, '提交')], default=0, verbose_name='状态')),
                ('creator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='答卷人')),
            ],
            options={
                'verbose_name': '答卷',
                'verbose_name_plural': '答卷',
            },
        ),
        migrations.CreateModel(
            name='Survey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=50, verbose_name='标题')),
                ('description', models.TextField(blank=True, verbose_name='描述')),
                ('status', models.SmallIntegerField(choices=[(0, '审核中'), (1, '发布中'), (2, '已结束'), (3, '草稿')], default=0, verbose_name='状态')),
                ('start_time', models.DateTimeField(verbose_name='起始时间')),
                ('end_time', models.DateTimeField(verbose_name='截止时间')),
                ('time', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('creator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
            ],
            options={
                'verbose_name': '问卷',
                'verbose_name_plural': '问卷',
            },
        ),
        migrations.CreateModel(
            name='Question',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.IntegerField(verbose_name='序号')),
                ('topic', models.CharField(max_length=50, verbose_name='简介')),
                ('description', models.TextField(blank=True, verbose_name='题目描述')),
                ('type', models.CharField(choices=[('TEXT', '填空题'), ('SINGLE', '单选题'), ('MULTIPLE', '多选题'), ('RANKING', '排序题')], default='SINGLE', max_length=10, verbose_name='类型')),
                ('required', models.BooleanField(default=True, verbose_name='必填')),
                ('survey', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='questionnaire.survey', verbose_name='所属问卷')),
            ],
            options={
                'verbose_name': '题目',
                'verbose_name_plural': '题目',
                'ordering': ['survey', 'order'],
            },
        ),
        migrations.CreateModel(
            name='Choice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.IntegerField(verbose_name='序号')),
                ('text', models.TextField(verbose_name='内容')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='choices', to='questionnaire.question', verbose_name='问题')),
            ],
            options={
                'verbose_name': '选项',
                'verbose_name_plural': '选项',
                'ordering': ['question', 'order'],
            },
        ),
        migrations.CreateModel(
            name='AnswerText',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(verbose_name='内容')),
                ('answersheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='questionnaire.answersheet', verbose_name='所属答卷')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='questionnaire.question', verbose_name='问题')),
            ],
            options={
                'verbose_name': '回答',
                'verbose_name_plural': '回答',
            },
        ),
        migrations.AddField(
            model_name='answersheet',
            name='survey',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='questionnaire.survey', verbose_name='对应问卷'),
        ),
    ]
