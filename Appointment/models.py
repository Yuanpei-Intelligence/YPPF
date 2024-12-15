from datetime import timedelta
from typing import cast

from django.db import models
from django.db.models.signals import pre_delete
from django.db.models import QuerySet, Q
from django.dispatch import receiver
from django.db import transaction

from utils.models.descriptor import admin_only
from utils.models.choice import choice, CustomizedDisplay, DefaultDisplay
from utils.models.manager import ManyRelatedManager
from utils.models.permission import PermissionModelBase, BasePermission
from generic.models import User
from Appointment.config import appointment_config as CONFIG

__all__ = [
    'User',
    'College_Announcement',
    'Participant',
    'RoomClass',
    'Room',
    'Appoint',
    'LongTermAppoint',
    'CardCheckInfo',
]



class College_Announcement(models.Model):
    class Meta:
        verbose_name = "全院公告"
        verbose_name_plural = verbose_name

    class Show_Status(models.IntegerChoices):
        Yes = 1
        No = 0

    show = models.SmallIntegerField('是否显示',
                                    choices=Show_Status.choices,
                                    default=0)
    announcement = models.CharField('通知内容', max_length=256, blank=True)


class Participant(models.Model):
    class Meta:
        verbose_name = '学生'
        verbose_name_plural = verbose_name
        ordering = ['Sid']

    Sid = models.OneToOneField(
        User,
        related_name='+',
        on_delete=models.CASCADE,
        to_field='username',
        verbose_name='学号',
        primary_key=True,
    )

    @property
    def name(self) -> str:
        return self.Sid.name

    @property
    def credit(self) -> int:
        '''通过此方法访问的信用分是只读的，修改应使用User.objects方法'''
        return self.Sid.credit

    hidden = models.BooleanField('不可搜索', default=False)
    longterm = models.BooleanField('可长期预约', default=False)

    # TODO: pht 2022-02-20 通过新的模型实现，允许每个房间有自己的规则
    # 用户许可的字段，需要许可的房间刷卡时检查是否通过了许可
    agree_time = models.DateField('上次许可时间', null=True, blank=True)

    appoint_list: 'AppointManager'

    @property
    def appoints_manager(self) -> 'ManyRelatedManager[Appoint]':
        '''获取所有预约，允许进行批量管理'''
        return cast('ManyRelatedManager[Appoint]', self.appoint_list)

    def get_id(self) -> str:
        '''获取id(学号/组织账号)'''
        return self.Sid_id

    @admin_only
    def __str__(self):
        '''仅用于后台呈现和搜索方便，任何时候不应使用'''
        acronym = self.Sid.acronym
        if acronym is None:
            return self.name
        return self.name + '_' + acronym


class RoomQuerySet(models.QuerySet['Room']):
    def permitted(self):
        '''只保留所有可预约的房间'''
        return self.filter(Rstatus=Room.Status.PERMITTED)

    def unlimited(self):
        '''只保留所有无需预约的房间'''
        return self.filter(Rstatus=Room.Status.UNLIMITED)

    def activated(self):
        '''只保留所有可用的房间'''
        return self.filter(Rstatus__in=[Room.Status.UNLIMITED, Room.Status.PERMITTED])

class RoomManager(models.Manager['Room']):
    def get_queryset(self) -> RoomQuerySet:
        return RoomQuerySet(self.model, using=self._db, hints=self._hints)

    def all(self) -> RoomQuerySet:
        return super().all()  # type: ignore

    def permitted(self):
        return self.get_queryset().permitted()

    def unlimited(self):
        return self.get_queryset().unlimited()

    def interview_room_ids(self):
        return set()


