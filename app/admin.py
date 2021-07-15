from django.contrib import admin
from app.models import *
# Register your models here.
class Newstudent(admin.ModelAdmin):
    list_display = ['pname','pid','pgender','pyear','pdorm','pstatus','TypeID','pemail','pclass','pmajor','ptel','firstTimeLogin']
    search_fields = ('pid','pname')
class NewOrg(admin.ModelAdmin):
    list_display = ['oname']
    search_fields = ('oname',)
class NewPos(admin.ModelAdmin):
    list_display = ['person','org','pos']
    search_fields = ('person__pname','org__oname','pos__person')
admin.site.register(NaturalPerson,Newstudent)
admin.site.register(Organization, NewOrg)
admin.site.register(Position, NewPos)