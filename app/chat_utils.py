from collections import Counter
from random import sample
from typing import Tuple

from django.http import HttpRequest

from generic.models import YQPointRecord
from app.utils_dependency import *
from app.models import (
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,
    User,
    Chat,
    AcademicQA,
    AcademicQAAwards,
)
from app.comment_utils import addComment
from achievement.api import unlock_achievement

__all__ = [
    'change_chat_status',
    'select_by_keywords',
    'create_QA',
    'add_comment_to_QA',
    'modify_rating',
]


def change_chat_status(chat_id: int, to_status: Chat.Status) -> MESSAGECONTEXT:
    """
    修改chat的状态

    :param chat_id
    :type chat_id: int
    :param to_status: 目标状态
    :type to_status: Chat.Status
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

        if to_status == Chat.Status.CLOSED:
            chat.status = Chat.Status.CLOSED
            chat.save()
            succeed("您已成功关闭当前提问！", context)
        elif to_status == Chat.Status.PROGRESSING:  # 这个目前没有用到
            raise NotImplementedError
            chat.status = Chat.Status.PROGRESSING
            chat.save()
            succeed("您已成功开放一个问答！", context)
        return context


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
    if (not chat.respondent.accept_anonymous_chat
            ) and chat.questioner_anonymous:
        if request.user == chat.respondent:
            return wrong("您目前处于禁用匿名提问状态!")
        else:
            return wrong("对方目前不允许匿名提问!")

    if request.user == chat.questioner:
        receiver = chat.respondent  # 我是这个chat的提问方，则我发送新comment时chat的接收方会收到通知
        anonymous = chat.questioner_anonymous  # 如果chat是匿名提问的，则我作为提问方发送新comment时需要匿名
    else:
        receiver = chat.questioner  # 我是这个chat的接收方，则我发送新comment时chat的提问方会收到通知
        anonymous = False  # 接收方发送的comment一定是实名的

    comment_context = addComment(  # 复用comment_utils.py，这个函数包含了通知发送功能
        request,
        chat,
        receiver,
        anonymous=anonymous,
        notification_title='学术地图问答信息')
    return comment_context


def create_chat(
        request: HttpRequest,
        respondent: User,
        title: str,
        questioner_anonymous: bool = False,
        respondent_anonymous: bool = False
) -> Tuple[int | None, MESSAGECONTEXT]:
    """
    创建新chat并调用add_chat_message发送首条提问

    :param request: add_chat_message会用到
    :type request: HttpRequest
    :param respondent: 被提问的人
    :type respondent: User
    :param title: chat主题，不超过50字
    :type title: str
    :param anonymous: chat是否匿名, defaults to False
    :type anonymous: bool, optional
    :return: 新chat的id（创建失败为None）和表明创建chat/发送提问结果的MESSAGECONTEXT
    :rtype: Tuple[int | None, MESSAGECONTEXT]
    """
    if (not respondent.accept_anonymous_chat) and questioner_anonymous:
        return None, wrong("对方不允许匿名提问！")

    # 目前提问方回答方都需要是自然人
    if not request.user.is_person() or not respondent.is_person():
        return None, wrong("目前只允许个人用户进行问答！")

    if len(title) > 50:  # Chat.title的max_length为50
        return None, wrong("主题过长！请勿超过50字")
    if len(request.POST["comment"]) == 0:
        return None, wrong("提问内容不能为空！")

    with transaction.atomic():
        chat = Chat.objects.create(
            questioner=request.user,
            respondent=respondent,
            title=title,
            questioner_anonymous=questioner_anonymous,
            respondent_anonymous=respondent_anonymous,
        )
        # 创建chat后没有发送通知，随后创建chat的第一条comment时会发送通知
        comment_context = add_chat_message(request, chat)

    return chat.id, comment_context


def get_matched_users(query: str, current_user: User, anonymous: bool):
    """
    根据提供的关键词获取搜索结果
    比academic_utils中的类似函数更加精简
    """
    # 搜索所有含有关键词的公开的学术地图项目，忽略大小写
    match_with_tags = SQ.qsvlist(AcademicTagEntry.objects.filter(
            tag__tag_content__icontains=query,
            status=AcademicEntry.EntryStatus.PUBLIC,
        ), AcademicEntry.person, NaturalPerson.person_id)

    match_with_texts = SQ.qsvlist(AcademicTextEntry.objects.filter(
            content__icontains=query,
            status=AcademicEntry.EntryStatus.PUBLIC,
        ), AcademicEntry.person, NaturalPerson.person_id)

    matched_ids = match_with_tags + match_with_texts
    matched_users = User.objects.exclude(
        username=current_user.username).filter(id__in=matched_ids)

    if anonymous:
        return matched_users.filter(accept_anonymous_chat=True)
    else:
        return matched_users


def select_by_keywords(
        user: User, anonymous: bool,
        keywords: list[str]) -> Tuple[User | None, MESSAGECONTEXT]:
    """
    根据关键词从学生中抽取一个回答者
    """
    matched_users = []
    for k in keywords:
        matched_users.extend(list(get_matched_users(k, user, anonymous)))

    counted_users = Counter()
    counted_users.update(matched_users)
    greatest_occurrence = counted_users.most_common(1)[0][1]
    most_matched_users = [
        user[0] for user in counted_users.items()
        if user[1] == greatest_occurrence
    ]

    if not most_matched_users:
        return None, wrong("没有和标签匹配的对象！")

    chosen_users = sample(most_matched_users, k=1)[0]
    return chosen_users, succeed("成功找到回答者")


def create_QA(request: HttpRequest,
              respondent: User,
              directed: bool,
              questioner_anonymous: bool,
              keywords: None | list[str] = None) -> MESSAGECONTEXT:
    """
    创建学术地图问答，包括定向和非定向

    :param respondent: 回答者
    :type respondent: User
    :param directed: 是否为定向问答
    :type directed: bool
    :param questioner_anonymous: 提问者是否匿名
    :type questioner_anonymous: bool
    :param keywords: 关键词，暂时只在非定向问答中使用，用来定位回答者。
    :type keywords: None | list[str]
    """
    respondent_anonymous = not directed
    chat_id, message_context = create_chat(
        request,
        respondent=respondent,
        title=request.POST.get('comment_title'),
        questioner_anonymous=questioner_anonymous,
        respondent_anonymous=respondent_anonymous,
    )
    if chat_id is None:
        return message_context

    with transaction.atomic():
        AcademicQA.objects.create(
            chat_id=chat_id,
            keywords=keywords,
            directed=directed,
        )

    # 解锁成就-参与学术问答
    unlock_achievement(request.user, "参与学术问答")

    # 奖励仅限第一次发起非定向提问
    if directed:
        return succeed("提问成功")

    award_points = 5
    award, created = AcademicQAAwards.objects.get_or_create(user=request.user)
    if created or not award.created_undirected_qa:
        User.objects.modify_YQPoint(
            request.user, award_points, "学术地图: 首次发起非定向提问", source_type=YQPointRecord.SourceType.ACHIEVE)
        award.created_undirected_qa = True
        award.save()
        return succeed(f"首次发起非定向提问，奖励{award_points}元气值～")

    return succeed("提问成功")


def modify_rating(chat_id: int, rating: int) -> MESSAGECONTEXT:
    assert rating >= 0 and rating <= 3
    award_points = [0, 5, 8, 12]  # 评价对应的奖励值
    with transaction.atomic():
        qa: AcademicQA = AcademicQA.objects.get(chat_id=chat_id)
        qa.rating = rating
        User.objects.modify_YQPoint(qa.chat.respondent, award_points[rating],
                                    "学术问答: 回答得到好评",
                                    YQPointRecord.SourceType.ACHIEVE)
        qa.save()

    return succeed("成功修改评价")


def add_comment_to_QA(request: HttpRequest) -> MESSAGECONTEXT:
    try:
        # TODO: 以后换成AcademicQA的id
        chat = Chat.objects.get(id=request.POST.get('chat_id'))
    except:
        return wrong('问答不存在!')

    message_context = add_chat_message(request, chat)
    if message_context[my_messages.CODE_FIELD] == my_messages.WRONG:
        return message_context

    anonymous = request.POST.get('anonymous')
    if anonymous == 'true':
        return message_context

    with transaction.atomic():
        if request.user == chat.respondent:
            Chat.objects.select_for_update().filter(id=chat.id).update(
                respondent_anonymous=False)
        else:
            Chat.objects.select_for_update().filter(id=chat.id).update(
                questioner_anonymous=False)

    # 解锁成就-参与学术问答
    unlock_achievement(request.user, "参与学术问答")

    return message_context
