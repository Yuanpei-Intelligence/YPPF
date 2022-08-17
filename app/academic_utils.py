from app.utils_dependency import *
from app.models import (
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,
    User,
    Chat,
)
from app.utils import get_person_or_org, check_user_type
from app.comment_utils import addComment, showComment

from django.http import HttpRequest
from typing import List, Tuple, Dict
from collections import defaultdict

__all__ = [
    'get_search_results',
    'change_chat_status', 'chats2Display', 'comments2Display'
    'add_chat_message', 'create_chat',
]


def get_search_results(query: str) -> List[dict]:
    """
    根据提供的关键词获取搜索结果。

    :param keyword: 关键词
    :type keyword: str
    :return: 搜索结果list，元素为dict，包含key：姓名、年级、条目内容中包含关键词的条目名。
             一个条目名可能对应一个或多个内容（如参与多个科研项目等），因此条目名对应的value统一用list打包。
    :rtype: List[dict]
    """
    # 首先搜索所有含有关键词的公开的学术地图项目，忽略大小写，同时转换成QuerySet[dict]
    academic_tags = AcademicTagEntry.objects.filter( 
        tag__tag_content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values(
        "person__person_id_id", "person__name",   # person_id_id用于避免重名
        "person__stu_grade", "tag__atype", "tag__tag_content",
    )
    academic_texts = AcademicTextEntry.objects.filter(
        content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values(
        "person__person_id_id", "person__name",   # person_id_id用于避免重名
        "person__stu_grade", "atype", "content",
    )
    
    # 将choice的值更新为对应的选项名
    for tag in academic_tags:
        tag.update({"tag__atype": AcademicTag.AcademicTagType(tag["tag__atype"]).label})
    for text in academic_texts:
        text.update({"atype": AcademicTextEntry.AcademicTextType(text["atype"]).label})
        
    # 然后根据tag/text对应的人，整合学术地图项目
    academic_map_dict = {}  # 整理一个以person_id_id为key，以含有姓名、年级和学术地图项目的dict为value的dict
    for tag in academic_tags:
        person_id = tag["person__person_id_id"]
        tag_type = tag["tag__atype"]
        tag_content = tag["tag__tag_content"]
        if not person_id in academic_map_dict:
            academic_map_dict[person_id] = defaultdict(list)
            academic_map_dict[person_id]["姓名"] = tag["person__name"]
            academic_map_dict[person_id]["年级"] = tag["person__stu_grade"]
        academic_map_dict[person_id][tag_type].append(tag_content)
    
    for text in academic_texts:
        person_id = text["person__person_id_id"]
        text_type = text["atype"]
        text_content = text["content"]
        if not person_id in academic_map_dict:
            academic_map_dict[person_id] = defaultdict(list)
            academic_map_dict[person_id]["姓名"] = text["person__name"]
            academic_map_dict[person_id]["年级"] = text["person__stu_grade"]
        academic_map_dict[person_id][text_type].append(text_content)
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = [value for value in academic_map_dict.values()]
    return academic_map_list


def change_chat_status(chat_id: int, to_status: Chat.Status, allow_modify_forbidden: bool=False) -> MESSAGECONTEXT:
    """
    修改chat的状态

    :param chat_id
    :type chat_id: int
    :param to_status: 目标状态
    :type to_status: Chat.Status
    :param allow_modify_forbidden: 若为True，则允许修改原始状态为FORBIDDEN的chat，一般情况下都不允许，但在用户改变“是否允许匿名提问”时应该要允许, defaults to False
    :type allow_modify_forbidden: bool, optional
    :return: 表明成功与否的MESSAGECONTEXT
    :rtype: MESSAGECONTEXT
    """
    # 参考了notification_utils.py的notification_status_change
    context = wrong("在修改问答状态的过程中发生错误，请联系管理员！")
    with transaction.atomic():
        try:
            chat: Chat = Chat.objects.select_for_update().get(id=chat_id)
        except:
            return wrong("该问答不存在！", context)
        
        if chat.status == to_status:
            return succeed("问答状态无需改变！", context)
        if chat.status == Chat.Status.FORBIDDEN and allow_modify_forbidden == False:
            return wrong("当前问答禁用中！接收方不允许匿名提问!", context)
        
        if to_status == Chat.Status.CLOSED:
            chat.status = Chat.Status.CLOSED
            chat.save()
            succeed("您已成功关闭一个问答！", context)
        elif to_status == Chat.Status.PROGRESSING: # 这个目前没有用到
            chat.status = Chat.Status.PROGRESSING
            chat.save()
            succeed("您已成功开放一个问答！", context)
        else: # 改为FORBIDDEN还没实现
            raise NotImplementedError
        return context


def chats2Display(chats: QuerySet[Chat], sent: bool) -> Dict[str, List[dict]]:
    """
    把我收到/我发出的所有chat转化为供前端展示的两个列表，分别是进行中chat的信息、和其他chat的信息

    :param chats: 我收到/我发出的所有chat
    :type chats: QuerySet[Chat]
    :param sent: 若为True则表示我发出的，否则表示我收到的
    :type sent: bool
    :return: 一个词典，key为progressing和not_progressing，value分别是进行中chat的列表、和其他chat的列表
    :rtype: Dict[str, List[dict]]
    """
    not_progressing_chats = []
    progressing_chats = []

    for chat in chats:
        chat_dict = {}
        chat_dict['id'] = chat.id

        if sent:
            chat_dict['anonymously_sent'] = chat.anonymous_flag # 我以匿名方式发给别人，“问答中心”页面的卡片上会显示[匿名]
            valid, receiver_type, _ = check_user_type(chat.respondent) # 学术地图应该只能是个人，不过以后或许可能复用Chat模型？
            chat_dict['receiver_type'] = receiver_type
            receiver = get_person_or_org(chat.respondent, receiver_type)
            chat_dict['receiver_name'] = receiver.get_display_name()
            chat_dict['academic_url'] = receiver.get_absolute_url() # 为了在“问答中心”页面的卡片上加入学术地图的url，超链接放在receiver_name上
        else:
            if chat.anonymous_flag: # 他人匿名发给我
                chat_dict['sender_type'] = 'anonymous'
                chat_dict['sender_name'] = '匿名用户'
                chat_dict['academic_url'] = ''
            else:
                valid, sender_type, _ = check_user_type(chat.questioner) # 学术地图应该只能是个人，不过以后或许可能复用Chat模型？
                chat_dict['sender_type'] = sender_type
                sender = get_person_or_org(chat.questioner, sender_type)
                chat_dict['sender_name'] = sender.get_display_name()
                chat_dict['academic_url'] = sender.get_absolute_url() # 为了在“问答中心”页面的卡片上加入学术地图的url，超链接放在sender_name上（若sender匿名发送则无超链接）
        
        if len(chat.title) >= 12:
            chat_dict['title'] = chat.title[:12] + "……"
        elif len(chat.title) == 0:
            chat_dict['title'] = "无主题"
        else:
            chat_dict['title'] = chat.title
        
        chat_dict['status'] = chat.get_status_display()
        chat_dict['start_time'] = chat.time
        chat_dict['last_modification_time'] = chat.modify_time
        chat_dict['chat_url'] = f"/viewQA/{chat.id}" # 问答详情的url，超链接放在title上
        chat_dict['message_count'] = chat.comments.count()
        # chat_dict["messages"] = showComment(
        #     chat, anonymous_users=[chat.questioner] if chat.anonymous_flag else None) # "问答中心"页面不再显示每个chat的comment
        
        if chat.status == Chat.Status.PROGRESSING:
            progressing_chats.append(chat_dict)
        else:
            not_progressing_chats.append(chat_dict)
        
    return {"progressing": progressing_chats, "not_progressing": not_progressing_chats}


def comments2Display(chat: Chat, frontend_dict: dict, user: User):
    """
    获取一个chat中的所有comment并转化为前端展示所需的形式（复用了comment_utils.py/showComment）

    :param chat: 
    :type chat: Chat
    :param frontend_dict: 前端词典
    :type frontend_dict: dict
    :param user: 当前用户
    :type user: User
    """
    if len(chat.title) == 0:
        frontend_dict['title'] = "无主题"
    else:
        frontend_dict['title'] = chat.title
    
    # 获取当前chat的所有comment
    frontend_dict["messages"] = showComment(
        chat, anonymous_users=[chat.questioner] if chat.anonymous_flag else None)
    if len(frontend_dict["messages"]) == 0:
        # 基本不可能出现，除非提问者匿名向不允许匿名提问的人发起了chat
        frontend_dict["not_found_messages"] = "当前问答没有信息." 
    
    frontend_dict['status'] = chat.get_status_display()
    frontend_dict["commentable"] = (chat.status == Chat.Status.PROGRESSING) # 若为True，则前端会给出评论区和“关闭当前问答”的按钮
    
    # 问答详情页面需要展示“发给xxx的问答”或“来自xxx的问答”，且xxx附有指向学术地图页面的超链接
    # 因而需要判断我是提问者还是回答者，并记录对方的名字
    # 问答详情页面对于我的信息和对方的信息以不同的格式显示
    # 因而还需要记录我的名字，通过和frontend_dict["messages"]中每条记录的commentator.name对比来判断是不是我发的
    # 事实上这些操作如果放到showComment里能减少一些get_display_name、get_person_or_org、get_absolute_url的调用，但需要对showComment做较大修改，就暂时没有整合进去
    if chat.anonymous_flag == False:
        me = get_person_or_org(user)
        frontend_dict['my_name'] = me.get_display_name()
        if user == chat.questioner:
            frontend_dict["questioner_name"] = frontend_dict['my_name']
            you = get_person_or_org(chat.respondent)
            frontend_dict["respondent_name"] = you.get_display_name()
            frontend_dict["academic_url"] = you.get_absolute_url()
        else:
            you = get_person_or_org(chat.questioner)
            frontend_dict["questioner_name"] = you.get_display_name()
            frontend_dict["respondent_name"] = frontend_dict['my_name']
            frontend_dict["academic_url"] = you.get_absolute_url()
    else: # 如果存在匿名情况，要注意删去指向学术地图页面的超链接
        if user == chat.questioner: # 我匿名向他人提问
            frontend_dict['my_name'] = "匿名用户"
            frontend_dict["questioner_name"] = "匿名用户"
            you = get_person_or_org(chat.respondent)
            frontend_dict["respondent_name"] = you.get_display_name()
            frontend_dict["academic_url"] = you.get_absolute_url()
        else: # 他人匿名向我提问
            me = get_person_or_org(user)
            frontend_dict['my_name'] = me.get_display_name()
            frontend_dict["questioner_name"] = "匿名用户"
            frontend_dict["respondent_name"] = frontend_dict['my_name']
            frontend_dict["academic_url"] = ""


def add_chat_message(request: HttpRequest, chat: Chat) -> MESSAGECONTEXT:
    """
    给一个chat发送新comment，并给接收者发通知（复用了comment_utils.py/addComment）

    :param request: addComment函数会用到，其user即为发送comment的用户，其POST参数至少应当包括：comment_submit（点击“回复”按钮），comment（回复内容）
    :type request: HttpRequest
    :param chat
    :type chat: Chat
    :return: 表明发送结果的MESSAGECONTEXT
    :rtype: MESSAGECONTEXT
    """
    # 只能发给PROGRESSING的chat
    if chat.status == Chat.Status.CLOSED:
        return wrong("当前问答已关闭，无法发送新信息!")
    if chat.status == Chat.Status.FORBIDDEN and request.user == chat.questioner:
        return wrong("对方目前不允许匿名用户提问!")
    
    if request.user == chat.questioner:
        receiver = chat.respondent # 我是这个chat的提问方，则我发送新comment时chat的接收方会收到通知
        anonymous = chat.anonymous_flag # 如果chat是匿名提问的，则我作为提问方发送新comment时需要匿名
    else:
        receiver = chat.questioner # 我是这个chat的接收方，则我发送新comment时chat的提问方会收到通知
        anonymous = False # 接收方发送的comment一定是实名的
    
    comment_context = addComment( # 复用comment_utils.py，这个函数包含了通知发送功能
        request, chat, receiver, anonymous=anonymous, notification_title='学术地图问答信息')
    return comment_context


def create_chat(request: HttpRequest, respondent: User, title: str, anonymous: bool=False) -> Tuple[int, MESSAGECONTEXT]:
    """
    创建新chat并调用add_chat_message发送首条提问
    将在views.py中被用到，因为发起问答的端口在个人主页-学术地图

    :param request: add_chat_message会用到
    :type request: HttpRequest
    :param respondent: 被提问的人
    :type respondent: User
    :param title: chat主题，不超过50字
    :type title: str
    :param anonymous: chat是否匿名, defaults to False
    :type anonymous: bool, optional
    :return: 新chat的id（创建失败为-1）和表明创建chat/发送提问结果的MESSAGECONTEXT
    :rtype: Tuple[int, MESSAGECONTEXT]
    """
    if len(title) > 50: # Chat.title的max_length为50
        return -1, wrong("主题长度超过50字!")
    if len(request.POST["comment"]) == 0:
        return -1, wrong("提问内容不能为空!")
    # 本函数暂未考虑receiver不允许匿名提问的情况，chat的初始status均为PROGRESSING
    chat = Chat.objects.create(
        questioner=request.user,
        respondent=respondent,
        title=title,
        anonymous_flag=anonymous
    )
    # 创建chat后没有发送消息，随后创建chat的第一条comment时会发送消息
    
    comment_context = add_chat_message(request, chat)
    # 如果创建comment成功，应该跳转到viewChat页面；如果失败，应该留在学术地图页面并显示warn_message

    return chat.id, comment_context