class RoomClass(models.Model):
    class Meta:
        verbose_name = '房间类别'
        verbose_name_plural = verbose_name

    sort_idx = models.SmallIntegerField('主页排序')
    name = models.CharField('类别名称', max_length=32, unique=True)
    description = models.CharField(
        '类别描述', max_length=256, blank=True, default='')
    reservable = models.BooleanField('可预约', default=True)
    quick_reservable = models.BooleanField('临时预约', default=False)
    rooms = models.ManyToManyField(
        'Room', verbose_name='房间列表', db_index=True, related_name='classes')

    # Used for room's many-to-many field
    def __str__(self):
        return self.name

class Room(models.Model):
    class Meta:
        verbose_name = '房间'
        verbose_name_plural = verbose_name
        ordering = ['Rid']

    # 房间编号我不确定是否需要。如果地下室有门牌的话（例如B101）保留房间编号比较好
    # 如果删除Rid记得把Rtitle设置成主键
    Rid = models.CharField('房间编号', max_length=8, primary_key=True)
    Rtitle = models.CharField('房间名称', max_length=32)
    Rmin = models.IntegerField('房间预约人数下限', default=0)
    Rmax = models.IntegerField('房间使用人数上限', default=20)
    Rstart = models.TimeField('最早预约时间')
    Rfinish = models.TimeField('最迟预约时间')
    Rlatest_time = models.DateTimeField("摄像头心跳", auto_now_add=True)
    Rpresent = models.IntegerField('目前人数', default=0)
    image = models.ImageField('房间图片', upload_to='room_images', null=True)

    # Rstatus 标记当前房间是否允许预约，可由管理员修改
    class Status(models.IntegerChoices):
        PERMITTED = 0, '允许预约'  # 允许预约
        UNLIMITED = 1, '无需预约'  # 允许使用
        FORBIDDEN = 2, '禁止使用'  # 禁止使用

    Rstatus = models.SmallIntegerField('房间状态', choices=Status.choices, default=0)

    # 标记当前房间是否可以通宵使用，可由管理员修改（主要针对自习室）
    RIsAllNight = models.BooleanField('可通宵使用', default=False)
    # 是否需要许可，目前通过要求阅读固定须知实现，未来可拓展为许可模型（关联房间和个人）
    RneedAgree = models.BooleanField('需要许可', default=False)

    appoint_list: 'AppointManager'

    @property
    def appoints_manager(self) -> 'ManyRelatedManager[Appoint]':
        '''获取所有预约，允许进行批量管理'''
        return cast('ManyRelatedManager[Appoint]', self.appoint_list)

    objects: RoomManager = RoomManager()

    @property
    def reservable(self) -> bool:
        '''是否可预约'''
        return self.Rstatus == Room.Status.PERMITTED

    @property
    def quick_reservable(self) -> bool:
        '''是否支持快速预约'''
        return self.classes.filter(quick_reservable=True).exists() and self.reservable

    def __str__(self):
        return self.Rid + ' ' + self.Rtitle


class AppointQuerySet(models.QuerySet['Appoint']):
    def not_canceled(self):
        return self.exclude(Astatus=Appoint.Status.CANCELED)

    def terminated(self):
        return self.filter(Astatus__in=Appoint.Status.Terminals())

    def unfinished(self):
        return self.exclude(Astatus__in=Appoint.Status.Terminals())


class AppointManager(models.Manager['Appoint']):
    def get_queryset(self) -> AppointQuerySet:
        return AppointQuerySet(self.model, using=self._db, hints=self._hints)

    def all(self) -> AppointQuerySet:
        return super().all()  # type: ignore

    def not_canceled(self):
        return self.get_queryset().not_canceled()

    def unfinished(self):
        '''用于检查而非呈现，筛选还未结束的预约'''
        return self.exclude(Astatus__in=Appoint.Status.Terminals())

    def displayable(self):
        '''个人主页页面，在"普通预约"和"查看下周"中会显示的预约'''
        return self.exclude(Atype=Appoint.Type.LONGTERM, Astatus=Appoint.Status.CANCELED)


