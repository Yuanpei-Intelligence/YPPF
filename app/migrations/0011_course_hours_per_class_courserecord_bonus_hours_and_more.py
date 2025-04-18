# Generated by Django 5.0.11 on 2025-02-15 21:08
# Modified by hand to satisfy the "total_hours_is_sum" constraint.
# Legacy objects keep their old values of attend_times and total_hours.
# We set bonus_hours = total_hours and hours_per_class = 0 to make sure the
# constraint is satisfied.

import django.apps.registry
import django.db.models.expressions
from django.db import migrations, models
from django.db.models import F


def set_bonus(apps: django.apps.registry.Apps, schema_editor):
    ''' Sets bonus_hours for the existing objects. '''
    CourseRecord = apps.get_model('app', 'CourseRecord')
    CourseRecord.objects.update(bonus_hours = F('total_hours'), hours_per_class = 0)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0010_homepageimage"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="hours_per_class",
            field=models.FloatField(default=2, verbose_name="每节课学时数"),
        ),
        migrations.AddField(
            model_name="courserecord",
            name="bonus_hours",
            field=models.FloatField(default=0.0, verbose_name="额外学时"),
        ),
        migrations.AddField(
            model_name="courserecord",
            name="hours_per_class",
            field=models.FloatField(default=2.0, verbose_name="每节课学时数"),
        ),
        migrations.RunPython(
            code=set_bonus,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="courserecord",
            constraint=models.CheckConstraint(
                check=models.Q(
                    (
                        "total_hours",
                        django.db.models.expressions.CombinedExpression(
                            models.F("bonus_hours"),
                            "+",
                            django.db.models.expressions.CombinedExpression(
                                models.F("attend_times"),
                                "*",
                                models.F("hours_per_class"),
                            ),
                        ),
                    )
                ),
                name="total_hours_is_sum",
            ),
        ),
    ]
