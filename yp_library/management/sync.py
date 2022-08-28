from yp_library import external_models
from yp_library.models import Reader, Book, LendRecord


def update_reader():
    reader_manager = external_models.Readers.objects.using('yp_lib')
    raise NotImplementedError


def update_book():
    book_manager = external_models.BookInfo.objects.using('yp_lib')
    raise NotImplementedError


def update_records():
    records_manager = external_models.LendRecords.objects.using('yp_lib')
    raise NotImplementedError
