from django.db import models


class SemesterType(models.Model):

    ty_name = models.CharField(max_length=20)


class Semester(models.Model):
    """
    Semetsters should not overlap.
    """

    year = models.IntegerField()
    ty = models.ForeignKey(SemesterType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
