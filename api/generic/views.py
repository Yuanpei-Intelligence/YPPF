"""
Generic API views (e.g. homepage carousel).
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from app.models import HomepageImage, ActivityPhoto


class CarouselView(APIView):
    """
    首页轮播图数据。
    返回配置的首页图与活动总结图（每活动一张），不足时用 fallback 图。
    """
    permission_classes = [AllowAny]  # 公开接口
    authentication_classes = []

    @staticmethod
    def _build_carousel_items():
        media_url = getattr(settings, 'MEDIA_URL', '/media/')
        homepage_image = [
            {"image": media_url + filename, "redirect_url": url or ""}
            for (filename, url) in HomepageImage.objects.activated().order_by('sort_id').values_list('image', 'redirect_url')
        ]

        # 活动总结图：每活动取一张（有图的活动），最多补足到与首页图合计 9 张
        # 不再显示这一部分
        # all_photo_display = ActivityPhoto.objects.filter(
        #     type=ActivityPhoto.PhotoType.SUMMARY
        # ).order_by('-time')
        # seen_activity_ids = set()
        # count = 9 - len(homepage_image)
        photo_display = []
        # for photo in all_photo_display:
        #     if photo.activity_id not in seen_activity_ids and photo.image:
        #         photo_display.append({
        #             "image": media_url + str(photo.image),
        #             "redirect_url": "",
        #         })
        #         seen_activity_ids.add(photo.activity_id)
        #         count -= 1
        #         if count <= 0:
        #             break

        # if photo_display:
        #     # 有活动图时去掉第一张首页图（仅作封面）
        #     homepage_image = homepage_image[1:]

        items = homepage_image + photo_display
        # 如果没有活动图和首页图，则采用默认图
        if not items:
            items = [
                {"image": "/static/assets/img/homepage_fallback.jpeg", "redirect_url": "/"}]
        return items

    @extend_schema(
        summary="首页轮播图",
        description="获取首页轮播图展示的图片列表（首页配置图 + 活动总结图），每项含 image、redirect_url。",
        responses={
            200: OpenApiResponse(
                description="图片列表",
                response={
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "image": {"type": "string", "description": "图片 URL"},
                                    "redirect_url": {"type": "string", "description": "点击跳转 URL"},
                                },
                            },
                        },
                    },
                },
            ),
        },
        tags=["通用"],
    )
    def get(self, request):
        items = self._build_carousel_items()
        return Response({"items": items}, status=status.HTTP_200_OK)
