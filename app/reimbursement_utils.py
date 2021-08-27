from django.dispatch.dispatcher import receiver
from app.models import (
    Reimbursement,
    Activity,
    Comment,
    CommentPhoto
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
# 返回值为context, warn_code = 1表示失败, 2表示成功; 错误信息在context["warn_message"]
# 如果成功context会返回update之后的application,


def update_reimb_application(application, me, user_type, request,auditor_name):
    # 关于这个application与我的关系已经完成检查
    # 确定request.POST中有post_type且不是None

    # 首先上锁
    with transaction.atomic():
        if application is not None:
            application = Reimbursement.objects.select_for_update().get(id=application.id)

        # 首先确定申请状态
        post_type = request.POST.get("post_type")
        feasible_post = ["new_submit", "modify_submit",
                         "cancel_submit", "accept_submit", "refuse_submit"]
        if post_type not in feasible_post:
            return wrong("申请状态异常！")

        # 接下来确定访问的个人/组织是不是在做分内的事情
        if (user_type == "Person" and feasible_post.index(post_type)<=2 ) or (
                user_type == "Organization" and feasible_post.index(post_type) >= 3):
            return wrong("您无权进行此操作. 如有疑惑, 请联系管理员")

        if feasible_post.index(post_type) <= 2:  # 是组织的操作, 新建\修改\取消

            # 访问者一定是组织
            try:
                assert user_type == "Organization"
            except:
                return wrong("访问者身份异常！")

            # 如果是取消申请
            if post_type == "cancel_submit":
                if not application.is_pending():  # 如果不在pending状态, 可能是重复点击
                    return wrong("该申请已经完成或被取消!")
                # 接下来可以进行取消操作
                Reimbursement.objects.filter(id=application.id).update(status=Reimbursement.ReimburseStatus.CANCELED)
                context = succeed("成功取消“" +application.activity.title+ "”的经费申请!")
                context["application_id"] = application.id
                return context

            else:
                # 无论是新建还是修改, 都应该首先对元气值、报销说明进行合法性检查

                #元气值
                YQP = me.YQPoint
                try:
                    reimb_YQP = float(request.POST.get('YQP'))
                    if reimb_YQP < 0:
                        return wrong("申请失败，报销的元气值不能为负值！")
                    if reimb_YQP > YQP:
                        return wrong("申请失败，报销的元气值不能超过组织当前元气值！")
                except:
                    return wrong("元气值不能为空，请完整填写。")
                #报销说明
                message = str(request.POST.get('message'))  # 报销说明
                if message == "":
                    return wrong("报销说明不能为空，请完整填写。")

                # 如果是新建申请,
                if post_type == "new_submit":
                    # 未报销的活动
                    activities=utils.get_unreimb_activity(me)
                    try:
                        reimb_act_id = int(request.POST.get('activity_id'))
                        reimb_act = Activity.objects.get(id=reimb_act_id)
                        if reimb_act not in activities:  # 防止篡改POST导致伪造别人的报销活动
                            return wrong("找不到该活动，请检查报销的活动的合法性！")
                    except:
                        return wrong("找不到该活动，请检查报销的活动的合法性！")
                    #报销材料
                    images = request.FILES.getlist('images')
                    if len(images) > 0:
                        for image in images:
                            if utils.if_image(image) == False:
                                return wrong("上传的材料只支持图片格式。")
                    # 至此可以新建申请, 创建一个空申请
                    application =Reimbursement.objects.create(
                                activity=reimb_act, amount=reimb_YQP, pos=me.organization_id,message=message)
                    if len(images)>0:
                        text = "以下默认为初始的报销材料"
                        reim_comment = Comment.objects.create(
                            commentbase=application, commentator=me.organization_id,text = text)
                        #创建评论外键
                        for payload in images:
                            CommentPhoto.objects.create(
                                image=payload, comment=reim_comment)
                    context = succeed(f'活动{reimb_act.title}的经费申请已成功发送，请耐心等待{auditor_name}老师审批！' )
                    context["application_id"] = application.id
                    return context

                else:  # post_type == "modify_submit":
                    # 如果是修改申请的话, 状态应该是waiting
                    if not application.is_pending():
                        return wrong("不可以修改状态不为申请中的申请!")
                    # 修改申请的状态应该有所变化
                    if application.amount == reimb_YQP and  application.message == message:
                        return wrong("没有检测到修改!")
                    # 至此可以发起修改
                    Reimbursement.objects.filter(id=application.id).update(
                        amount=reimb_YQP,message=message)
                    context = succeed(f'活动{application.activity.title}的经费申请已成功修改，请耐心等待{auditor_name}老师审批！' )
                    context["application_id"] = application.id
                    return context

        else:  # 是老师的操作, 通过or拒绝
            # 访问者一定是个人
            try:
                assert user_type == "Person"
            except:
                return wrong("访问者身份异常！")
            if not application.is_pending():
                return wrong("无法操作, 该申请已经完成或被取消!")
            act_title=application.activity.title
            # 否则，应该直接完成状态修改
            if post_type == "refuse_submit":
                Reimbursement.objects.filter(id=application.id).update(status=Reimbursement.ReimburseStatus.REFUSED)
                context = succeed(f'已成功拒绝活动{act_title}的经费申请！')
                context["application_id"] = application.id
                return context
            else:  # 通过申请
                '''
                    注意，在这个申请发起、修改的时候，都应该保证这条申请的合法地位
                    例如不存在冲突申请、职位的申请是合理的等等
                    否则就不应该通过这条创建
                '''
                org = application.pos.organization
                if org.YQPoint < application.amount:
                    return wrong("当前组织没有足够的元气值。报销申请无法通过。")
                else:  # 修改对应组织的元气值
                    org.YQPoint -= application.amount
                    org.save()
                    application.status = Reimbursement.ReimburseStatus.CONFIRMED
                    application.save()
                context = succeed(f'活动{act_title}的经费申请已通过！')
                context["application_id"] = application.id
                return context