class Appoint(models.Model, metaclass=PermissionModelBase):
    class Permission(BasePermission):
        CREATE = choice('create_appointment', '创建预约')
        CANCEL = choice('cancel_appointment', '取消预约')

    class Meta:
        verbose_name = '预约信息'
        verbose_name_plural = verbose_name
        ordering = ['Aid']

    Aid = models.AutoField('预约编号', primary_key=True)
    # 申请时间为插入数据库的时间
    Atime = models.DateTimeField('申请时间', auto_now_add=True)
    Astart = models.DateTimeField('开始时间')
    Afinish = models.DateTimeField('结束时间')
    Ausage = models.CharField('用途', max_length=256, null=True)
    Aannouncement = models.CharField(
        '预约通知', max_length=256, null=True, blank=True)
    Anon_yp_num = models.IntegerField("外院人数", default=0)
    Ayp_num = models.IntegerField('院内人数', default=0)

    # CheckStatus: 分钟内检测状态
    class CheckStatus(models.IntegerChoices):
        FAILED = 0  # 预约在此分钟的检查尚未通过
        PASSED = 1  # 预约在特定分钟内的检查是通过的
        UNSAVED = 2  # 预约在此分钟内尚未记录检测状态
    Acheck_status = models.SmallIntegerField('检测状态',
        choices=CheckStatus.choices, default=2)

    # 这里Room使用外键的话只能设置DO_NOTHING，否则删除房间就会丢失预约信息
    # 所以房间信息不能删除，只能逻辑删除
    # 调用时使用appoint_obj.Room和room_obj.appoint_list
    Room: 'models.ForeignKey[Room]' = models.ForeignKey(
        Room, verbose_name='房间号',
        related_name='appoint_list',
        null=True, on_delete=models.SET_NULL)  # type: ignore
    # 通过类型提示限制操作类型，非只读操作应访问students_manager
    students: 'models.Manager[Participant]' = models.ManyToManyField(
        Participant, related_name='appoint_list', db_index=True)  # type: ignore

    @property
    def students_manager(self) -> 'ManyRelatedManager[Participant]':
        '''获取所有参与者，允许进行批量管理'''
        return cast('ManyRelatedManager[Participant]', self.students)

    major_student: 'models.ForeignKey[Participant]' = models.ForeignKey(
        Participant, verbose_name='Appointer',
        null=True, on_delete=models.CASCADE)  # type: ignore

    class Status(models.IntegerChoices):
        CANCELED = choice(0, '已取消')
        APPOINTED = choice(1, '已预约')
        PROCESSING = choice(2, '进行中')
        WAITING = choice(3, '等待确认')
        CONFIRMED = choice(4, '已确认')
        VIOLATED = choice(5, '违约')
        JUDGED = choice(6, '申诉成功')

        @classmethod
        def Terminals(cls) -> 'list[Appoint.Status]':
            return [cls.CANCELED, cls.CONFIRMED, cls.VIOLATED, cls.JUDGED]

    Astatus = models.IntegerField('预约状态', choices=Status.choices, default=1)
    get_Astatus_display: CustomizedDisplay

    Aneed_num = models.IntegerField('检查人数要求')
    Acamera_check_num = models.IntegerField('检查次数', default=0)
    Acamera_ok_num = models.IntegerField('人数合格次数', default=0)

    class Reason(models.IntegerChoices):
        R_NOVIOLATED = choice(0, '没有违约')
        R_LATE = choice(1, '迟到')
        R_TOOLITTLE = choice(2, '人数不足')
        R_ELSE = choice(3, '其它原因')

    Areason = models.IntegerField('违约原因', choices=Reason.choices, default=0)
    get_Areason_display: DefaultDisplay

    class Type(models.IntegerChoices):
        '''预约类型'''
        NORMAL = choice(0, '常规预约')
        TODAY = choice(1, '当天预约')
        TEMPORARY = choice(2, '临时预约')
        LONGTERM = choice(3, '长期预约')
        INTERVIEW = choice(4, '面试预约')

    Atype = models.SmallIntegerField('预约类型',
        choices=Type.choices, default=Type.NORMAL)
    get_Atype_display: CustomizedDisplay

    objects: AppointManager = AppointManager()

    def add_time(self, delta: timedelta):
        '''方便同时调整预约时间的函数，修改自身，不调用save保存'''
        self.Astart += delta
        self.Afinish += delta
        return self

    def get_major_id(self) -> str:
        '''获取预约发起者id'''
        return self.major_student.Sid_id

    def get_admin_url(self) -> str:
        '''获取后台搜索的url'''
        return f'/admin/Appointment/appoint/?q={self.pk}'

    def get_status(self):
        if self.Astatus == Appoint.Status.VIOLATED:
            match cast(Appoint.Reason, self.Areason):
                case Appoint.Reason.R_NOVIOLATED:
                    status = "未知错误，请联系管理员"
                case Appoint.Reason.R_LATE:
                    status = "使用迟到"
                case Appoint.Reason.R_TOOLITTLE:
                    status = "人数不足"
                case Appoint.Reason.R_ELSE:
                    status = "管理员操作"
        else:
            status = self.get_Astatus_display()
        return status

    def toJson(self):
        data = {
            'Aid': self.Aid,  # 预约编号
            'Atime': self.Atime.strftime("%Y-%m-%dT%H:%M:%S"),      # 申请提交时间
            'Astart': self.Astart.strftime("%Y-%m-%dT%H:%M:%S"),    # 开始使用时间
            'Afinish': self.Afinish.strftime("%Y-%m-%dT%H:%M:%S"),  # 结束使用时间
            'Ausage': self.Ausage,  # 房间用途
            'Aannouncement': self.Aannouncement,  # 预约通知
            'Atype': self.get_Atype_display(),      # 预约类型
            'Astatus': self.get_Astatus_display(),  # 预约状态
            'Areason': self.Areason,
            'Rid': self.Room.Rid,  # 房间编号
            'Rtitle': self.Room.Rtitle,  # 房间名称
            'yp_num': self.Ayp_num,  # 院内人数
            'non_yp_num': self.Anon_yp_num,  # 外院人数
            'major_student': {
                "Sname": self.major_student.name,  # 发起预约人
                "Sid": self.get_major_id(),
            },
            'students': [{
                'Sname': student.name,  # 参与人姓名
                'Sid': student.get_id(),
            } for student in self.students.all().select_related('Sid')],
        }
        return data


