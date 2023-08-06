from django.contrib import admin

from questionnaire.models import *

admin.site.register(Survey)
admin.site.register(Question)
admin.site.register(Choice)
admin.site.register(AnswerSheet)
admin.site.register(AnswerText)
