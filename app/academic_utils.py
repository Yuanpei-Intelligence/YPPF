from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,
    User,
    Chat,
)
from app.constants import UTYPE_PER
from app.utils import get_person_or_org, check_user_type
from app.comment_utils import showComment

from django.http import HttpRequest
from django.db.models import QuerySet

from typing import List, Dict, Set
from collections import defaultdict

__all__ = [
    'get_search_results',
    'chats2Display', 
    'comments2Display',
    'get_js_tag_list',
    'get_text_list',
    'get_tag_status',
    'get_text_status',
    'update_tag_entry',
    'update_text_entry',
    'update_academic_map',
    'get_wait_audit_student',
    'audit_academic_map',
    'have_entries_of_type',
]


def get_search_results(query: str):
    """
    根据提供的关键词获取搜索结果。

    :param keyword: 关键词
    :type keyword: str
    :return: 搜索结果list，元素为dict，包含key：姓名、年级、条目内容中包含关键词的条目名。
             一个条目名可能对应一个或多个内容（如参与多个科研项目等），因此条目名对应的value统一用list打包。
    :rtype: List[dict]
    """
    # TODO: 更新文档
    # 首先搜索所有含有关键词的公开的学术地图项目，忽略大小写，同时转换成QuerySet[dict]
    academic_tags = AcademicTagEntry.objects.filter( 
        tag__tag_content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values_list(
        "person__person_id__username",  # person_id_id用于避免重名
        "tag__atype", "tag__tag_content",
    )
    academic_texts = AcademicTextEntry.objects.filter(
        content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values_list(
        "person__person_id__username", 
         "atype", "content",
    )

    type2display = {ty: label for ty, label in AcademicTag.Type.choices}

    # 然后根据tag/text对应的人，整合学术地图项目
    # 使用defaultdict会导致前端items不可用，原因未知
    academic_map_dict: 'dict[str, dict[str, list]]' = dict()
    for sid, ty, content in academic_tags:
        # 将choice的值更新为对应的选项名
        tag_type = type2display[ty]
        academic_map_dict.setdefault(sid, {})
        academic_map_dict[sid].setdefault(text_type, [])
        academic_map_dict[sid][tag_type].append(content)
    
    for sid, ty, content in academic_texts:
        text_type = type2display[ty]
        academic_map_dict.setdefault(sid, {})
        academic_map_dict[sid].setdefault(text_type, [])
        academic_map_dict[sid][text_type].append(content)
    
    return academic_map_dict


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
            chat_dict['anonymously_sent'] = chat.anonymous # 我以匿名方式发给别人，“问答中心”页面的卡片上会显示[匿名]
            valid, receiver_type, _ = check_user_type(chat.respondent) # 学术地图应该只能是个人，不过以后或许可能复用Chat模型？
            chat_dict['receiver_type'] = receiver_type
            receiver = get_person_or_org(chat.respondent, receiver_type)
            chat_dict['receiver_name'] = receiver.get_display_name()
            chat_dict['academic_url'] = receiver.get_absolute_url() # 为了在“问答中心”页面的卡片上加入学术地图的url，超链接放在receiver_name上
        else:
            if chat.anonymous: # 他人匿名发给我
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
        #     chat, anonymous_users=[chat.questioner] if chat.anonymous else None) # "问答中心"页面不再显示每个chat的comment
        
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
        chat, anonymous_users=[chat.questioner] if chat.anonymous else None)
    if len(frontend_dict["messages"]) == 0:
        # Chat一定有Comment，正常情况下不会到这里
        frontend_dict["not_found_messages"] = "当前问答没有信息." 
    
    frontend_dict['status'] = chat.get_status_display()
    frontend_dict["commentable"] = (chat.status == Chat.Status.PROGRESSING) # 若为True，则前端会给出评论区和“关闭当前问答”的按钮
    frontend_dict["anonymous_chat"] = chat.anonymous
    frontend_dict["accept_anonymous"] = chat.respondent.accept_anonymous_chat

    # 问答详情页面需要展示“发给xxx的问答”或“来自xxx的问答”，且xxx附有指向学术地图页面的超链接
    # 因而需要判断我是提问者还是回答者，并记录对方的名字
    # 问答详情页面对于我的信息和对方的信息以不同的格式显示
    # 因而还需要记录我的名字，通过和frontend_dict["messages"]中每条记录的commentator.name对比来判断是不是我发的
    # 事实上这些操作如果放到showComment里能减少一些get_display_name、get_person_or_org、get_absolute_url的调用，但需要对showComment做较大修改，就暂时没有整合进去
    if chat.anonymous == False:
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


def get_js_tag_list(author: NaturalPerson, type: AcademicTag.Type,
                    selected: bool, status_in: list=None) -> List[dict]:
    """
    用于前端显示支持搜索的专业/项目列表，返回形如[{id, content}]的列表。

    :param author: 作者自然人信息
    :type author: NaturalPerson
    :param type: 标记所需的tag类型
    :type type: AcademicTag.Type
    :param selected: 用于标记是否获取本人已有的专业项目，selected代表获取前端默认选中的项目
    :type selected: bool
    :param status_in: 所要检索的状态的字符串的列表，如["public","private"]，默认为None，表示搜索全部
    :type status_in: list
    :return: 所有专业/项目组成的List[dict]，key值如上所述
    :rtype: List[dict]
    """
    type_map = {
        "public": AcademicEntry.EntryStatus.PUBLIC,
        "wait_audit": AcademicEntry.EntryStatus.WAIT_AUDIT,
        "private": AcademicEntry.EntryStatus.PRIVATE,
        "outdate": AcademicEntry.EntryStatus.OUTDATE
    }
    stats = []
    if status_in is not None:
        stats = [type_map[s] for s in status_in]
    if selected:
        # me = get_person_or_org(request.user, UTYPE_PER)
        all_my_tags = AcademicTagEntry.objects.activated().filter(person=author)
        if status_in is not None:
            all_my_tags = all_my_tags.filter(status__in=stats)
        tags = all_my_tags.filter(tag__atype=type).values('tag__id', 'tag__tag_content')
        js_list = [{"id": tag['tag__id'], "text": tag['tag__tag_content']} for tag in tags]
    else:
        tags = AcademicTag.objects.filter(atype=type)
        js_list = [{"id": tag.id, "text": tag.tag_content} for tag in tags]

    return js_list


def get_text_list(author: NaturalPerson, type: AcademicTextEntry.AcademicTextType,
                  status_in: list=None) -> List[str]:
    """
    获取自己的所有类型为type的TextEntry的内容列表。

    :param author: 作者自然人信息
    :type author: NaturalPerson
    :param type: TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    :param status_in: 所要检索的状态的字符串的列表，如["public","private"]，默认为None，表示搜索全部
    :type status_in: list
    :return: 含有所有类型为type的TextEntry的content的list
    :rtype: List[str]
    """
    # me = get_person_or_org(request.user, UTYPE_PER)
    type_map = {
        "public": AcademicEntry.EntryStatus.PUBLIC,
        "wait_audit": AcademicEntry.EntryStatus.WAIT_AUDIT,
        "private": AcademicEntry.EntryStatus.PRIVATE,
        "outdate": AcademicEntry.EntryStatus.OUTDATE
    }
    stats = []
    if status_in is not None:
        stats = [type_map[s] for s in status_in]
    all_my_text = AcademicTextEntry.objects.activated().filter(person=author, atype=type)
    if status_in is not None:
        all_my_text = all_my_text.filter(status__in=stats)
    text_list = [text.content for text in all_my_text]
    return text_list


def get_tag_status(person: NaturalPerson, type: AcademicTag.Type) -> str:
    """
    获取person的类型为type的TagEntry的公开状态。
    如果person没有类型为type的TagEntry，返回"公开"。

    :param person: 需要获取公开状态的人
    :type person: NaturalPerson
    :param type: TagEntry的类型
    :type type: AcademicTag.Type
    :return: 公开状态，返回"公开/私密"
    :rtype: str
    """
    # 首先获取person所有的TagEntry
    all_tag_entries = AcademicTagEntry.objects.activated().filter(person=person, tag__atype=type)
    
    if all_tag_entries.exists():
        # 因为所有类型为type的TagEntry的公开状态都一样，所以直接返回第一个entry的公开状态
        entry = all_tag_entries[0]
        return "私密" if entry.status == AcademicEntry.EntryStatus.PRIVATE else "公开"
    else:
        return "公开"


def get_text_status(person: NaturalPerson, type: AcademicTextEntry.AcademicTextType) -> str:
    """
    获取person的类型为type的TextEntry的公开状态。
    如果person没有类型为type的TextEntry，返回"公开"。

    :param person: 需要获取公开状态的人
    :type person: NaturalPerson
    :param type: TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    :return: 公开状态，返回"公开/私密"
    :rtype: str
    """
    # 首先获取person所有的类型为type的TextEntry
    all_text_entries = AcademicTextEntry.objects.activated().filter(person=person, atype=type)
    
    if all_text_entries.exists():
        # 因为所有类型为type的TextEntry的公开状态都一样，所以直接返回第一个entry的公开状态
        entry = all_text_entries[0]
        return "私密" if entry.status == AcademicEntry.EntryStatus.PRIVATE else "公开"
    else:
        return "公开"


def update_tag_entry(person: NaturalPerson, 
                     tag_ids: List[str], 
                     status: bool,
                     type: AcademicTag.Type) -> None:
    """
    更新TagEntry的工具函数。

    :param person: 需要更新学术地图的人
    :type person: NaturalPerson
    :param tag_ids: 含有一系列tag_id(未经类型转换)的list
    :type tag_ids: List[str]
    :param status: tag_ids对应的所有tags的公开状态
    :type status: bool
    :param type: tag_ids对应的所有tags的类型
    :type type: AcademicTag.Type
    """
    # 首先获取person所有的TagEntry
    all_tag_entries = AcademicTagEntry.objects.activated().filter(person=person, tag__atype=type)
    
    for entry in all_tag_entries:
        if not str(entry.tag.id) in tag_ids:
            # 如果用户原有的TagEntry的id在tag_ids中未出现，则将其状态设置为“已弃用”
            entry.status = AcademicEntry.EntryStatus.OUTDATE
            entry.save()
        else:
            # 如果出现，直接更新其状态，并将这个id从tag_ids移除
            entry.status = AcademicEntry.EntryStatus.WAIT_AUDIT if status == "公开" \
                           else AcademicEntry.EntryStatus.PRIVATE
            entry.save()
            tag_ids.remove(str(entry.tag.id))
    
    # 接下来遍历的tag_id都是要新建的tag
    for tag_id in tag_ids:
        AcademicTagEntry.objects.create(
            person=person, tag=AcademicTag.objects.get(id=int(tag_id)),
            status=AcademicEntry.EntryStatus.WAIT_AUDIT if status == "公开" \
                else AcademicEntry.EntryStatus.PRIVATE
        )


def update_text_entry(person: NaturalPerson, 
                      contents: List[str], 
                      status: bool, 
                      type: AcademicTextEntry.AcademicTextType) -> None:
    """
    更新TextEntry的工具函数。

    :param person: 需要更新学术地图的人
    :type person: NaturalPerson
    :param tag_ids: 含有一系列TextEntry的内容的list
    :type tag_ids: List[str]
    :param status: 该用户所有类型为type的TextEntry的公开状态
    :type status: bool
    :param type: contents对应的TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    """
    # 首先获取person所有的类型为type的TextEntry
    all_text_entries = AcademicTextEntry.objects.activated().filter(person=person, atype=type)
    updated_status = AcademicEntry.EntryStatus.WAIT_AUDIT if status == "公开" \
                        else AcademicEntry.EntryStatus.PRIVATE
    previous_num = len(all_text_entries)
    
    # 即将修改/创建的entry总数一定不小于原有的，因此先遍历原有的entry，判断是否更改/删除
    for i, entry in enumerate(all_text_entries):
        if entry.content != contents[i]: 
            # 内容发生修改，需要先将原有的content设置为“已弃用”
            entry.status = AcademicEntry.EntryStatus.OUTDATE
            entry.save()
            if contents[i] != "":  # 只有新的entry的内容不为空才创建
                AcademicTextEntry.objects.create(
                    person=person, atype=type, content=contents[i], 
                    status=updated_status,
                )
        elif entry.status != updated_status:
            # 内容未修改但status修改，只更新entry的状态，不删除
            entry.status = updated_status
            entry.save()
    
    # 接下来遍历的entry均为需要新建的
    for content in contents[previous_num:]:
        if content != "":
            AcademicTextEntry.objects.create(
                person=person, atype=type, content=content,
                status=AcademicEntry.EntryStatus.WAIT_AUDIT if status == "公开" \
                    else AcademicEntry.EntryStatus.PRIVATE
            )


def update_academic_map(request: HttpRequest) -> dict:
    """
    从前端获取填写的学术地图信息，并在数据库中进行更新，返回含有成功/错误信息的dict。

    :param request: http请求
    :type request: HttpRequest
    :return: 含成功/错误信息的dict，用于redirect后页面的前端展示
    :rtype: dict
    """
    # 首先从select栏获取所有选中的TagEntry
    majors = request.POST.getlist('majors')
    minors = request.POST.getlist('minors')
    double_degrees = request.POST.getlist('double_degrees')
    projects = request.POST.getlist('projects')
    
    # 然后从其余栏目获取即将更新的TextEntry
    scientific_research_num = int(request.POST['scientific_research_num'])
    challenge_cup_num = int(request.POST['challenge_cup_num'])
    internship_num = int(request.POST['internship_num'])
    scientific_direction_num = int(request.POST['scientific_direction_num'])
    graduation_num = int(request.POST['graduation_num'])
    scientific_research = [request.POST[f'scientific_research_{i}'] \
                            for i in range(scientific_research_num+1)]
    challenge_cup = [request.POST[f'challenge_cup_{i}'] \
                        for i in range(challenge_cup_num+1)]
    internship = [request.POST[f'internship_{i}'] for i in range(internship_num+1)]
    scientific_direction = [request.POST[f'scientific_direction_{i}'] \
                            for i in range(scientific_direction_num+1)]
    graduation = [request.POST[f'graduation_{i}'] for i in range(graduation_num+1)]
    
    # 对上述五个列表中的所有填写项目，检查是否超过数据库要求的字数上限
    max_length_of = lambda items: max([len(item) for item in items]) if len(items) > 0 else 0
    MAX_LENGTH = 4095
    if max_length_of(scientific_research) > MAX_LENGTH:
        return wrong("您设置的本科生科研经历太长啦！请修改~")
    elif max_length_of(challenge_cup) > MAX_LENGTH:
        return wrong("您设置的挑战杯经历太长啦！请修改~")
    elif max_length_of(internship) > MAX_LENGTH:
        return wrong("您设置的实习经历太长啦！请修改~")
    elif max_length_of(scientific_direction) > MAX_LENGTH:
        return wrong("您设置的科研方向太长啦！请修改~")
    elif max_length_of(graduation) > MAX_LENGTH:
        return wrong("您设置的毕业去向太长啦！请修改~")
    
    # 从checkbox获取所有栏目的公开状态
    major_status = request.POST['major_status']
    minor_status = request.POST['minor_status']
    double_degree_status = request.POST['double_degree_status']
    project_status = request.POST['project_status']
    scientific_research_status = request.POST['scientific_research_status']
    challenge_cup_status = request.POST['challenge_cup_status']
    internship_status = request.POST['internship_status']
    scientific_direction_status = request.POST['scientific_direction_status']
    graduation_status = request.POST['graduation_status']
    
    # 获取前端信息后对数据库进行更新
    with transaction.atomic():
        me = get_person_or_org(request.user, UTYPE_PER)
        
        # 首先更新自己的TagEntry
        update_tag_entry(me, majors, major_status, AcademicTag.Type.MAJOR)
        update_tag_entry(me, minors, minor_status, AcademicTag.Type.MINOR)
        update_tag_entry(me, double_degrees, double_degree_status, 
                         AcademicTag.Type.DOUBLE_DEGREE)
        update_tag_entry(me, projects, project_status, AcademicTag.Type.PROJECT)
        
        # 然后更新自己的TextEntry
        update_text_entry(
            me, scientific_research, scientific_research_status, 
            AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH
        )
        update_text_entry(
            me, challenge_cup, challenge_cup_status, 
            AcademicTextEntry.AcademicTextType.CHALLENGE_CUP
        )
        update_text_entry(
            me, internship, internship_status, 
            AcademicTextEntry.AcademicTextType.INTERNSHIP
        )
        update_text_entry(
            me, scientific_direction, scientific_direction_status, 
            AcademicTextEntry.AcademicTextType.SCIENTIFIC_DIRECTION
        )
        update_text_entry(
            me, graduation, graduation_status, 
            AcademicTextEntry.AcademicTextType.GRADUATION
        )
        
        # 最后更新是否允许他人提问
        accept_chat = request.POST["accept_chat"]
        request.user.accept_chat = True if accept_chat == "True" else False
        request.user.save()
    
    return succeed("学术地图修改成功！")


def get_wait_audit_student() -> Set[NaturalPerson]:
    """
    获取当前审核中的AcademicEntry对应的学生，因为要去重，所以返回一个集合

    :return: 当前审核中的AcademicEntry对应的NaturalPerson组成的集合
    :rtype: Set[NaturalPerson]
    """
    wait_audit_tag_entries = AcademicTagEntry.objects.filter(
        status=AcademicEntry.EntryStatus.WAIT_AUDIT)
    wait_audit_text_entries = AcademicTextEntry.objects.filter(
        status=AcademicEntry.EntryStatus.WAIT_AUDIT)
    
    wait_audit_students = set()
    for entry in wait_audit_tag_entries:
        wait_audit_students.add(entry.person)
    for entry in wait_audit_text_entries:
        wait_audit_students.add(entry.person)
    
    return wait_audit_students


def audit_academic_map(author: NaturalPerson) -> None:
    """
    审核通过某用户的记录。
    :param author: 被审核用户
    :type author: NaturalPerson
    """
    # 筛选所有待审核的记录
    AcademicTagEntry.objects.activated().filter(
        person=author, status=AcademicEntry.EntryStatus.WAIT_AUDIT).update(
        status=AcademicEntry.EntryStatus.PUBLIC)

    AcademicTextEntry.objects.activated().filter(
        person=author, status=AcademicEntry.EntryStatus.WAIT_AUDIT).update(
        status=AcademicEntry.EntryStatus.PUBLIC)


def have_entries_of_type(author: NaturalPerson, status_in: list) -> bool:
    """
    判断用户有无status属性为public/wait_audit...的学术地图条目(tag和text)
    :param author: 条目作者用户
    :type author: NaturalPerson
    :param status_in: ["public", "wait_audit", "private", "outdate"]中的str构成的list
    :type status_in: list
    :return: 是否有该类别的条目
    :rtype: bool
    """
    type_map = {
        "public": AcademicEntry.EntryStatus.PUBLIC,
        "wait_audit": AcademicEntry.EntryStatus.WAIT_AUDIT,
        "private": AcademicEntry.EntryStatus.PRIVATE,
        "outdate": AcademicEntry.EntryStatus.OUTDATE
    }
    stats = [type_map[s] for s in status_in]
    all_tag_entries = AcademicTagEntry.objects.activated().filter(
        person=author, status__in=stats)
    all_text_entries = (AcademicTextEntry.objects.activated().filter(
        person=author, status__in=stats))
    return bool(all_tag_entries) or bool(all_text_entries)
