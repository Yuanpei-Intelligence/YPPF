# -----------------------
# |      models.py      |
# -----------------------

class Reimbursement(models.Model):
    class Meta:
        verbose_name = "报销信息"
        verbose_name_plural = verbose_name
        ordering = ["-modify_time", "-time"]

    class ReimburseStatus(models.IntegerChoices):
        WAITING = (0, "待确认")
        CONFIRM1 = (1, "主管老师已确认")
        CONFIRM2 = (2, "财务老师已确认")
        CONFIRMED = (3, "已通过")
        # 如果需要更多审核，每个审核的确认状态应该是2的幂
        # 根据最新要求，最终不以线上为准，不再设置转账状态
        CANCELED = (4, "已取消")

    activity = models.ForeignKey(Activity,
                                related_name="reimbursement", 
                                on_delete=models.CASCADE)
    amount = models.FloatField("报销金额", default=0)
    # 如果之后全线上流程，可能需要报账人字段
    message = models.TextField("备注信息", default="", blank=True)
    # 图片存储在comment中，models不支持序列图片
    status = models.SmallIntegerField(choices=ReimburseStatus.choices, default=0)
    time = models.DateTimeField("发起时间", auto_now_add=True)
    modify_time = models.DateTimeField("上次修改时间", auto_now_add=True)
    


class ReimburseComment(models.Model):
    class Meta:
        verbose_name = "报销评论"
        verbose_name_plural = verbose_name
        ordering = ["-time"]

    def comment_path(instance, filename):
        reimburse = instance.reimbursement
        act = reimburse.activity
        dir = f"reimburse/{act.organization_id.oname}/"
        # 日期和时间都是不靠谱的，因为上传多个图片时不同图片的存储很可能是同1秒完成的
        # 同一报销信息可能在连续的几分钟内发很多个同文件名的
        # title是方便人识别的内容
        return dir + f"{act.title}-{instance.id}-{filename}"

    reimbursement = models.ForeignKey(Reimbursement,
                                    related_name="comments",
                                    on_delete=models.CASCADE)
    username = models.CharField("评论者", max_length=10)
    # 保留用户名的意义是方便页面统一呈现（评论者可能是组织或老师）
    # 也许可以允许自由设置名称
    text = models.TextField("文字内容", default="", blank=True)
    img = models.ImageField("图片", upload_to=comment_path, blank=True)
    time = models.DateTimeField("评论时间", auto_now_add=True)


# ---------------------------------------
# |      reimbursement_add.html      |
# ---------------------------------------

def html1():
    '''
    创建报销页面（鼠标移动至本函数查看文档）
    - 基于base.html和org_left_narbar.html

    页面要素
    -------
    - 报销活动：从已知选项中选择，类似地下室预约选择预约名单
    - 报销金额：浮点，由于元气值限制可以改成至多允许一位浮点
        * 新：最好设置上限为组织元气值
    - 发票和其他图片材料：不设上限的图片上传<input type="file" accept="image/*" multiple>
        有能力的话设成多次上传也行
    - 备注：文本框
    - 可能的错误信息提示
    - 提交按钮

    进阶要求
    -------
    支持根据render提供的数据重建表单（错误后自动填充）
        图片可以不急
    '''

# ---------------------------------------
# |     comment_reimbursement.html      |
# ---------------------------------------

def html2():
    '''
    修改/评论报销页面（鼠标移动至本函数查看文档）
    - 独立页面，GET:/?id=reimbursement.id(&pass=yes或者老师类型)(&cancel=yes)

    页面要素
    -------
    - 可能的错误信息/提示信息
    - 报销信息
        - 当前报销状态/进度
        - 报销活动
        - 报销金额
        - 备注
        - 申请时间
    - 评论（很多条）
        - 评论者
        - 评论内容（如果有文字，呈现文字，如果有图片也呈现图片）
        - 评论时间
    - 如果报销已经结束或取消，后续不呈现
    - 如果是组织者：
        - 修改报销金额
        - 修改按钮（应与评论按钮并列更好看）（需要二次确认）
        *新：- 取消按钮（可以在详情界面，也可以在某个能统一呈现的界面）（需要二次确认）
    - 评论
        - 评论内容
        - 评论图片
        - 评论按钮
    - 如果是老师且未通过：通过按钮（应与评论并列）

    进阶要求
    -------
    如果可评论，页面中一个按钮快速导航到评论区
    POST后支持根据render提供的数据重建表单（错误后自动填充）
        图片可以不急
    连续同名评论者可以只显示一个名字
    '''

# -----------------------
# |      views.py       |
# -----------------------

def create_reimbursement(request):
    '''
    创建报销

    流程
    -------
    1. 判断当前user是否是组织，不是返回到/welcome
    2. GET
        1. 通过`check_user_type`和`get_user_left_narbar`获取`html_display`
        2. `html_display["narbar_name"] = "活动报销"`等
        *有改动：
        3. 查询当前组织还未报销的活动和*新：元气值上限
            - 注意一个活动可能有已取消的报销信息，这时该活动也是未报销的
        4. 返回`render(request, reimbursement_add.html, locals())`
    3. POST
        1. 获取提交的报销信息（不含图片）
            - *新：查看元气值是否足够
            - 有问题时最好重新根据报销信息组织页面，然后返回render
            - 无误时创建Reimbursement对象，*新：扣除元气值
            - 发送信箱消息，有需要时发送企业微信消息
        2. 获取提交的图片信息
            1. 获取图片列表，如`imgs = request.FILES.getlist(表单图片名)`
            2. 根据组织名称，为每个图片创建一个comment
    '''

def comment_reimbursement(request):
    '''
    报销评论
    网址有一定get参数：报销id，通过与否，取消与否

    流程
    -------
    0. 查询报销是否存在（不论状态）
    1. 判断当前user是否是该活动的组织或负责审批的老师，不是返回到/welcome
        - 也可以老师都能查看，但只有对应老师能评论和操作
    2. GET
        1. 获取报销信息和状态
        2. 获取所有本报销关联的评论:`reim.comments`
        3. 返回`render(request, comment_reimbursement.html, locals())`
    3. POST
        1. 查看是否通过
            - 如果是对应老师，更新状态，结束，提示成功并返回之前界面
                *新：现在扣除元气值是创建和修改时的操作，这里不修改
            - 如果不是，报错返回到之前页面
        *新：2. 查看是否取消
            - 如果不是对应组织，报错返回到之前页面
            - 没问题，则修改报销状态并同时恢复元气值
        3. 获取评论信息
            1. 如果是对应组织且修改了金额
                *新：0. 确定报销金额是否合法（新金额<=元气值+旧金额）
                *有改动：
                1. 更新数据库报销金额并同时根据当前金额和此前的差值决定扣除/回复元气值
                2. 根据组织名创建评论，提示金额已更改
                3. 提示成功并返回当前页面
            2. 否则获取表单信息
                1. 根据组织或教师名称，创建一个comment
                2. 提示成功并返回当前页面
    '''