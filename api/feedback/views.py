"""
REST APIs for feedback (反馈) management.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
)
from drf_spectacular.types import OpenApiTypes

from app.utils import get_person_or_org
from feedback.models import FeedbackType, Feedback
from feedback.feedback_utils import make_relevant_notification
from api.authentication import WxJWTAuthentication
from api.feedback.serializers import (
    FeedbackTypeSerializer,
    FeedbackSerializer,
    FeedbackCreateSerializer,
    FeedbackUpdateSerializer,
    FeedbackListQuerySerializer,
)


class FeedbackViewSet(viewsets.ViewSet):
    """
    ViewSet for feedback.

    - list: 我的反馈（个人为发出列表，组织为收到列表）
    - create: 创建反馈（草稿或直接提交，仅个人）
    - retrieve: 获取单条反馈（需有权限）
    - partial_update: 修改草稿或提交草稿（仅发布者）
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    def _get_me(self, request):
        return get_person_or_org(request.user)

    def _get_queryset(self, request):
        """当前用户可见的反馈：个人=我发出的，组织=我收到的."""
        me = self._get_me(request)
        qs = Feedback.objects.activated()
        if request.user.is_person():
            return qs.filter(person=me)
        return qs.filter(org=me)

    @extend_schema(
        description="列表：个人为「我发出的反馈」，组织为「收到的反馈」",
        parameters=[
            OpenApiParameter(
                name="issue_status",
                description="发布状态筛选",
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1, 2],
            ),
            OpenApiParameter(
                name="solve_status",
                description="解决状态筛选",
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1, 2, 3],
            ),
            OpenApiParameter(
                name="ordering",
                description="排序",
                required=False,
                type=OpenApiTypes.STR,
                enum=[
                    "feedback_time",
                    "-feedback_time",
                    "time",
                    "-time",
                    "modify_time",
                    "-modify_time",
                ],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=FeedbackSerializer(many=True),
                description="反馈列表",
            ),
        },
        tags=["反馈"],
    )
    def list(self, request):
        queryset = self._get_queryset(request)

        issue_status = request.query_params.get("issue_status")
        if issue_status is not None:
            try:
                queryset = queryset.filter(issue_status=int(issue_status))
            except ValueError:
                pass

        solve_status = request.query_params.get("solve_status")
        if solve_status is not None:
            try:
                queryset = queryset.filter(solve_status=int(solve_status))
            except ValueError:
                pass

        ordering = request.query_params.get("ordering", "-feedback_time")
        allowed = {
            "feedback_time",
            "-feedback_time",
            "time",
            "-time",
            "modify_time",
            "-modify_time",
        }
        if ordering in allowed:
            queryset = queryset.order_by(ordering)

        serializer = FeedbackSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(serializer.data)

    @extend_schema(
        description="创建反馈（保存草稿或直接提交），仅个人账号",
        request=FeedbackCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=FeedbackSerializer,
                description="创建成功",
            ),
            400: OpenApiResponse(description="参数错误"),
            403: OpenApiResponse(description="仅个人可提交反馈"),
        },
        tags=["反馈"],
    )
    def create(self, request):
        if not request.user.is_person():
            return Response(
                {"detail": "仅个人账号可提交反馈！"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = FeedbackCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save()

        post_type = serializer.validated_data.get("post_type")
        if post_type in ("directly_submit",):
            try:
                me = self._get_me(request)
                info = {
                    "post_type": post_type,
                    "org": serializer.validated_data.get("org") or "",
                }
                make_relevant_notification(feedback, info, me)
            except Exception:
                pass

        out = FeedbackSerializer(
            feedback, context={"request": request}
        )
        return Response(out.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="获取单条反馈详情（需有访问权限）",
        responses={
            200: FeedbackSerializer,
            404: OpenApiResponse(description="反馈不存在"),
            403: OpenApiResponse(description="无权限访问"),
        },
        tags=["反馈"],
    )
    def retrieve(self, request, pk=None):
        try:
            feedback = Feedback.objects.activated().get(id=pk)
        except (Feedback.DoesNotExist, ValueError):
            raise NotFound("反馈不存在")

        me = self._get_me(request)
        # 权限：发布者、对应组织、教师、或公开反馈
        if feedback.person == me or feedback.org == me:
            pass
        elif request.user.is_person() and getattr(me, "is_teacher", lambda: False)():
            pass
        elif feedback.public_status == Feedback.PublicStatus.PUBLIC:
            pass
        else:
            raise PermissionDenied("没有访问该反馈的权限")

        serializer = FeedbackSerializer(
            feedback, context={"request": request}
        )
        return Response(serializer.data)

    @extend_schema(
        description="修改草稿或提交草稿（仅发布者对草稿可操作）",
        request=FeedbackUpdateSerializer,
        responses={
            200: FeedbackSerializer,
            400: OpenApiResponse(description="参数错误或状态不允许"),
            403: OpenApiResponse(description="无权限"),
            404: OpenApiResponse(description="反馈不存在"),
        },
        tags=["反馈"],
    )
    def partial_update(self, request, pk=None):
        try:
            feedback = Feedback.objects.activated().get(id=pk)
        except (Feedback.DoesNotExist, ValueError):
            raise NotFound("反馈不存在")

        me = self._get_me(request)
        if feedback.person != me:
            raise PermissionDenied("只能修改自己发出的反馈")
        if feedback.issue_status != Feedback.IssueStatus.DRAFTED:
            raise ValidationError("只能修改草稿状态的反馈")

        serializer = FeedbackUpdateSerializer(
            feedback,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save()

        post_type = serializer.validated_data.get("post_type")
        if post_type == "submit_draft":
            try:
                info = {
                    "post_type": post_type,
                    "org": (
                        feedback.org.oname
                        if feedback.org
                        else ""
                    ),
                }
                make_relevant_notification(feedback, info, me)
            except Exception:
                pass

        out = FeedbackSerializer(
            feedback, context={"request": request}
        )
        return Response(out.data)

    @extend_schema(
        description="删除草稿（仅发布者对草稿可删）",
        responses={
            204: OpenApiResponse(description="已删除"),
            403: OpenApiResponse(description="无权限或非草稿"),
            404: OpenApiResponse(description="反馈不存在"),
        },
        tags=["反馈"],
    )
    def destroy(self, request, pk=None):
        try:
            feedback = Feedback.objects.activated().get(id=pk)
        except (Feedback.DoesNotExist, ValueError):
            raise NotFound("反馈不存在")
        me = self._get_me(request)
        if not request.user.is_person():
            return Response(
                {"detail": "仅个人可删除反馈"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if feedback.person != me:
            raise PermissionDenied("只能删除自己发出的反馈")
        if feedback.issue_status != Feedback.IssueStatus.DRAFTED:
            return Response(
                {"detail": "只能删除草稿状态的反馈"},
                status=status.HTTP_403_FORBIDDEN,
            )

        feedback.issue_status = Feedback.IssueStatus.DELETED
        feedback.save(update_fields=["issue_status"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description="获取当前用户「进行中」的反馈列表\n\n"
        "分类规则：issue_status=已发布，且解决状态为【解决中】或【未标记】。",
        parameters=[
            OpenApiParameter(
                name="ordering",
                description="排序字段（默认 -feedback_time）",
                required=False,
                type=OpenApiTypes.STR,
                enum=[
                    "feedback_time",
                    "-feedback_time",
                    "time",
                    "-time",
                    "modify_time",
                    "-modify_time",
                ],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=FeedbackSerializer(many=True),
                description="进行中的反馈列表",
            ),
            403: OpenApiResponse(description="仅个人账号可访问"),
        },
        tags=["反馈"],
    )
    @action(detail=False, methods=["get"], url_path="in-progress")
    def in_progress(self, request):
        """
        获取当前用户「进行中」的反馈列表。

        规则：
        - 仅个人账号可访问
        - 仅返回当前登录用户发出的反馈
        - issue_status=已发布
        - solve_status 为【解决中】或【未标记】
        """
        if not request.user.is_person():
            return Response(
                {"detail": "仅个人账号可查看进行中的反馈列表"},
                status=status.HTTP_403_FORBIDDEN,
            )

        me = self._get_me(request)
        queryset = (
            Feedback.objects.activated()
            .filter(person=me)
            .filter(issue_status=Feedback.IssueStatus.ISSUED)
            .filter(
                Q(solve_status=Feedback.SolveStatus.SOLVING)
                | Q(solve_status=Feedback.SolveStatus.UNMARKED)
            )
        )

        ordering = request.query_params.get("ordering", "-feedback_time")
        allowed = {
            "feedback_time",
            "-feedback_time",
            "time",
            "-time",
            "modify_time",
            "-modify_time",
        }
        if ordering in allowed:
            queryset = queryset.order_by(ordering)

        serializer = FeedbackSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        description="获取当前用户「已结束」的反馈列表\n\n"
        "分类规则：issue_status=已发布，且解决状态为【已解决】或【无法解决】。",
        parameters=[
            OpenApiParameter(
                name="ordering",
                description="排序字段（默认 -feedback_time）",
                required=False,
                type=OpenApiTypes.STR,
                enum=[
                    "feedback_time",
                    "-feedback_time",
                    "time",
                    "-time",
                    "modify_time",
                    "-modify_time",
                ],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=FeedbackSerializer(many=True),
                description="已结束的反馈列表",
            ),
            403: OpenApiResponse(description="仅个人账号可访问"),
        },
        tags=["反馈"],
    )
    @action(detail=False, methods=["get"], url_path="done")
    def done(self, request):
        """
        获取当前用户「已结束」的反馈列表。

        规则：
        - 仅个人账号可访问
        - 仅返回当前登录用户发出的反馈
        - issue_status=已发布
        - solve_status 为【已解决】或【无法解决】
        """
        if not request.user.is_person():
            return Response(
                {"detail": "仅个人账号可查看已结束的反馈列表"},
                status=status.HTTP_403_FORBIDDEN,
            )

        me = self._get_me(request)
        queryset = (
            Feedback.objects.activated()
            .filter(person=me)
            .filter(issue_status=Feedback.IssueStatus.ISSUED)
            .filter(
                Q(solve_status=Feedback.SolveStatus.SOLVED)
                | Q(solve_status=Feedback.SolveStatus.UNSOLVABLE)
            )
        )

        ordering = request.query_params.get("ordering", "-feedback_time")
        allowed = {
            "feedback_time",
            "-feedback_time",
            "time",
            "-time",
            "modify_time",
            "-modify_time",
        }
        if ordering in allowed:
            queryset = queryset.order_by(ordering)

        serializer = FeedbackSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        description="获取所有反馈类型（表单选项）",
        responses={
            200: OpenApiResponse(
                response=FeedbackTypeSerializer(many=True),
                description="反馈类型列表",
            ),
        },
        tags=["反馈"],
    )
    @action(detail=False, methods=["get"], url_path="types")
    def types(self, request):
        qs = FeedbackType.objects.all()
        serializer = FeedbackTypeSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        description="获取所有公开的反馈（公示栏用）- 返回所有已解决/无法解决且公开的反馈，不限制用户",
        parameters=[
            OpenApiParameter(
                name="ordering",
                description="排序",
                required=False,
                type=OpenApiTypes.STR,
                enum=[
                    "feedback_time",
                    "-feedback_time",
                    "time",
                    "-time",
                    "modify_time",
                    "-modify_time",
                ],
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=FeedbackSerializer(many=True),
                description="公开反馈列表",
            ),
        },
        tags=["反馈"],
    )
    @action(detail=False, methods=["get"], url_path="public")
    def public(self, request):
        """
        获取所有公开的反馈（公示栏用）
        返回所有已解决/无法解决且公开的反馈，不限制用户
        """
        queryset = (
            Feedback.objects.activated()
            .filter(public_status=Feedback.PublicStatus.PUBLIC)
            .filter(issue_status=Feedback.IssueStatus.ISSUED)
            .filter(
                Q(solve_status=Feedback.SolveStatus.SOLVED)
                | Q(solve_status=Feedback.SolveStatus.UNSOLVABLE)
            )
        )

        ordering = request.query_params.get("ordering", "-feedback_time")
        allowed = {
            "feedback_time",
            "-feedback_time",
            "time",
            "-time",
            "modify_time",
            "-modify_time",
        }
        if ordering in allowed:
            queryset = queryset.order_by(ordering)

        serializer = FeedbackSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(serializer.data)
