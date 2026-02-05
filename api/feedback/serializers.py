"""
Serializers (schema) for feedback API.
"""
from rest_framework import serializers
from django.db import transaction

from app.models import Organization, OrganizationType
from feedback.models import FeedbackType, Feedback


class OrganizationTypeSerializer(serializers.ModelSerializer):
    """Serializer for OrganizationType."""

    class Meta:
        model = OrganizationType
        fields = [
            "otype_id",
            "otype_name",
        ]
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for Organization."""

    otype_id = serializers.IntegerField(source="otype.otype_id", read_only=True)
    otype_name = serializers.CharField(source="otype.otype_name", read_only=True)
    organization_id = serializers.IntegerField(
        source="organization_id.id", read_only=True, help_text="组织用户ID"
    )

    class Meta:
        model = Organization
        fields = [
            "organization_id",
            "oname",
            "otype_id",
            "otype_name",
        ]
        read_only_fields = fields


class FeedbackTypeSerializer(serializers.ModelSerializer):
    """Serializer for FeedbackType (list options)."""

    org_type_name = serializers.CharField(
        source="org_type.otype_name", read_only=True, allow_null=True
    )
    org_name = serializers.CharField(
        source="org.oname", read_only=True, allow_null=True
    )

    class Meta:
        model = FeedbackType
        fields = [
            "id",
            "name",
            "org_type",
            "org_type_name",
            "org",
            "org_name",
            "flexible",
        ]
        read_only_fields = fields


class FeedbackSerializer(serializers.ModelSerializer):
    """Serializer for Feedback (list/retrieve)."""

    type_name = serializers.CharField(source="type.name", read_only=True)
    org_type_name = serializers.CharField(
        source="org_type.otype_name", read_only=True, allow_null=True
    )
    org_name = serializers.CharField(
        source="org.oname", read_only=True, allow_null=True
    )
    person_name = serializers.SerializerMethodField()
    issue_status_display = serializers.CharField(
        source="get_issue_status_display", read_only=True
    )
    read_status_display = serializers.CharField(
        source="get_read_status_display", read_only=True
    )
    solve_status_display = serializers.CharField(
        source="get_solve_status_display", read_only=True
    )
    public_status_display = serializers.CharField(
        source="get_public_status_display", read_only=True
    )

    def get_person_name(self, obj):
        """Anonymous when publisher_public is False for non-involved users."""
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        from app.utils import get_person_or_org
        me = get_person_or_org(request.user)
        # 仅发布者、对应组织、教师可见发布者姓名
        if obj.person == me:
            return obj.person.get_display_name()
        if hasattr(me, "oname") and obj.org == me:
            return obj.person.get_display_name() if obj.publisher_public else "匿名"
        if getattr(me, "is_teacher", lambda: False)():
            return obj.person.get_display_name()
        if obj.public_status == Feedback.PublicStatus.PUBLIC and obj.publisher_public:
            return obj.person.get_display_name()
        return "匿名"

    class Meta:
        model = Feedback
        fields = [
            "id",
            "type",
            "type_name",
            "title",
            "content",
            "person",
            "person_name",
            "org_type",
            "org_type_name",
            "org",
            "org_name",
            "url",
            "issue_status",
            "issue_status_display",
            "read_status",
            "read_status_display",
            "solve_status",
            "solve_status_display",
            "feedback_time",
            "publisher_public",
            "org_public",
            "public_time",
            "public_status",
            "public_status_display",
            "time",
            "modify_time",
        ]
        read_only_fields = fields


class FeedbackCreateSerializer(serializers.Serializer):
    """Schema for creating feedback (draft or direct submit)."""

    type = serializers.CharField(help_text="反馈类型名称 (FeedbackType.name)")
    title = serializers.CharField(max_length=30, help_text="标题")
    content = serializers.CharField(help_text="内容")
    otype = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
        help_text="接收小组类型 (OrganizationType.otype_name)",
    )
    org = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
        help_text="接收小组 (Organization.oname)",
    )
    publisher_public = serializers.BooleanField(
        help_text="发布者是否同意公开"
    )
    post_type = serializers.ChoiceField(
        choices=[("save", "保存草稿"), ("directly_submit", "直接提交")],
        default="directly_submit",
        help_text="save=保存草稿, directly_submit=直接提交",
    )
    url = serializers.URLField(
        allow_blank=True,
        required=False,
        default="",
        help_text="相关链接",
    )

    def validate_type(self, value):
        try:
            return FeedbackType.objects.get(name=value)
        except FeedbackType.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应反馈类型，请联系管理员！")

    def validate_otype(self, value):
        if not value:
            return value
        try:
            OrganizationType.objects.get(otype_name=value)
            return value
        except OrganizationType.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应小组类型，请联系管理员！")

    def validate_org(self, value):
        if not value:
            return value
        try:
            Organization.objects.get(oname=value)
            return value
        except Organization.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应小组，请联系管理员！")

    def validate(self, attrs):
        post_type = attrs.get("post_type", "directly_submit")
        if post_type == "directly_submit":
            if len(attrs["title"]) >= 30:
                raise serializers.ValidationError({"title": "标题不能超过30字哦！"})
            if not attrs["title"].strip():
                raise serializers.ValidationError({"title": "标题不能为空哦！"})
            if not attrs.get("otype"):
                raise serializers.ValidationError(
                    {"otype": "不能不选择接收小组的类型哦！"}
                )
            if not attrs.get("org"):
                raise serializers.ValidationError(
                    {"org": "不选择接收小组就没有小组收到你的反馈了哦！请选择接收小组~"}
                )
            if not attrs.get("content", "").strip():
                raise serializers.ValidationError({"content": "反馈内容不能为空哦！"})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        from app.utils import get_person_or_org
        me = get_person_or_org(request.user)
        if not request.user.is_person():
            raise serializers.ValidationError("仅个人账号可提交反馈！")

        otype = validated_data.get("otype") or ""
        org = validated_data.get("org") or ""

        org_type = (
            OrganizationType.objects.get(otype_name=otype) if otype else None
        )
        org_obj = (
            Organization.objects.get(oname=org) if org else None
        )

        post_type = validated_data["post_type"]
        
        # 仅在提交反馈时检查（与 feedback_utils.py 第 97-98 行逻辑一致）
        if post_type == "directly_submit":
            if org_type and org_type.incharge == me:
                raise serializers.ValidationError(
                    "老师您好，本系统暂不支持给您管理的小组发送反馈！抱歉。"
                )
        issue_status = (
            Feedback.IssueStatus.DRAFTED
            if post_type == "save"
            else Feedback.IssueStatus.ISSUED
        )

        with transaction.atomic():
            feedback = Feedback.objects.create(
                type=validated_data["type"],
                title=validated_data["title"],
                content=validated_data["content"],
                person=me,
                org_type=org_type,
                org=org_obj,
                publisher_public=validated_data["publisher_public"],
                url=validated_data.get("url", "") or "",
                issue_status=issue_status,
            )
        return feedback


class FeedbackUpdateSerializer(serializers.Serializer):
    """Schema for updating feedback (modify draft or submit draft)."""

    type = serializers.CharField(
        allow_blank=True,
        required=False,
        help_text="反馈类型名称 (FeedbackType.name)",
    )
    title = serializers.CharField(max_length=30, required=False, help_text="标题")
    content = serializers.CharField(required=False, help_text="内容")
    otype = serializers.CharField(
        allow_blank=True,
        required=False,
        help_text="接收小组类型 (OrganizationType.otype_name)",
    )
    org = serializers.CharField(
        allow_blank=True,
        required=False,
        help_text="接收小组 (Organization.oname)",
    )
    publisher_public = serializers.BooleanField(required=False)
    post_type = serializers.ChoiceField(
        choices=[("modify", "修改"), ("submit_draft", "提交草稿")],
        help_text="modify=修改, submit_draft=提交草稿",
    )
    url = serializers.URLField(allow_blank=True, required=False, default="")

    def validate_type(self, value):
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return None
        try:
            return FeedbackType.objects.get(name=value)
        except FeedbackType.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应反馈类型，请联系管理员！")

    def validate_otype(self, value):
        if not value:
            return value
        try:
            OrganizationType.objects.get(otype_name=value)
            return value
        except OrganizationType.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应小组类型，请联系管理员！")

    def validate_org(self, value):
        if not value:
            return value
        try:
            Organization.objects.get(oname=value)
            return value
        except Organization.DoesNotExist:
            raise serializers.ValidationError("数据库没有对应小组，请联系管理员！")

    def validate(self, attrs):
        post_type = attrs.get("post_type")
        if post_type == "submit_draft":
            title = attrs.get("title") or getattr(
                self.instance, "title", ""
            )
            content = attrs.get("content") or getattr(
                self.instance, "content", ""
            )
            otype = attrs.get("otype", "")
            org = attrs.get("org", "")
            if len(title) >= 30:
                raise serializers.ValidationError({"title": "标题不能超过30字哦！"})
            if not str(title).strip():
                raise serializers.ValidationError({"title": "标题不能为空哦！"})
            if not otype:
                raise serializers.ValidationError(
                    {"otype": "不能不选择接收小组的类型哦！"}
                )
            if not org:
                raise serializers.ValidationError(
                    {"org": "不选择接收小组就没有小组收到你的反馈了哦！请选择接收小组~"}
                )
            if not str(content).strip():
                raise serializers.ValidationError({"content": "反馈内容不能为空哦！"})
        return attrs

    def update(self, instance, validated_data):
        request = self.context["request"]
        from app.utils import get_person_or_org
        me = get_person_or_org(request.user)

        if instance.person != me:
            raise serializers.ValidationError("只能修改自己发出的反馈！")
        if instance.issue_status != Feedback.IssueStatus.DRAFTED:
            raise serializers.ValidationError("只能修改草稿状态的反馈！")

        post_type = validated_data["post_type"]
        type_obj = validated_data.get("type") or instance.type
        title = validated_data.get("title") or instance.title
        content = validated_data.get("content") or instance.content
        otype = validated_data.get("otype", "")
        org = validated_data.get("org", "")
        org_type = (
            OrganizationType.objects.get(otype_name=otype)
            if otype
            else None
        )
        org_obj = (
            Organization.objects.get(oname=org) if org else None
        )
        publisher_public = validated_data.get(
            "publisher_public", instance.publisher_public
        )
        url = validated_data.get("url") or instance.url or ""

        if post_type == "submit_draft":
            if org_type and org_type.incharge == me:
                raise serializers.ValidationError(
                    "老师您好，本系统暂不支持给您管理的小组发送反馈！抱歉。"
                )

        with transaction.atomic():
            Feedback.objects.filter(id=instance.id).update(
                type=type_obj,
                title=title,
                content=content,
                org_type=org_type,
                org=org_obj,
                publisher_public=publisher_public,
                url=url,
                issue_status=(
                    Feedback.IssueStatus.ISSUED
                    if post_type == "submit_draft"
                    else Feedback.IssueStatus.DRAFTED
                ),
            )
        instance.refresh_from_db()
        return instance


class FeedbackListQuerySerializer(serializers.Serializer):
    """Query params for list feedback."""

    issue_status = serializers.ChoiceField(
        choices=Feedback.IssueStatus.choices,
        required=False,
        help_text="筛选发布状态",
    )
    solve_status = serializers.ChoiceField(
        choices=Feedback.SolveStatus.choices,
        required=False,
        help_text="筛选解决状态",
    )
    ordering = serializers.ChoiceField(
        choices=[
            "feedback_time",
            "-feedback_time",
            "time",
            "-time",
            "modify_time",
            "-modify_time",
        ],
        default="-feedback_time",
        required=False,
        help_text="排序字段",
    )


class OrganizationTypeMappingSerializer(serializers.Serializer):
    """Serializer for organization type and organization mapping data."""

    org_types = OrganizationTypeSerializer(many=True, help_text="所有组织类型列表")
    organizations = OrganizationSerializer(many=True, help_text="所有组织列表")
    org_type_to_orgs = serializers.DictField(
        help_text="组织类型到组织的映射，key为otype_name，value为该类型下的组织列表（oname数组）"
    )
    feedback_type_mappings = serializers.DictField(
        help_text="反馈类型到组织类型/组织的默认映射，key为反馈类型name，value包含org_type_name和org_name（可能为null）"
    )
