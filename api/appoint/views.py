"""
REST APIs for appointment management.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, date
from urllib.parse import unquote
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db import transaction
from django.db.models import QuerySet

from Appointment.models import (
    Appoint,
    LongTermAppoint,
    Room,
    College_Announcement,
    Participant,
)
from Appointment.extern.wechat import MessageType, notify_appoint
from Appointment.utils.utils import get_conflict_appoints, get_total_appoint_time, get_overlap_appoints
from Appointment.utils.log import logger, get_user_logger
import Appointment.utils.web_func as web_func
from Appointment.utils.identity import get_auditor_ids, get_avatar, get_or_create_participant
from Appointment.utils.identity import get_member_ids
from Appointment.appoint.manage import cancel_appoint, create_appoint, create_require_num
from Appointment import jobs
from Appointment.config import appointment_config as CONFIG
from api.authentication import WxJWTAuthentication
from api.appoint.serializers import (
    CancelAppointSerializer,
    RenewLongtermAppointSerializer,
    AccountResponseSerializer,
    CreditResponseSerializer,
    IndexResponseSerializer,
    ArrangeTimeResponseSerializer,
    ArrangeTalkRoomResponseSerializer,
    AgreementResponseSerializer,
    CheckoutAppointRequestSerializer,
    CheckoutAppointResponseSerializer,
    AppointDisplaySerializer,
    LongtermAppointDisplaySerializer,
    UserInfoSerializer,
    ViolationAppointSerializer,
    RoomSerializer,
    RoomStatisticsSerializer,
    RoomInfoSerializer,
    CollegeAnnouncementSerializer,
    DayRangeSerializer,
    RoomTimeSlotSerializer,
)
from api.appoint.utils import (
    notify_longterm_review,
    calculate_appointment_datetime,
    get_content_students,
)
from generic.models import User
from Appointment.models import Participant
from django.db.models import QuerySet, Q
# 一些固定值
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


class AppointViewSet(viewsets.ViewSet):
    """
    ViewSet for managing appointments.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        description="Cancel an appointment or long-term appointment",
        request=CancelAppointSerializer,
        responses={
            200: OpenApiResponse(
                description="Appointment canceled successfully",
                response={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "room_name": {"type": "string"},
                    },
                },
            ),
            400: OpenApiResponse(description="Invalid request or appointment not found"),
            403: OpenApiResponse(description="Permission denied"),
        },
        tags=['预约'],
    )
    @action(detail=False, methods=['post'], url_path='cancel')
    def cancel(self, request):
        """Cancel an appointment or long-term appointment."""
        serializer = CancelAppointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cancel_type = serializer.validated_data['type']
        pk = serializer.validated_data['cancel_id']

        if cancel_type == "longterm":
            try:
                longterm_appoint = LongTermAppoint.objects.get(pk=pk)
                assert longterm_appoint.status in [
                    LongTermAppoint.Status.REVIEWING,
                    LongTermAppoint.Status.APPROVED,
                ]
                assert longterm_appoint.get_applicant_id() == request.user.username
                assert longterm_appoint.sub_appoints().filter(
                    Astatus=Appoint.Status.APPOINTED).exists()
            except:
                raise ValidationError("长期预约不存在或没有权限取消!")

            try:
                with transaction.atomic():
                    longterm_appoint: LongTermAppoint = (
                        LongTermAppoint.objects.select_for_update().get(pk=pk))
                    count = longterm_appoint.cancel()
            except:
                logger.exception(f"取消长期预约{pk}意外失败")
                raise ValidationError("未能取消长期预约!")

            get_user_logger(longterm_appoint).info(
                f"成功取消长期预约{pk}及{count}条未开始的预约")
            appoint_room_name = str(longterm_appoint.appoint.Room)
            return Response({
                "message": f"成功取消对{appoint_room_name}的长期预约!",
                "room_name": appoint_room_name,
                "canceled_count": count,
            }, status=status.HTTP_200_OK)

        # Regular appointment cancellation
        try:
            assert cancel_type == 'appoint'
            appoints = Appoint.objects.filter(Astatus=Appoint.Status.APPOINTED)
            appoint: Appoint = appoints.get(pk=pk)
        except:
            raise NotFound("预约不存在、已经开始或者已取消!")

        try:
            assert appoint.get_major_id() == request.user.username
        except:
            raise PermissionDenied("请不要尝试取消不是自己发起的预约!")

        if (CONFIG.restrict_cancel_time
                and appoint.Astart < datetime.now() + timedelta(minutes=30)):
            raise ValidationError("不能取消开始时间在30分钟之内的预约!")

        cancel_appoint(appoint, record=True, lock=True)
        notify_appoint(appoint, MessageType.CANCELED)
        return Response({
            "message": f"成功取消对{appoint.Room.Rtitle}的预约!",
            "room_name": appoint.Room.Rtitle,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        description="Renew a long-term appointment",
        request=RenewLongtermAppointSerializer,
        responses={
            200: OpenApiResponse(
                description="Long-term appointment renewed successfully",
                response={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "room_name": {"type": "string"},
                    },
                },
            ),
            400: OpenApiResponse(description="Invalid request or renewal failed"),
            403: OpenApiResponse(description="Permission denied"),
        },
        tags=['预约'],
    )
    @action(detail=False, methods=['post'], url_path='renew-longterm')
    def renew_longterm(self, request):
        """Renew a long-term appointment."""
        serializer = RenewLongtermAppointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pk = serializer.validated_data['longterm_id']
        times = serializer.validated_data['times']

        try:
            longterm_appoint: LongTermAppoint = LongTermAppoint.objects.get(
                pk=pk)
            assert longterm_appoint.get_applicant_id() == request.user.username
            assert longterm_appoint.status == LongTermAppoint.Status.APPROVED
        except:
            raise ValidationError("长期预约不存在或不符合续约要求!")

        total_times = longterm_appoint.times + times
        if total_times > CONFIG.longterm_max_time:
            raise ValidationError(f"总周数不能超过{CONFIG.longterm_max_time}周!")
        if total_times * longterm_appoint.interval > CONFIG.longterm_max_week:
            raise ValidationError(f"总周数不能超过{CONFIG.longterm_max_week}周!")

        conflict, conflict_appoints = longterm_appoint.renew(times)
        if conflict is None:
            get_user_logger(longterm_appoint).info(f"对长期预约{pk}发起{times}周续约")
            return Response({
                "message": f"成功对{longterm_appoint.appoint.Room}的长期预约进行了{times}周的续约!",
                "room_name": str(longterm_appoint.appoint.Room),
            }, status=status.HTTP_200_OK)
        else:
            raise ValidationError(f"续约第{conflict}次失败，后续时间段存在预约冲突!")


