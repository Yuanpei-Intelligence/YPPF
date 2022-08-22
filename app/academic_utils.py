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
from app.comment_utils import showComment

from typing import List, Dict
from collections import defaultdict

__all__ = [
    'get_search_results','chats2Display', 'comments2Display',
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
        else:
            chat_dict['title'] = chat.title or "无主题"
        
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
    frontend_dict['title'] = chat.title or "无主题"
    frontend_dict["chat_id"] = chat.id

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
        frontend_dict['my_name'] = get_person_or_org(user).get_display_name()
        if user == chat.questioner:
            frontend_dict["questioner_name"] = frontend_dict['my_name']
            the_other = get_person_or_org(chat.respondent)
            frontend_dict["respondent_name"] = the_other.get_display_name()
            frontend_dict["academic_url"] = the_other.get_absolute_url()
        else:
            the_other = get_person_or_org(chat.questioner)
            frontend_dict["questioner_name"] = the_other.get_display_name()
            frontend_dict["respondent_name"] = frontend_dict['my_name']
            frontend_dict["academic_url"] = the_other.get_absolute_url()
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
