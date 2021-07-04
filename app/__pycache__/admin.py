from django.contrib import admin
from app.models import *
# Register your models here.
class Newstudent(admin.ModelAdmin):
    list_display = ['sno','sname','username','sgender','syear','semail','sclass','smajor','stel']
    search_fields = ('sname','sno')
class NewOrg(admin.ModelAdmin):
    list_display = ['organization_name','department']

class NewPos(admin.ModelAdmin):
    list_display = ['position_stu','from_organization','job']
    
admin.site.register(student,Newstudent)
admin.site.register(organization, NewOrg)
admin.site.register(position, NewPos)
