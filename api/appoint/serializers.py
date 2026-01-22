"""
Serializers for appointment API.
"""
from rest_framework import serializers
from datetime import datetime, timedelta, date
from Appointment.models import Appoint, LongTermAppoint, Room, College_Announcement
from Appointment.config import appointment_config as CONFIG


class CancelAppointSerializer(serializers.Serializer):
    """Serializer for canceling an appointment."""
    
    type = serializers.ChoiceField(
        choices=['appoint', 'longterm'],
        help_text="Type of appointment to cancel: 'appoint' for regular appointment, 'longterm' for long-term appointment"
    )
    cancel_id = serializers.IntegerField(
        help_text="ID of the appointment or long-term appointment to cancel"
    )


class RenewLongtermAppointSerializer(serializers.Serializer):
    """Serializer for renewing a long-term appointment."""
    
    longterm_id = serializers.IntegerField(
        help_text="ID of the long-term appointment to renew"
    )
    times = serializers.IntegerField(
        min_value=1,
        help_text="Number of weeks to renew"
    )
    
    def validate_times(self, value):
        """Validate that times is within allowed range."""
        if value > CONFIG.longterm_max_time_once:
            raise serializers.ValidationError(
                f"续约周数不能超过{CONFIG.longterm_max_time_once}周"
            )
        return value


class RoomSerializer(serializers.ModelSerializer):
    """Serializer for Room model."""
    
    status_display = serializers.CharField(
        source='get_Rstatus_display',
        read_only=True,
        help_text="Room status display text"
    )
    
    class Meta:
        model = Room
        fields = [
            'Rid',
            'Rtitle',
            'Rmin',
            'Rmax',
            'Rstart',
            'Rfinish',
            'Rpresent',
            'Rstatus',
            'status_display',
            'RIsAllNight',
            'RneedAgree',
        ]
        # Note: read_only_fields should not include all fields
        # Only fields that are truly read-only should be listed
        read_only_fields = ['Rid', 'Rtitle', 'Rmin', 'Rmax', 'Rstart', 'Rfinish', 
                           'Rpresent', 'Rstatus', 'status_display', 'RIsAllNight', 'RneedAgree']


class AppointDisplaySerializer(serializers.Serializer):
    """Serializer for appointment display information.
    
    This matches the structure returned by appointment2Display which uses toJson()
    and adds additional fields like Astart_hour_minute, is_appointer, etc.
    """
    
    Aid = serializers.IntegerField()
    Rid = serializers.CharField(required=False, allow_null=True)  # Room ID from toJson
    Rtitle = serializers.CharField(required=False, allow_null=True)  # Room title from toJson
    Astart = serializers.CharField()  # ISO format string from toJson
    Afinish = serializers.CharField()  # ISO format string from toJson
    Astart_hour_minute = serializers.CharField()  # Added by appointment2Display
    Afinish_hour_minute = serializers.CharField()  # Added by appointment2Display
    Ausage = serializers.CharField(required=False, allow_null=True)
    major_student = serializers.DictField(required=False, allow_null=True)  # {Sname, Sid} from toJson
    is_appointer = serializers.BooleanField(required=False)  # Added by appointment2Display
    can_cancel = serializers.BooleanField(required=False)  # Added by appointment2Display
    Aweek = serializers.CharField(required=False)  # Added by appointment2Display for longterm
    Atype = serializers.CharField(required=False)
    Astatus = serializers.CharField(required=False)
    Atime = serializers.CharField(required=False)  # ISO format string from toJson
    Aannouncement = serializers.CharField(required=False, allow_null=True)
    Areason = serializers.IntegerField(required=False)
    yp_num = serializers.IntegerField(required=False)
    non_yp_num = serializers.IntegerField(required=False)
    students = serializers.ListField(required=False, child=serializers.DictField())


class LongtermAppointDisplaySerializer(serializers.Serializer):
    """Serializer for long-term appointment display information."""
    
    longterm_id = serializers.IntegerField()
    appoint = AppointDisplaySerializer()
    times = serializers.IntegerField()
    interval = serializers.IntegerField()
    status = serializers.CharField()
    renewable = serializers.BooleanField()
    review_comment = serializers.CharField(required=False, allow_blank=True)


