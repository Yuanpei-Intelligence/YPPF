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


class StartChat(SecureJsonView):
    def post(self):
        """
        创建一条新的chat
        """
        try:
            respondent = User.objects.get(
                name=self.request.POST['receiver_id'])
        except:
            return self.message_response(wrong("出现了意料之外的错误！"))
        questioner_anonymous = self.request.POST['comment_anonymous'] == 'true'

        return self.message_response(
            create_QA(self.request,
                      respondent,
                      directed=True,
                      questioner_anonymous=questioner_anonymous))


class AddComment(SecureJsonView):
    def post(self):
        """
        向聊天中添加对话
        """
        return self.message_response(add_comment_to_QA(self.request))


class CloseChat(SecureJsonView):
    def post(self):
        """
        终止聊天
        """
        message_context = change_chat_status(self.request.POST.get("chat_id"),
                                             Chat.Status.CLOSED)
        return self.message_response(message_context)


class StartUndirectedChat(SecureJsonView):
    def post(self):
        """
        开始非定向问答
        """
        questioner_anonymous = (
            self.request.POST['comment_anonymous'] == 'true')
        keywords = self.request.POST.get('keywords').split(sep=',')
        respondent, message_context = select_by_keywords(
            self.request.user, questioner_anonymous, keywords)
        if respondent is None:
            return self.message_response(message_context)

        return self.message_response(
            create_QA(self.request,
                      respondent,
                      directed=False,
                      questioner_anonymous=questioner_anonymous,
                      keywords=keywords))


class RateAnswer(SecureJsonView):
    def post(self):
        """
        提问方对回答质量给出评价
        """
        chat_id = self.request.POST.get('chat_id')
        rating = self.request.POST.get('rating')

        return self.message_response(modify_rating(chat_id, rating))