class CardCheckInfo(models.Model):
    # 这里Room使用外键的话只能设置DO_NOTHING，否则删除房间就会丢失预约信息
    # 所以房间信息不能删除，只能逻辑删除
    # 调用时使用appoint_obj.Room和room_obj.appoint_list
    Cardroom: Room = models.ForeignKey(Room,
                                       related_name='+',
                                       null=True,
                                       blank=True,
                                       on_delete=models.SET_NULL,
                                       verbose_name='房间号')
    Cardstudent: Participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, verbose_name='刷卡者',
        null=True, blank=True, db_index=True)
    Cardtime = models.DateTimeField('刷卡时间', auto_now_add=True)

    class Status(models.IntegerChoices):
        DOOR_CLOSE = 0, '不开门'  # 开门：否
        DOOR_OPEN = 1, '开门'  # 开门：是

    CardStatus = models.SmallIntegerField(
        '刷卡状态', choices=Status.choices, default=0)

    Message = models.CharField(
        '记录信息', max_length=256, null=True, blank=True)

    class Meta:
        verbose_name = "刷卡记录"
        verbose_name_plural = verbose_name


class LongTermAppointManager(models.Manager['LongTermAppoint']):
    def activated(self, this_semester=True) -> 'QuerySet[LongTermAppoint]':
        result = self.filter(
            status__in=[
                LongTermAppoint.Status.APPROVED,
                LongTermAppoint.Status.REVIEWING,
            ])
        if this_semester:
            result = result.filter(
                appoint__Astart__gt=CONFIG.semester_start,
            )
        return result