class MyAppointmentsView(APIView):
    """
    Get user's appointment information.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取用户预约信息",
        description="返回当前用户的预约信息，包括未来预约、过去预约和长期预约",
        responses={
            200: AccountResponseSerializer,
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get user's appointment information."""
        Pid = request.user.username
        my_info = web_func.get_user_info(Pid)
        participant = get_or_create_participant(request)
        if participant.agree_time is not None:
            my_info['agree_time'] = str(participant.agree_time)

        has_longterm_permission = participant.longterm
        img_path = get_avatar(request.user)

        # 获取过去和未来的预约信息
        appoint_list_future = []
        appoint_list_past = []

        for appoint in web_func.get_appoints(Pid, 'future').order_by('Astart'):
            appoint_info = web_func.appointment2Display(appoint, 'future', Pid)
            appoint_list_future.append(appoint_info)

        for appoint in web_func.get_appoints(Pid, 'past').order_by('-Astart'):
            appoint_info = web_func.appointment2Display(appoint, 'past', Pid)
            appoint_list_past.append(appoint_info)

        response_data = {
            'user_info': my_info,
            'img_path': img_path,
            'has_longterm_permission': has_longterm_permission,
            'appoint_list_future': appoint_list_future,
            'appoint_list_past': appoint_list_past,
            'show_admin': (request.user.is_superuser or request.user.is_staff),
        }

        if has_longterm_permission:
            # 获取长期预约数据
            appoint_list_longterm = []
            longterm_appoints = LongTermAppoint.objects.filter(
                applicant=participant).order_by('-appoint__Astart')
            # 判断是否达到上限
            count = LongTermAppoint.objects.activated().filter(applicant=participant).count()
            is_full = count >= CONFIG.longterm_max_num
            for longterm_appoint in longterm_appoints:
                appoint_info = web_func.appointment2Display(
                    longterm_appoint.appoint, 'longterm')

                # 判断是否可以续约
                last_start = longterm_appoint.appoint.Astart + timedelta(
                    weeks=(longterm_appoint.times - 1) * longterm_appoint.interval)

                renewable = (longterm_appoint.status == LongTermAppoint.Status.APPROVED
                             and datetime.now() > last_start - timedelta(weeks=2)
                             and datetime.now() < last_start)

                data = {
                    'longterm_id': longterm_appoint.pk,
                    'appoint': appoint_info,
                    'times': longterm_appoint.times,
                    'interval': longterm_appoint.interval,
                    'status': longterm_appoint.get_status_display(),
                    'renewable': renewable,
                    'review_comment': longterm_appoint.review_comment,
                }
                appoint_list_longterm.append(data)

            response_data.update({
                'appoint_list_longterm': appoint_list_longterm,
                'longterm_count': count,
                'is_full': is_full,
            })

        serializer = AccountResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MyViolationsView(APIView):
    """
    Get user's violation records.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取违约记录",
        description="返回当前用户的违约记录",
        responses={
            200: CreditResponseSerializer,
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get user's violation records."""
        Pid = request.user.username
        my_info = web_func.get_user_info(Pid)
        participant = get_or_create_participant(request)
        if participant.agree_time is not None:
            my_info['agree_time'] = str(participant.agree_time)

        img_path = get_avatar(request.user)
        vio_list = web_func.get_appoints(Pid, 'violate', major=True)

        vio_list_display = web_func.appoints2json(vio_list)
        for x, appoint in zip(vio_list_display, vio_list):
            x['Astart_hour_minute'] = appoint.Astart.strftime("%I:%M %p")
            x['Afinish_hour_minute'] = appoint.Afinish.strftime("%I:%M %p")

        response_data = {
            'user_info': my_info,
            'img_path': img_path,
            'vio_list': vio_list_display,
            'show_admin': (request.user.is_superuser or request.user.is_staff),
        }

        serializer = CreditResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class StatusView(APIView):
    """
    Get index page information including room status and announcements.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取主页信息",
        description="返回主页信息，包括房间状态、公告等",
        responses={
            200: IndexResponseSerializer,
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get index page information."""
        room_list = Room.objects.all()
        now, tomorrow = datetime.now(), datetime.today() + timedelta(days=1)
        occupied_rooms = set(Appoint.objects.not_canceled().filter(
            Astart__lte=now + timedelta(minutes=15),
            Afinish__gte=now).values_list('Room__Rid', flat=True))
        future_appointments = Appoint.objects.not_canceled().filter(
            Astart__gte=now + timedelta(minutes=15), Astart__lt=tomorrow)
        room_appointments = {room.Rid: None for room in room_list}
        for appointment in future_appointments:
            room_appointments[appointment.Room.Rid] = min(
                room_appointments[appointment.Room.Rid] or timedelta(1), appointment.Astart - now)

        def format_time(delta):
            if delta is None:
                return None
            hour, rem = divmod(delta.seconds, 3600)
            return f"{rem // 60}min" if hour == 0 else f"{hour}h{rem // 60}min"

        # 地下室状态部分
        function_room_list = Room.objects.function_rooms().order_by('Rid')
        unlimited_rooms = room_list.unlimited().order_by('-Rtitle')
        statistics_info = [
            {
                'room': RoomSerializer(room).data,
                'occupancy_percentage': (room.Rpresent * 10) // (room.Rmax or 1)
            }
            for room in unlimited_rooms
        ]

        # 研讨室占用情况
        talk_room_list = Room.objects.talk_rooms().order_by('Rid')
        room_info = [
            {
                'room': RoomSerializer(room).data,
                'is_occupied': room.Rid in occupied_rooms,
                'next_available_time': format_time(room_appointments[room.Rid])
            }
            for room in talk_room_list
        ]

        # 俄文楼部分
        russian_room_list = Room.objects.russian_rooms().order_by('Rid')

        # 处理学院公告
        announcements = College_Announcement.objects.filter(
            show=College_Announcement.Show_Status.Yes)

        response_data = {
            'function_room_list': [RoomSerializer(room).data for room in function_room_list],
            'statistics_info': statistics_info,
            'talk_room_list': [RoomSerializer(room).data for room in talk_room_list],
            'room_info': room_info,
            'russian_room_list': [RoomSerializer(room).data for room in russian_room_list],
            'russ_len': len(russian_room_list),
            'announcements': [CollegeAnnouncementSerializer(ann).data for ann in announcements] if announcements else [],
            'show_admin': (request.user.is_superuser or request.user.is_staff),
        }

        serializer = IndexResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AgreementView(APIView):
    """
    Handle agreement signing.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取协议信息",
        description="返回用户的协议签署信息",
        responses={
            200: AgreementResponseSerializer,
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get agreement information."""
        participant = get_or_create_participant(request)
        response_data = {}
        if participant.agree_time is not None:
            response_data['agree_time'] = str(participant.agree_time)
        else:
            response_data['agree_time'] = None

        serializer = AgreementResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="签署协议",
        description="用户签署协议",
        request=None,
        responses={
            200: OpenApiResponse(
                description="协议签署成功",
                response={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                    },
                },
            ),
            400: OpenApiResponse(description="签署失败"),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def post(self, request):
        """Sign the agreement."""
        try:
            participant = get_or_create_participant(request)
            with transaction.atomic():
                participant = Participant.objects.select_for_update().get(pk=participant.pk)
                participant.agree_time = datetime.now().date()
                participant.save()
            return Response({
                "message": "协议签署成功!",
            }, status=status.HTTP_200_OK)
        except:
            raise ValidationError("签署失败，请重试！")


