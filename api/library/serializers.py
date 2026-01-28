"""
Serializers for library API.
"""
from rest_framework import serializers
from yp_library.models import Book, LendRecord, Reader
from app.models import Activity


class BookSerializer(serializers.ModelSerializer):
    """Serializer for book information."""

    class Meta:
        model = Book
        fields = [
            'id',
            'identity_code',
            'title',
            'author',
            'publisher',
            'returned',
        ]
        read_only_fields = fields


class ReaderSerializer(serializers.ModelSerializer):
    """Serializer for reader information."""

    class Meta:
        model = Reader
        fields = [
            'id',
            'student_id',
        ]
        read_only_fields = fields


class LendRecordSerializer(serializers.ModelSerializer):
    """Serializer for lend record with detailed information."""

    book_title = serializers.CharField(
        source='book_id.title',
        read_only=True,
        help_text="Book title"
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
        help_text="Status display text"
    )
    type = serializers.CharField(
        read_only=True,
        help_text="Record type: normal/overtime/approaching/returned/overtime_returned"
    )

    class Meta:
        model = LendRecord
        fields = [
            'id',
            'book_id',
            'book_title',
            'lend_time',
            'due_time',
            'return_time',
            'returned',
            'status',
            'status_display',
            'type',
        ]
        read_only_fields = fields


class LendRecordListSerializer(serializers.Serializer):
    """Serializer for lend record list response."""

    id = serializers.IntegerField(help_text="Record ID")
    book_id__title = serializers.CharField(help_text="Book title")
    lend_time = serializers.DateTimeField(help_text="Lend time")
    due_time = serializers.DateTimeField(help_text="Due time")
    return_time = serializers.DateTimeField(
        help_text="Return time", allow_null=True)
    status = serializers.IntegerField(
        help_text="Record status", required=False)
    type = serializers.CharField(
        help_text="Record type: normal/overtime/approaching/returned/overtime_returned"
    )


class ActivitySerializer(serializers.ModelSerializer):
    """Serializer for library activity."""

    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
        help_text="Activity status display text"
    )

    class Meta:
        model = Activity
        fields = [
            'id',
            'title',
            'start',
            'end',
            'location',
            'introduction',
            'status',
            'status_display',
            'URL',
        ]
        read_only_fields = fields


class LibraryWelcomeSerializer(serializers.Serializer):
    """Serializer for library welcome page data."""

    activities = ActivitySerializer(many=True, help_text="Recent library activities")
    opening_time_start = serializers.CharField(help_text="Library opening time start")
    opening_time_end = serializers.CharField(help_text="Library opening time end")
    records_list = LendRecordListSerializer(
        many=True, help_text="User's borrow records")
    recommendation = BookSerializer(many=True, help_text="Recommended books")


class BookSearchQuerySerializer(serializers.Serializer):
    """Serializer for book search query parameters."""

    keywords = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Keywords to search (searches in title, author, publisher, identity_code)"
    )
    identity_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Book identity code (partial match)"
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Book title (partial match)"
    )
    author = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Book author (partial match)"
    )
    publisher = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Book publisher (partial match)"
    )
    returned = serializers.BooleanField(
        required=False,
        help_text="Filter by returned status"
    )


class LibraryConfigSerializer(serializers.Serializer):
    """Serializer for library configuration."""

    opening_time_start = serializers.CharField(help_text="Library opening time start")
    opening_time_end = serializers.CharField(help_text="Library opening time end")
    organization_name = serializers.CharField(help_text="Library organization name")
