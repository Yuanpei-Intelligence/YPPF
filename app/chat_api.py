from app.views_dependency import *
from app.models import Chat
from app.chat_utils import (
    change_chat_status,
    select_by_keywords,
    modify_rating,
    create_QA,
    add_comment_to_QA,
)

__all__ = [
    'StartChat', 'AddComment', 'CloseChat', 'StartUndirectedChat', 'RateAnswer'
]


class StartChat(ProfileJsonView):
    def prepare_post(self):
        self.receiver_id = int(self.request.POST['receiver_id'])
        self.questioner_anonymous = self.request.POST['comment_anonymous'] == 'true'
        return self.post

    def post(self):
        '''创建一条新的chat'''
        respondent = User.objects.get(username=self.receiver_id)

        context = create_QA(self.request, respondent, directed=True,
                            questioner_anonymous=self.questioner_anonymous)
        return self.message_response(context)


class AddComment(ProfileJsonView):
    need_prepare = False
    def post(self):
        '''向聊天中添加对话'''
        return self.message_response(add_comment_to_QA(self.request))


class CloseChat(ProfileJsonView):
    def prepare_post(self):
        self.chat_id = int(self.request.POST['chat_id'])
        return self.post

    def post(self):
        '''终止聊天'''
        message_context = change_chat_status(self.chat_id, Chat.Status.CLOSED)
        return self.message_response(message_context)


class StartUndirectedChat(ProfileJsonView):
    def prepare_post(self):
        self.questioner_anonymous = self.request.POST['comment_anonymous'] == 'true'
        self.keywords = self.request.POST['keywords'].split(sep=',')
        return self.post

    def post(self):
        """
        开始非定向问答
        """
        respondent, message_context = select_by_keywords(
            self.request.user, self.questioner_anonymous, self.keywords)
        if respondent is None:
            return self.message_response(message_context)

        context = create_QA(self.request, respondent, directed=False,
                            questioner_anonymous=self.questioner_anonymous,
                            keywords=self.keywords)
        return self.message_response(context)


class RateAnswer(ProfileJsonView):
    def prepare_post(self):
        self.chat_id = int(self.request.POST['chat_id'])
        self.rating = int(self.request.POST['rating'])
        return self.post

    def post(self):
        '''提问方对回答质量给出评价'''
        return self.message_response(modify_rating(self.chat_id, self.rating))