class ArrangeTimeView(APIView):
    """
    Get appointment time arrangement for a room.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取预约时间安排",
        description="返回指定房间的预约时间安排信息",
        parameters=[
            OpenApiParameter(
                name='Rid',
                description='Room ID',
                required=True,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='start_week',
                description='Start week (0 for this week, 1 for next week)',
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1],
            ),
        ],
        responses={
            200: ArrangeTimeResponseSerializer,
            400: OpenApiResponse(description="Invalid room ID or parameters"),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get appointment time arrangement for a room."""
        has_longterm_permission = get_or_create_participant(request).longterm
        allow_overlap = CONFIG.allow_overlap
        max_appoint_time = int(CONFIG.max_appoint_time.total_seconds() // 3600)
        is_person = request.user.is_person()

        # 获取房间编号
        Rid = request.query_params.get('Rid')
        if not Rid:
            raise ValidationError("房间号不能为空!")

        try:
            room: Room = Room.objects.get(Rid=Rid)
        except Room.DoesNotExist:
            raise NotFound(f"房间号{Rid}不存在!")

        if room.Rstatus == Room.Status.FORBIDDEN:
            return Response({
                "error": "房间已被禁用",
                "room": RoomSerializer(room).data,
            }, status=status.HTTP_400_BAD_REQUEST)

        # start_week=0代表查看本周，start_week=1代表查看下周
        start_week = request.query_params.get('start_week')
        if start_week is None:
            is_longterm = False
            start_week = 0
        else:
            is_longterm = True
        try:
            start_week = int(start_week)
            assert start_week == 0 or start_week == 1
            assert has_longterm_permission or not is_longterm
        except:
            raise ValidationError("Invalid start_week parameter")

        dayrange_list, start_day, end_next_day = web_func.get_dayrange(
            day_offset=start_week * 7)

        # 获取每天剩余的可预约时长
        available_hours = {}
        for day in [start_day + timedelta(days=i) for i in range(7)]:
            used_time = get_total_appoint_time(
                get_or_create_participant(request), day)
            available_hour = CONFIG.max_appoint_time - used_time
            available_hours[day.strftime('%a')] = int(
                available_hour.total_seconds() // 3600)

        # 获取预约时间的最大时间块id
        max_stamp_id = web_func.get_time_id(
            room, room.Rfinish, mode="leftopen")

        # 定义时间块状态
        class TimeStatus:
            AVAILABLE = 0   # 可预约
            PASSED = 1      # 已过期
            NORMAL = 2      # 已被普通预约
            LONGTERM = 3    # 已被长期预约

        for day in dayrange_list:
            timesections = []
            start_hour = room.Rstart.hour
            round_up = int(room.Rstart.minute >= 30)

            # 在小程序中，时间选择被改为了左闭右开，所以最后需要多一个时间块用于边界检查
            for i in range(max_stamp_id + 1 + 1):
                timesection = {}
                timesection['starttime'] = str(
                    start_hour + (i + round_up) // 2).zfill(2) + ":" + str(
                        (i + round_up) % 2 * 30).zfill(2)
                timesection['status'] = TimeStatus.AVAILABLE
                timesection['id'] = i
                timesections.append(timesection)
            day['timesection'] = timesections

        # 筛选已经存在的预约
        appoints: QuerySet[Appoint] = Appoint.objects.not_canceled().filter(
            Room_id=Rid, Afinish__gte=start_day, Astart__date__lt=end_next_day)

        start_day_date = dayrange_list[0]
        start_day_date = date(
            start_day_date['year'], start_day_date['month'], start_day_date['day'])

        # 给出已有预约的信息
        for appoint in appoints:
            change_id_list = web_func.timerange2idlist(Rid, appoint.Astart,
                                                       appoint.Afinish,
                                                       max_stamp_id)
            appoint_usage = html.escape(appoint.Ausage).replace('\n', '<br/>')
            appointer_name = html.escape(appoint.major_student.name)

            date_id = (appoint.Astart.date() - start_day_date).days
            day = dayrange_list[date_id]

            display_info = [
                f'{appoint_usage}',
                f'预约者：{appointer_name}',
            ]
            # 根据预约类型标记该时间块的状态和信息
            time_status = TimeStatus.NORMAL
            if has_longterm_permission and appoint.Atype == Appoint.Type.LONGTERM:
                time_status = TimeStatus.LONGTERM
                max_week = CONFIG.longterm_max_week
                potential_appoints = get_conflict_appoints(
                    appoint, times=max_week, week_offset=1 - max_week,
                ).filter(major_student=appoint.major_student)
                potential_longterms = LongTermAppoint.objects.filter(
                    appoint__in=potential_appoints)
                related_longterm_appoint = None
                for longterm_appoint in potential_longterms:
                    if appoint in longterm_appoint.sub_appoints():
                        related_longterm_appoint = longterm_appoint
                        break

                if related_longterm_appoint is not None:
                    display_info.append(
                        jobs.get_longterm_display(
                            times=related_longterm_appoint.times,
                            interval_week=related_longterm_appoint.interval,
                            type="inline",
                        )
                    )
            display_info = '<br/>'.join(display_info)

            for i in change_id_list:
                day['timesection'][i]['status'] = time_status
                day['timesection'][i]['display_info'] = display_info

        # 删去今天已经过去的时间
        if start_week == 0:
            curr_stamp_id = web_func.get_time_id(room, datetime.now().time())
            for i in range(min(max_stamp_id, curr_stamp_id) + 1):
                dayrange_list[0]['timesection'][i]['status'] = TimeStatus.PASSED

        # 获取房间信息，以支持房间切换的功能
        # TODO: 在小程序中不需要，为了兼容老版本，保留了这部分代码
        function_room_list = Room.objects.function_rooms().order_by('Rid')
        talk_room_list = Room.objects.talk_rooms().order_by('Rid')

        response_data = {
            'room': RoomSerializer(room).data,
            'has_longterm_permission': has_longterm_permission,
            'allow_overlap': allow_overlap,
            'max_appoint_time': max_appoint_time,
            'is_person': is_person,
            'is_longterm': is_longterm,
            'start_week': start_week,
            'dayrange_list': dayrange_list,
            'available_hours': available_hours,  # 其实应该是半小时，比如available_hours 6 = 3小时
            'function_room_list': [RoomSerializer(room).data for room in function_room_list],
            'talk_room_list': [RoomSerializer(room).data for room in talk_room_list],
        }

        serializer = ArrangeTimeResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ArrangeTalkRoomView(APIView):
    """
    Get talk room arrangement for a specific date.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取讨论室安排",
        description="返回指定日期的讨论室或俄文楼房间安排信息",
        parameters=[
            OpenApiParameter(
                name='year',
                description='Year',
                required=True,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='month',
                description='Month',
                required=True,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='day',
                description='Day',
                required=True,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='type',
                description='Room type: "talk" for talk rooms, "russ" for Russian building rooms',
                required=True,
                type=OpenApiTypes.STR,
                enum=['talk', 'russ'],
            ),
        ],
        responses={
            200: ArrangeTalkRoomResponseSerializer,
            400: OpenApiResponse(description="Invalid date or parameters"),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get talk room arrangement for a specific date."""
        try:
            year = int(request.query_params.get("year"))
            month = int(request.query_params.get("month"))
            day = int(request.query_params.get("day"))
            check_type = str(request.query_params.get("type"))
            assert check_type in {"russ", "talk"}
            re_time = datetime(year, month, day)
            if (re_time.date() < datetime.now().date()
                    or re_time.date() - datetime.now().date() > timedelta(days=6)):
                raise ValidationError("日期超出允许范围!")
        except (ValueError, AssertionError, TypeError) as e:
            raise ValidationError(f"Invalid parameters: {str(e)}")

        is_today = False
        show_min = None
        if check_type == "talk":
            if re_time.date() == datetime.now().date():
                is_today = True
                show_min = CONFIG.today_min
            room_list = Room.objects.talk_rooms().basement_only().order_by('Rmin', 'Rid')
        else:  # type == "russ"
            room_list = Room.objects.russian_rooms().order_by('Rid')

        Rids = [room.Rid for room in room_list]
        t_start, t_finish = web_func.get_talkroom_timerange(room_list)
        t_start = web_func.time2datetime(year, month, day, t_start)
        t_finish = web_func.time2datetime(year, month, day, t_finish)
        t_range = int(((t_finish - timedelta(minutes=1)) -
                       t_start).total_seconds()) // 1800 + 1
        rooms_time_list = []

        width = 100 / len(room_list) if room_list else 0

        for sequence, room in enumerate(room_list):
            rooms_time_list.append([])
            # 在小程序中，时间选择被改为了左闭右开，所以最后需要多一个时间块用于边界检查
            for time_id in range(t_range + 1):
                rooms_time_list[-1].append({})
                rooms_time_list[sequence][time_id]['status'] = 1
                rooms_time_list[sequence][time_id]['time_id'] = time_id
                rooms_time_list[sequence][time_id]['Rid'] = Rids[sequence]
                temp_hour, temp_minute = t_start.hour, int(
                    t_start.minute >= 30)
                rooms_time_list[sequence][time_id]['starttime'] = str(
                    temp_hour + (time_id + temp_minute) // 2).zfill(2) + ":" + str(
                        (time_id + temp_minute) % 2 * 30).zfill(2)

        # 考虑三部分不可预约时间
        appoints = Appoint.objects.not_canceled().filter(Room_id__in=Rids,
                                                         Astart__gte=t_start,
                                                         Afinish__lte=t_finish)

        present_time_id = int(
            (datetime.now() - t_start).total_seconds()) // 1800

        for sequence, room in enumerate(room_list):
            # case 1: 房间的预约时间范围内
            start_id = int((web_func.time2datetime(year, month, day, room.Rstart) -
                            t_start).total_seconds()) // 1800
            finish_id = int(
                ((web_func.time2datetime(year, month, day, room.Rfinish) -
                  timedelta(minutes=1)) - t_start).total_seconds()) // 1800

            for time_id in range(start_id, finish_id + 1):
                rooms_time_list[sequence][time_id]['status'] = 0

            # case 2: 过去的时间
            for time_id in range(min(present_time_id + 1, t_range)):
                rooms_time_list[sequence][time_id]['status'] = 1

            # case 3: 冲突预约
            for appointment in appoints:
                if appointment.Room.Rid == room.Rid:
                    start_id = int(
                        (appointment.Astart - t_start).total_seconds()) // 1800
                    finish_id = int(((appointment.Afinish - timedelta(minutes=1)) -
                                     t_start).total_seconds()) // 1800
                    appointer_name = html.escape(
                        appointment.major_student.name)
                    appoint_usage = html.escape(
                        appointment.Ausage).replace('\n', '<br/>')

                    for time_id in range(start_id, finish_id + 1):
                        rooms_time_list[sequence][time_id]['status'] = 1
                        rooms_time_list[sequence][time_id]['display_info'] = '<br/>'.join([
                            f'{appoint_usage}',
                            f'预约者：{appointer_name}',
                        ])

        weekday = WEEKDAYS[datetime(year, month, day).weekday()]

        response_data = {
            'rooms_time_list': rooms_time_list,
            'weekday': weekday,
            'is_today': is_today,
            'width': width,
        }
        if show_min is not None:
            response_data['show_min'] = show_min

        serializer = ArrangeTalkRoomResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CheckoutAppointView(APIView):
    """
    Handle appointment checkout (form submission and appointment creation).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="获取预约表单数据",
        description="返回预约表单所需的数据，包括可搜索的用户列表等",
        parameters=[
            OpenApiParameter(
                name='Rid',
                description='Room ID',
                required=True,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='weekday',
                description='Weekday',
                required=False,
                type=OpenApiTypes.STR,
                enum=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            ),
            OpenApiParameter(
                name='startid',
                description='Start time slot ID',
                required=False,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='endid',
                description='End time slot ID',
                required=False,
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name='start_week',
                description='Start week (0 for this week, 1 for next week)',
                required=False,
                type=OpenApiTypes.INT,
                enum=[0, 1],
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Form data for appointment checkout",
                response={
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "object",
                            "properties": {
                                "Rid": {"type": "string"},
                                "Rtitle": {"type": "string"},
                                "Rmin": {"type": "integer"},
                                "Rmax": {"type": "integer"},
                                "Rstart": {"type": "string", "format": "time"},
                                "Rfinish": {"type": "string", "format": "time"},
                                "Rpresent": {"type": "integer"},
                                "Rstatus": {"type": "integer"},
                                "status_display": {"type": "string"},
                                "RIsAllNight": {"type": "boolean"},
                                "RneedAgree": {"type": "boolean"},
                            },
                        },
                        "appoint_params": {"type": "object"},
                        "has_longterm_permission": {"type": "boolean"},
                        "has_interview_permission": {"type": "boolean"},
                        "interview_max_count": {"type": "integer"},
                        "member_ids": {"type": "array"},
                    },
                },
            ),
            400: OpenApiResponse(description="Invalid parameters"),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Get appointment checkout form data."""
        Rid = request.query_params.get('Rid')
        weekday = request.query_params.get('weekday')
        startid = request.query_params.get('startid')
        endid = request.query_params.get('endid')
        start_week = int(request.query_params.get('start_week', 0))

        if not Rid:
            raise ValidationError("房间号不能为空")

        try:
            room = Room.objects.get(Rid=Rid)
            if room.Rstatus != Room.Status.PERMITTED:
                raise ValidationError(f'房间{Rid}不可预约')
        except Room.DoesNotExist:
            raise NotFound(f"房间号{Rid}不存在")

        applicant = get_or_create_participant(request)
        has_longterm_permission = applicant.longterm
        has_interview_permission = not (applicant.longterm or applicant.hidden)
        has_interview_permission &= Rid in Room.objects.interview_room_ids()

        # Prepare appointment parameters
        appoint_params = {}
        if weekday and startid is not None and endid is not None:
            try:
                # 在小程序中，时间选择被改为了左闭右开
                # 原先是 [startid, endid]，现在变成了 [startid, endid), 所以得减1
                startid = int(startid)
                endid = int(endid) - 1
                WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                assert weekday in WEEKDAYS
                assert startid >= 0 and endid >= 0
                assert endid >= startid

                dayrange_list = web_func.get_dayrange(day_offset=0)[0]
                for day in dayrange_list:
                    if day['weekday'] == weekday:
                        appoint_params['date'] = day['date']
                        appoint_params['starttime'], valid = web_func.get_hour_time(
                            room, startid)
                        assert valid is True
                        appoint_params['endtime'], valid = web_func.get_hour_time(
                            room, endid + 1)
                        assert valid is True
                        appoint_params['year'] = day['year']
                        appoint_params['month'] = day['month']
                        appoint_params['day'] = day['day']
                        appoint_params['Rmin'] = room.Rmin
                        if start_week == 0 and datetime.now().strftime(
                                "%a") == weekday:
                            appoint_params['Rmin'] = min(
                                CONFIG.today_min, room.Rmin)
                        break
            except (ValueError, AssertionError) as e:
                raise ValidationError(f"参数错误: {str(e)}")

        appoint_params.update({
            'Rid': Rid,
            'weekday': weekday,
            'startid': startid,
            'endid': endid,
            'start_week': start_week,
            'Sid': applicant.get_id(),
            'Sname': applicant.name,
        })

        # 返回一个组织的全部成员
        member_ids = get_member_ids(request.user)

        return Response({
            'room': RoomSerializer(room).data,
            'appoint_params': appoint_params,
            'has_longterm_permission': has_longterm_permission,
            'has_interview_permission': has_interview_permission,
            'interview_max_count': CONFIG.interview_max_num,
            'member_ids': member_ids,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="提交预约",
        description="提交预约表单，创建预约或长期预约申请",
        request=CheckoutAppointRequestSerializer,
        responses={
            200: CheckoutAppointResponseSerializer,
            400: OpenApiResponse(description="Invalid request or validation failed"),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def post(self, request):
        """Submit appointment checkout and create appointment."""
        serializer = CheckoutAppointRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Extract data
        data = serializer.validated_data
        Rid = data['Rid']
        weekday = data['weekday']
        startid = data['startid']
        endid = data['endid'] - 1
        is_longterm = data.get('longterm', False)
        start_week = data.get('start_week', 0)
        is_interview = data.get('interview', False)
        times = data.get('times', 0) if is_longterm else 0
        interval = data.get('interval', 1) if is_longterm else 1
        non_yp_num = data.get('non_yp_num', 0)
        Ausage = data.get('Ausage', '')
        announcement = data.get('announcement', '')
        students = data.get('students', [])

        # Get applicant
        applicant = get_or_create_participant(request)
        has_longterm_permission = applicant.longterm
        has_interview_permission = not (applicant.longterm or applicant.hidden)
        has_interview_permission &= Rid in Room.objects.interview_room_ids()

        # ------------------------- Check parameters -------------------------
        try:
            room = Room.objects.get(Rid=Rid)
            if room.Rstatus != Room.Status.PERMITTED:
                raise ValidationError(f'房间{Rid}不可预约')
        except Room.DoesNotExist:
            raise NotFound(f"房间号{Rid}不存在")

        try:
            if is_longterm and start_week not in [0, 1]:
                raise ValidationError('预约周数必须为0或1')
            assert weekday in WEEKDAYS, '星期几无效'
            assert startid >= 0 and endid >= 0, '时间ID无效'
            assert endid >= startid, '起始时间晚于结束时间'
            assert has_longterm_permission or not is_longterm, '没有长期预约权限'
        except AssertionError as e:
            raise ValidationError(str(e))

        # Check applicant active status
        if not applicant.Sid.active:
            raise ValidationError('您现在不能预约地下室')

        # Check long-term appointment count
        if is_longterm and LongTermAppoint.objects.activated().filter(
                applicant=applicant).count() >= CONFIG.longterm_max_num:
            raise ValidationError("您的长期预约总数已超过上限")

        # Check interview
        if is_interview and not has_interview_permission:
            raise ValidationError('没有面试权限')
        if is_interview and Appoint.objects.unfinished().filter(
                major_student=applicant, Atype=Appoint.Type.INTERVIEW
        ).count() >= CONFIG.interview_max_num:
            raise ValidationError('您预约的面试次数已达到上限，结束后方可继续预约')

        # Check appointment time
        try:
            start_time, end_time = calculate_appointment_datetime(
                weekday, startid, endid, start_week, room
            )
        except (ValueError, AssertionError) as e:
            raise ValidationError(f"时间计算错误: {str(e)}")

        if (
            applicant.Sid.is_person()
            and start_time + timedelta(hours=3) < end_time
        ):
            raise ValidationError('预约时长不能超过3小时！')

        # Check total appointment time
        if (
            applicant.Sid.is_person()
            and not is_longterm
            and not is_interview
            and get_total_appoint_time(applicant, start_time.date()) + (end_time - start_time) > CONFIG.max_appoint_time
        ):
            raise ValidationError('您预约的时长已超过每日最大预约时长')

        # Check for overlapping appointments
        if (
            applicant.Sid.is_person()
            and not CONFIG.allow_overlap
            and not is_longterm
            and not is_interview
            and get_overlap_appoints(applicant, start_time, end_time).exists()
        ):
            raise ValidationError('您在该时间段已经有预约')

        # Validate usage
        if not Ausage:
            raise ValidationError('请输入房间用途!')

        # Validate announcement (ensure it's a string)
        if not isinstance(announcement, str):
            announcement = ''

        # Prepare students list
        if not students:
            students = [applicant.get_id()]
        else:
            students.append(applicant.get_id())

        students = list(filter(
            lambda sid: User.objects.get(username=sid).active,
            students
        ))

        try:
            student_participants = get_content_students(students)
        except AssertionError as e:
            raise ValidationError(str(e))

        # Determine appointment type
        appoint_type = Appoint.Type.NORMAL
        _notify = True
        if is_longterm:
            appoint_type = Appoint.Type.LONGTERM
            _notify = False
        elif is_interview:
            appoint_type = Appoint.Type.INTERVIEW
        if datetime.now().date() == start_time.date() and appoint_type == Appoint.Type.NORMAL:
            appoint_type = Appoint.Type.TODAY

        # Check participant count
        if not is_longterm:
            create_min = create_require_num(room, appoint_type)
            if 2 * len(student_participants) < create_min:
                raise ValidationError('院内使用人数需要达到房间最小人数的一半！')

        # ------------------------- Create appointment -------------------------

        # Create appointment directly, params are checked to be valid
        # but conflicts are possible, so we need to check for conflicts
        try:
            appoint, err_msg = create_appoint(
                appointer=applicant,
                students=student_participants,
                room=room,
                start=start_time,
                finish=end_time,
                usage=Ausage,
                announce=announcement,
                outer_num=non_yp_num,
                type=appoint_type,
                notify=_notify,
            )
            if appoint is None:
                raise ValidationError(err_msg or "创建预约失败")
        except Exception as e:
            logger.exception("创建预约失败")
            raise ValidationError(f"创建预约失败: {str(e)}")

        if not is_longterm:
            # Success for regular appointment
            return Response({
                'success': True,
                'message': f"预约{room.Rtitle}成功!",
                'appoint_id': appoint.pk,
                'room_name': room.Rtitle,
            }, status=status.HTTP_200_OK)
        else:
            # Long-term appointment, need to create longterm appointment object
            try:
                conflict_appoints = []
                with transaction.atomic():
                    appoint.refresh_from_db()
                    conflict_appoints = get_conflict_appoints(
                        appoint, times - 1, interval,
                        week_offset=interval, exclude_this=True, lock=True)
                    assert not conflict_appoints, "存在预约冲突"

                    longterm: LongTermAppoint = LongTermAppoint.objects.create(
                        appoint=appoint,
                        applicant=applicant,
                        times=times,
                        interval=interval,
                    )
                    # Generate subsequent appointments
                    conflict, conflict_appoints = longterm.create()
                    assert conflict is None, "创建长期预约意外失败"

                    # Notify auditors
                    auditor_ids = get_auditor_ids(longterm.applicant)
                    notify_longterm_review(longterm, auditor_ids)

                    return Response({
                        'success': True,
                        'message': "申请长期预约成功，请等待审核。",
                        'appoint_id': appoint.pk,
                        'longterm_id': longterm.pk,
                        'room_name': room.Rtitle,
                    }, status=status.HTTP_200_OK)
            except AssertionError as e:
                appoint.delete()
                if conflict_appoints:
                    conflict_appoints = sorted(conflict_appoints,
                                               key=lambda x: (x.Astart, x.Afinish))
                    raise ValidationError(
                        f"与预约时间为{conflict_appoints[0].Astart}"
                        f"-{conflict_appoints[0].Afinish}的预约发生冲突"
                    )
                raise ValidationError(str(e))
            except Exception as e:
                if appoint.pk:
                    appoint.delete()
                logger.exception("创建长期预约失败")
                raise ValidationError(f"创建长期预约失败: {str(e)}")


class SearchUsersView(APIView):
    """
    Search users for appointment participants.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [WxJWTAuthentication]

    @extend_schema(
        summary="搜索用户",
        description="根据姓名、学号、拼音等搜索可添加为预约参与者的用户",
        parameters=[
            OpenApiParameter(
                name='query',
                description='Search query (name, username, pinyin, acronym)',
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name='limit',
                description='Maximum number of results to return',
                required=False,
                type=OpenApiTypes.INT,
                default=10,
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="List of matching users",
                response={
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "User username"},
                            "name": {"type": "string", "description": "User name"},
                        },
                    },
                },
            ),
            403: OpenApiResponse(description="未登录或无权限"),
        },
        tags=['预约'],
    )
    def get(self, request):
        """Search users by name, username, pinyin or acronym."""
        query = unquote(request.query_params.get('query', ''))
        try:
            limit = int(request.query_params.get('limit', 10))
            limit = min(max(1, limit), 50)  # Limit between 1-50
        except (ValueError, TypeError):
            limit = 10

        # Filter out hidden participants and search
        users = Participant.objects.filter(
            hidden=False
        ).filter(
            Q(Sid__name__icontains=query) |
            Q(Sid__username__icontains=query) |
            Q(Sid__pinyin__icontains=query) |
            Q(Sid__acronym__icontains=query)
        ).exclude(
            Sid=request.user  # Exclude current user
        ).values('Sid__username', 'Sid__name')[:limit]

        users = [{
            'id': user['Sid__username'],
            'name': user['Sid__name'],
        } for user in users]

        return Response(users, status=status.HTTP_200_OK)