class UserInfoSerializer(serializers.Serializer):
    """Serializer for user information."""
    
    id = serializers.CharField()
    name = serializers.CharField()
    credit = serializers.IntegerField()
    agree_time = serializers.DateField(required=False, allow_null=True)


class AccountResponseSerializer(serializers.Serializer):
    """Serializer for account endpoint response."""
    
    user_info = UserInfoSerializer()
    img_path = serializers.CharField()
    has_longterm_permission = serializers.BooleanField()
    appoint_list_future = AppointDisplaySerializer(many=True)
    appoint_list_past = AppointDisplaySerializer(many=True)
    appoint_list_longterm = LongtermAppointDisplaySerializer(many=True, required=False)
    longterm_count = serializers.IntegerField(required=False)
    is_full = serializers.BooleanField(required=False)
    show_admin = serializers.BooleanField()


class ViolationAppointSerializer(serializers.Serializer):
    """Serializer for violation appointment display."""
    
    Aid = serializers.IntegerField()
    Room = serializers.CharField(required=False, allow_null=True)
    Rtitle = serializers.CharField(required=False, allow_null=True)
    Rid = serializers.CharField(required=False, allow_null=True)
    Astart = serializers.CharField()  # ISO format string
    Afinish = serializers.CharField()  # ISO format string
    Astart_hour_minute = serializers.CharField()
    Afinish_hour_minute = serializers.CharField()
    Ausage = serializers.CharField(required=False, allow_null=True)
    major_student = serializers.DictField(required=False, allow_null=True)  # {Sname, Sid}
    Atype = serializers.CharField(required=False)
    Astatus = serializers.CharField(required=False)
    Atime = serializers.CharField(required=False)
    Aannouncement = serializers.CharField(required=False, allow_null=True)
    Areason = serializers.IntegerField(required=False)
    yp_num = serializers.IntegerField(required=False)
    non_yp_num = serializers.IntegerField(required=False)
    students = serializers.ListField(required=False, child=serializers.DictField())


class CreditResponseSerializer(serializers.Serializer):
    """Serializer for credit endpoint response."""
    
    user_info = UserInfoSerializer()
    img_path = serializers.CharField()
    vio_list = ViolationAppointSerializer(many=True)
    show_admin = serializers.BooleanField()


class CollegeAnnouncementSerializer(serializers.ModelSerializer):
    """Serializer for college announcement."""
    
    class Meta:
        model = College_Announcement
        fields = ['id', 'announcement', 'show']
        read_only_fields = fields


class RoomStatisticsSerializer(serializers.Serializer):
    """Serializer for room statistics."""
    
    room = RoomSerializer()
    occupancy_percentage = serializers.IntegerField()


class RoomInfoSerializer(serializers.Serializer):
    """Serializer for room information with occupancy status."""
    
    room = RoomSerializer()
    is_occupied = serializers.BooleanField()
    next_available_time = serializers.CharField(required=False, allow_null=True)


class IndexResponseSerializer(serializers.Serializer):
    """Serializer for index endpoint response."""
    
    function_room_list = RoomSerializer(many=True)
    statistics_info = RoomStatisticsSerializer(many=True)
    talk_room_list = RoomSerializer(many=True)
    room_info = RoomInfoSerializer(many=True)
    russian_room_list = RoomSerializer(many=True)
    russ_len = serializers.IntegerField()
    announcements = CollegeAnnouncementSerializer(many=True, required=False)
    show_admin = serializers.BooleanField()


class TimeSectionSerializer(serializers.Serializer):
    """Serializer for time section in arrange_time."""
    
    starttime = serializers.CharField()
    status = serializers.IntegerField()
    id = serializers.IntegerField()
    display_info = serializers.CharField(required=False, allow_null=True)


class DayRangeSerializer(serializers.Serializer):
    """Serializer for day range in arrange_time."""
    
    weekday = serializers.CharField()
    date = serializers.CharField()
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    day = serializers.IntegerField()
    timesection = TimeSectionSerializer(many=True)


