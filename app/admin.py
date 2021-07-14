from django.contrib import admin
from app.models import *
# Register your models here.
class Newstudent(admin.ModelAdmin):
    list_display = ['pno','pname','username','pgender','pyear','pemail','pclass','pmajor','ptel','firstTimeLogin']
    search_fields = ('pname','pno')
class NewOrg(admin.ModelAdmin):
    list_display = ['organization_name','department']
    search_fields = ('organization_name','department')
class NewPos(admin.ModelAdmin):
    list_display = ['position_stu','from_organization','job']
    search_fields = ('position_stu__sname','from_organization__organization_name','position_stu__pno')
admin.site.register(NaturalPeople,Newstudent)
admin.site.register(organization, NewOrg)
admin.site.register(position, NewPos)