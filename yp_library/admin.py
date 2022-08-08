from django.contrib import admin


from boottest.admin_utils import *
from yp_library.models import *


@admin.register(Reader)
class ReaderAdmin(admin.ModelAdmin):
    list_display = ["id", "student_id",]
    search_fields = ("student_id",)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ["identity_code", "title", "author", "publisher", "returned",]
    search_fields =  ("identity_code", "title", "author", "publisher",)
    
    
@admin.register(LendRecord)
class LendRecordAdmin(admin.ModelAdmin):
    list_display = ["reader_stu_id", "book_name", "lend_time", "due_time", "return_time", "returned",]
    search_fields =  ("reader_stu_id", "book_name",)
