from django.contrib import admin
from app.models import *
# Register your models here.
class Newstudent(admin.ModelAdmin):
    list_display = ['sno','sname','username','sgender','syear','semail','sclass','smajor','stel','firstTimeLogin']
    search_fields = ('sname','sno')
class NewOrg(admin.ModelAdmin):
    list_display = ['organization_name','department']
    search_fields = ('organization_name','department')
class NewPos(admin.ModelAdmin):
    list_display = ['position_stu','from_organization','job']
    search_fields = ('position_stu__sname','from_organization__organization_name','position_stu__sno')
admin.site.register(student,Newstudent)
admin.site.register(organization, NewOrg)
admin.site.register(position, NewPos)