class LongTermAppoint(models.Model):
    """
    记录长期预约所需要的全部信息
    """
    class Meta:
        verbose_name = '长期预约信息'
        verbose_name_plural = verbose_name

    appoint: Appoint = models.OneToOneField(Appoint,
                                            on_delete=models.CASCADE,
                                            verbose_name='单次预约信息')

    applicant: Participant = models.ForeignKey(Participant,
                                               on_delete=models.CASCADE,
                                               verbose_name='申请者')

    times = models.SmallIntegerField('预约次数', default=1)
    interval = models.SmallIntegerField('间隔周数', default=1)
    review_comment = models.TextField('评论意见', default='', blank=True)

    class Status(models.IntegerChoices):
        REVIEWING = (0, '审核中')
        CANCELED = (1, '已取消')
        APPROVED = (2, '已通过')
        REJECTED = (3, '未通过')

    status: 'int|Status' = models.SmallIntegerField('申请状态',
                                                    choices=Status.choices,
                                                    default=Status.REVIEWING)

    objects: LongTermAppointManager = LongTermAppointManager()

    def create(self):
        '''原子化创建长期预约的全部后续子预约'''
        from Appointment.jobs import add_longterm_appoint
        conflict_week, appoints = add_longterm_appoint(
            appoint=self.appoint.pk,
            times=self.times - 1,
            interval=self.interval,
        )
        return conflict_week, appoints

    def cancel(self, all=False, delete=False):
        '''
        原子化取消长期预约以及它的子预约，不应出错

        :param all: 取消全部，否则只取消未开始的预约, defaults to False
        :type all: bool, optional
        :param delete: 以数据库删除代替取消，长期预约也会级联删除, defaults to False
        :type delete: bool, optional
        :return: 取消的子预约数量
        :rtype: int
        '''
        from Appointment.appoint.manage import cancel_appoint
        with transaction.atomic():
            # 取消子预约
            appoints = self.sub_appoints(lock=True)
            if not all:
                appoints = appoints.filter(Astatus=Appoint.Status.APPOINTED)
            if delete:
                return appoints.delete()[0]
            count = len(appoints)
            for appoint in appoints:
                cancel_appoint(appoint, record=True, lock=False)
            self.status = LongTermAppoint.Status.CANCELED
            self.save()
            return count

    def renew(self, times: int):
        '''原子化添加新的后续子预约，不应出错'''
        from Appointment.jobs import add_longterm_appoint
        times = max(0, times)
        with transaction.atomic():
            conflict_week, appoints = add_longterm_appoint(
                appoint=self.appoint.pk,
                times=times,
                interval=self.interval,
                week_offset=self.times * self.interval,
            )
            if conflict_week is not None:
                self.times += times
                self.save()
            return conflict_week, appoints

    def sub_appoints(self, lock=False) -> QuerySet[Appoint]:
        '''
        获取时间升序的子预约，只有类型为长期预约的被视为子预约，不应出错

        :param lock: 上锁，调用者需要自行开启事务, defaults to False
        :type lock: bool, optional
        :return: 时间升序的子预约
        :rtype: QuerySet[Appoint]
        '''
        from Appointment.utils.utils import get_conflict_appoints
        conflict_appoints = get_conflict_appoints(
            self.appoint, times=self.times, interval=self.interval, lock=lock)
        sub_appoints = conflict_appoints.filter(
            major_student=self.appoint.major_student, Atype=Appoint.Type.LONGTERM)
        return sub_appoints.order_by('Astart', 'Afinish')

    def get_applicant_id(self) -> str:
        '''获取申请者id'''
        return self.applicant.get_id()


@receiver(pre_delete, sender=Appoint)
def before_delete_Appoint(sender, instance, **kwargs):
    from Appointment.appoint.jobs import cancel_scheduler
    cancel_scheduler(instance.Aid)