class ArrangeTimeResponseSerializer(serializers.Serializer):
    """Serializer for arrange_time endpoint response."""
    
    room = RoomSerializer()
    has_longterm_permission = serializers.BooleanField()
    allow_overlap = serializers.BooleanField()
    max_appoint_time = serializers.IntegerField()
    is_person = serializers.BooleanField()
    is_longterm = serializers.BooleanField()
    start_week = serializers.IntegerField()
    dayrange_list = DayRangeSerializer(many=True)
    available_hours = serializers.DictField(child=serializers.IntegerField())
    function_room_list = RoomSerializer(many=True)
    talk_room_list = RoomSerializer(many=True)


class RoomTimeSlotSerializer(serializers.Serializer):
    """Serializer for room time slot in arrange_talk_room."""
    
    status = serializers.IntegerField()
    time_id = serializers.IntegerField()
    Rid = serializers.CharField()
    starttime = serializers.CharField()
    display_info = serializers.CharField(required=False, allow_null=True)


class ArrangeTalkRoomResponseSerializer(serializers.Serializer):
    """Serializer for arrange_talk_room endpoint response."""
    
    rooms_time_list = serializers.ListField(
        child=serializers.ListField(child=RoomTimeSlotSerializer())
    )
    weekday = serializers.CharField()
    is_today = serializers.BooleanField()
    show_min = serializers.IntegerField(required=False)
    width = serializers.FloatField()


class CheckoutAppointRequestSerializer(serializers.Serializer):
    """Serializer for checkout appointment request."""
    
    Rid = serializers.CharField(help_text="Room ID")
    weekday = serializers.ChoiceField(
        choices=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        help_text="Weekday for the appointment"
    )
    startid = serializers.IntegerField(
        min_value=0,
        help_text="Start time slot ID"
    )
    endid = serializers.IntegerField(
        min_value=0,
        help_text="End time slot ID"
    )
    longterm = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether this is a long-term appointment"
    )
    start_week = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=1,
        help_text="Start week (0 for this week, 1 for next week)"
    )
    times = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Number of weeks for long-term appointment"
    )
    interval = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Interval weeks for long-term appointment (1 for weekly, 2 for bi-weekly)"
    )
    interview = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether this is an interview appointment"
    )
    Ausage = serializers.CharField(
        max_length=256,
        help_text="Usage description for the appointment"
    )
    announcement = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=256,
        help_text="Announcement for the appointment"
    )
    non_yp_num = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of non-YP participants"
    )
    students = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of student IDs participating in the appointment"
    )
    
    def validate(self, data):
        """Validate the appointment request."""
        if data.get('endid', 0) < data.get('startid', 0):
            raise serializers.ValidationError({
                'endid': '结束时间必须晚于或等于开始时间'
            })
        
        if data.get('longterm'):
            times = data.get('times')
            interval = data.get('interval')
            if not times:
                raise serializers.ValidationError({
                    'times': '长期预约周数未填写'
                })
            if not (1 <= interval <= CONFIG.longterm_max_interval):
                raise serializers.ValidationError({
                    'interval': f'间隔周数不符合要求，必须在1-{CONFIG.longterm_max_interval}之间'
                })
            if not (1 <= times <= CONFIG.longterm_max_time_once
                    and 1 <= interval * times <= CONFIG.longterm_max_week):
                raise serializers.ValidationError({
                    'times': f'预约周数不符合要求，单次最多{CONFIG.longterm_max_time_once}周，总周数最多{CONFIG.longterm_max_week}周'
                })
        
        return data


class CheckoutAppointResponseSerializer(serializers.Serializer):
    """Serializer for checkout appointment response."""
    
    success = serializers.BooleanField()
    message = serializers.CharField()
    appoint_id = serializers.IntegerField(required=False, allow_null=True)
    longterm_id = serializers.IntegerField(required=False, allow_null=True)
    room_name = serializers.CharField(required=False, allow_null=True)


class AgreementResponseSerializer(serializers.Serializer):
    """Serializer for agreement endpoint response."""
    
    agree_time = serializers.DateField(required=False, allow_null=True)

