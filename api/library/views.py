"""
REST APIs for library management.
"""
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from yp_library.utils import (
    PersonalAccountRequired,
    ReaderAccountError,
    ReaderAccountMissing,
    get_readers_by_user,
    search_books,
    get_lendinfo_by_readers,
    get_library_activity,
    get_recommended_or_newest_books,
)
from yp_library.config import library_config as CONFIG
from achievement.api import unlock_achievement
from api.authentication import WxJWTAuthentication
from api.exceptions import (
    APIError,
    APIErrorResponseSerializer,
    StandardizedExceptionHandlerMixin,
)
from api.library.serializers import (
    BookSearchQuerySerializer,
    BookSerializer,
    LendRecordListSerializer,
    ActivitySerializer,
    LibraryActivitiesQuerySerializer,
    LibraryWelcomeSerializer,
    LibraryConfigSerializer,
    LibraryRecommendationsQuerySerializer,
    LibraryRecordsQuerySerializer,
)


DISPLAY_ACTIVITY_NUM = 3  # Number of activities displayed on the homepage
# Number of recommended books displayed on the homepage
DISPLAY_RECOMMENDATION_NUM = 5


def error_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=APIErrorResponseSerializer,
        description=description,
    )


class LibraryViewSet(StandardizedExceptionHandlerMixin, viewsets.ViewSet):
    """
    ViewSet for library operations.

    Provides endpoints for:
    - Welcome page data (activities, opening time, records, recommendations)
    - Book search
    - User's borrow records
    - Library configuration
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        description="Get library welcome page data including activities, opening time, borrow records, and recommendations",
        responses={
            200: LibraryWelcomeSerializer,
            401: error_response("Authentication required or token invalid"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='welcome')
    def welcome(self, request):
        """
        Get library welcome page data.

        Returns:
        - activities: Recent library activities
        - opening_time_start: Library opening time start
        - opening_time_end: Library opening time end
        - records_list: User's borrow records (unreturned + returned)
        - recommendation: Randomly recommended books
        """
        # Get borrow records
        try:
            readers = get_readers_by_user(request.user)
            unreturned_records_list, returned_records_list = get_lendinfo_by_readers(
                readers)
            records_list = unreturned_records_list + returned_records_list
        except ReaderAccountError:
            records_list = []

        data = {
            "activities": list(get_library_activity(num=DISPLAY_ACTIVITY_NUM)),
            "opening_time_start": CONFIG.start_time,
            "opening_time_end": CONFIG.end_time,
            "records_list": records_list,
            "recommendation": list(get_recommended_or_newest_books(
                num=DISPLAY_RECOMMENDATION_NUM, newest=False)),
        }

        return Response(data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Search books by various criteria",
        parameters=[
            OpenApiParameter(
                name='keywords',
                description='Keywords to search (searches in title, author, publisher, identity_code)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='identity_code',
                description='Book identity code (partial match)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='title',
                description='Book title (partial match)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='author',
                description='Book author (partial match)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='publisher',
                description='Book publisher (partial match)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='returned',
                description='Filter by returned status (true/false)',
                required=False,
                type=OpenApiTypes.BOOL,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=BookSerializer(many=True),
                description="List of matching books"
            ),
            400: error_response("Invalid search parameters"),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        """
        Search books by various criteria.

        Query parameters:
        - keywords: Full-text search in title, author, publisher, identity_code
        - identity_code: Partial match
        - title: Partial match
        - author: Partial match
        - publisher: Partial match
        - returned: Filter by returned status
        """
        query_serializer = BookSearchQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search_results = search_books(**query_serializer.validated_data)

        # Unlock achievement for using library search
        unlock_achievement(request.user, "使用一次元培书房查询")

        return Response(list(search_results), status=status.HTTP_200_OK)

    @extend_schema(
        description="Get user's borrow records",
        parameters=[
            OpenApiParameter(
                name='returned',
                description='Filter by returned status (true/false/all)',
                required=False,
                type=OpenApiTypes.STR,
                enum=['true', 'false', 'all'],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=LendRecordListSerializer(many=True),
                description="List of borrow records"
            ),
            400: error_response("The person has no linked library account"),
            401: error_response("Authentication required or token invalid"),
            403: error_response("Only person accounts can view borrow records"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='records')
    def records(self, request):
        """
        Get user's borrow records.

        Query parameters:
        - returned: Filter by returned status
          - 'true': Only returned records
          - 'false': Only unreturned records
          - 'all' or not specified: All records
        """
        query_serializer = LibraryRecordsQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        returned_filter = query_serializer.validated_data["returned"]

        try:
            readers = get_readers_by_user(request.user)
        except PersonalAccountRequired as exc:
            raise PermissionDenied(
                "请切换至个人账号后查询借阅记录。"
            ) from exc
        except ReaderAccountMissing as exc:
            raise APIError(
                code="library.reader_account_missing",
                message="您的学号尚未关联书房账号。",
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc

        unreturned_records_list, returned_records_list = get_lendinfo_by_readers(
            readers)

        if returned_filter == 'true':
            records_list = returned_records_list
        elif returned_filter == 'false':
            records_list = unreturned_records_list
        else:
            records_list = unreturned_records_list + returned_records_list

        return Response(records_list, status=status.HTTP_200_OK)

    @extend_schema(
        description="Get library activities",
        parameters=[
            OpenApiParameter(
                name='num',
                description='Maximum number of activities to return (default: 3)',
                required=False,
                type=OpenApiTypes.INT,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=ActivitySerializer(many=True),
                description="List of library activities"
            ),
            400: error_response("Invalid activity query parameters"),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='activities')
    def activities(self, request):
        """
        Get library activities.

        Query parameters:
        - num: Maximum number of activities to return (default: 3)
        """
        query_serializer = LibraryActivitiesQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        num = query_serializer.validated_data["num"]

        activities = get_library_activity(num=num)
        return Response(list(activities), status=status.HTTP_200_OK)

    @extend_schema(
        description="Get recommended or newest books",
        parameters=[
            OpenApiParameter(
                name='num',
                description='Maximum number of books to return (default: 5)',
                required=False,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='newest',
                description='If true, return newest books instead of random recommendations',
                required=False,
                type=OpenApiTypes.BOOL,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=BookSerializer(many=True),
                description="List of recommended/newest books"
            ),
            400: error_response("Invalid recommendation query parameters"),
            401: error_response("Authentication required or token invalid"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='recommendations')
    def recommendations(self, request):
        """
        Get recommended or newest books.

        Query parameters:
        - num: Maximum number of books to return (default: 5)
        - newest: If true, return newest books instead of random recommendations
        """
        query_serializer = LibraryRecommendationsQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        num = query_serializer.validated_data["num"]
        newest = query_serializer.validated_data["newest"]

        books = get_recommended_or_newest_books(num=num, newest=newest)
        return Response(list(books), status=status.HTTP_200_OK)

    @extend_schema(
        description="Get library configuration (opening hours, etc.)",
        responses={
            200: LibraryConfigSerializer,
            401: error_response("Authentication required or token invalid"),
        },
        tags=['书房']
    )
    @action(detail=False, methods=['get'], url_path='config')
    def config(self, request):
        """
        Get library configuration.

        Returns:
        - opening_time_start: Library opening time start
        - opening_time_end: Library opening time end
        - organization_name: Library organization name
        """
        data = {
            "opening_time_start": CONFIG.start_time,
            "opening_time_end": CONFIG.end_time,
            "organization_name": CONFIG.organization_name,
        }
        return Response(data, status=status.HTTP_200_OK)
