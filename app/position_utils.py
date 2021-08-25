from app.models import (
    NaturalPerson,
    Organization,
    OrganizationType,
    Position,
    ModifyPosition,
    Notification,
)
import app.utils as utils
from django.db import transaction


# 在错误的情况下返回的字典,message为错误信息
def wrong(message="检测到恶意的申请操作. 如有疑惑，请联系管理员!"):
    context = dict()
    context["warn_code"] = 1
    context["warn_message"] = message
    return context


def succeed(message):
    context = dict()
    context["warn_code"] = 2
    context["warn_message"] = message
    return context

# 修改人事申请状态的操作函数, application为修改的对象，可以为None
# me为操作者
# info为前端POST字典
# 返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
# 如果成功context会返回update之后的application,


def update_pos_application(application, me, user_type, applied_org, info):
    # 关于这个application与我的关系已经完成检查
    # 确定info中有post_type且不是None

    # 首先上锁
    with transaction.atomic():
        if application is not None:
            application = ModifyPosition.objects.select_for_update().get(id=application.id)

        # 首先确定申请状态
        post_type = info.get("post_type")
        feasible_post = ["new_submit", "modify_submit",
                         "cancel_submit", "accept_submit", "refuse_submit"]
        if post_type not in feasible_post:
            return wrong("申请状态异常！")

        # 接下来确定访问的个人/组织是不是在做分内的事情
        if (user_type == "Person" and feasible_post.index(post_type) >= 3) or (
                user_type == "Organization" and feasible_post.index(post_type) <= 2):
            return wrong("您无权进行此操作. 如有疑惑, 请联系管理员")

        if feasible_post.index(post_type) <= 2:  # 是个人的操作, 新建\修改\删除

            # 访问者一定是个人
            try:
                assert user_type == "Person"
            except:
                return wrong("访问者身份异常！")

            # 如果是取消申请
            if post_type == "cancel_submit":
                if not application.is_pending():    # 如果不在pending状态, 可能是重复点击
                    return wrong("该申请已经完成或被取消!")
                # 接下来可以进行取消操作
                ModifyPosition.objects.filter(id=application.id).update(status=ModifyPosition.Status.CANCELED)
                context = succeed("成功取消向" + applied_org.oname + "的申请!")
                context["application_id"] = application.id
                return context

            else:
                # 无论是新建还是修改, 都应该根据申请类别、申请职务和申请理由进行审核

                # 申请理由
                apply_reason = info.get("apply_reason")
                if apply_reason is None or apply_reason == "":
                    return wrong("申请失败, 申请理由或陈述不能为空!")

                # 申请类别和职务
                # 讨论申请的类别，抓取错误
                apply_type = info.get("apply_type")
                if apply_type == "加入组织":
                    # 此时应该满足的条件是不存在对应的在职职位
                    if Position.objects.activated().filter(person=me, org=applied_org).exists():
                        return wrong("加入已存在的组织！")
                    
                    apply_pos_name = str(info.get('apply_pos'))
                    apply_pos = applied_org.otype.get_pos_from_str(apply_pos_name)
                    print(apply_pos_name,apply_pos)
                elif apply_type == "退出组织":
                    if not Position.objects.activated().filter(person=me, org=applied_org).exists():
                        return wrong()
                    # 退出组织不应该有apply_pos
                elif apply_type == "修改职位":
                    try:
                        cur_position = Position.objects.activated().get(person=me, org=applied_org)
                        apply_pos_name = str(info.get('apply_pos'))
                        apply_pos = cur_position.otype.get_pos_from_str(
                            apply_pos_name)
                        assert apply_pos != cur_position.pos
                    except:
                        return wrong()
                else:  # 非法操作
                    return wrong()

                # 如果是新建申请, 则应该意味着me+applied_org的pending申请目前不存在
                if post_type == "new_submit":
                    if ModifyPosition.objects.filter(
                        person=me, org=applied_org, status=ModifyPosition.Status.PENDING
                    ).exists():
                        return wrong()
                    # 至此可以新建申请, 创建一个空申请
                    application = ModifyPosition.objects.create(
                        typename="ModifyPosition", pos=apply_pos, person=me, org=applied_org, apply_type=apply_type, reason=apply_reason)
                    context = succeed("成功发起向" + applied_org.oname + "的申请!")
                    context["application_id"] = application.id
                    return context

                else:  # post_type == "modify_submit":
                    # 如果是修改申请的话, 状态应该是pending
                    if not application.is_pending():
                        return wrong("不可以修改状态不为申请中的申请!")
                    # 修改申请的状态应该有所变化
                    if application.reason == apply_reason and \
                            application.apply_type == apply_type and \
                            application.pos == apply_pos:
                        return wrong("没有检测到修改!")
                    # 至此可以发起修改
                    ModifyPosition.objects.filter(id=application.id).update(
                        pos=apply_pos, reason=apply_reason, apply_type=apply_type)
                    context = succeed("成功修改向" + applied_org.oname + "的申请!")
                    context["application_id"] = application.id
                    return context

        else: # 是组织的操作, 通过\拒绝
            # 已经确定 me == application.org 了
            # 只需要确定状态是否匹配
            if not application.is_pending():
                return wrong("无法操作, 该申请已经完成或被取消!")
            # 否则，应该直接完成状态修改
            if post_type == "refuse_submit":
                ModifyPosition.objects.filter(id=application.id).update(status=ModifyPosition.Status.REFUSED)
                context = succeed("成功拒绝来自" + application.person.name + "的申请!")
                context["application_id"] = application.id
                return context
            else:   # 通过申请
                '''
                    注意，在这个申请发起、修改的时候，都应该保证这条申请的合法地位
                    例如不存在冲突申请、职位的申请是合理的等等
                    否则就不应该通过这条创建
                '''
                try:
                    application.accept_submit()
                    context = succeed("成功通过来自" + application.person.name + "的申请!")
                    context["application_id"] = application.id
                    return context
                except:
                    return wrong("出现系统意料之外的行为，请联系管理员处理!")
                

# 对一个已经完成的申请, 构建相关的通知和对应的微信消息, 将有关的事务设为已完成
# 如果有错误，则不应该是用户的问题，需要发送到管理员处解决
def make_relevant_notification(application):

    pass
