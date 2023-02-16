from app.views_dependency import *
from app.models import Chat
from app.chat_utils import (
    change_chat_status,
    add_chat_message,
    create_chat,
    create_undirected_chat,
    select_by_keywords,
    modify_rating,
)

__all__ = [
    'StartChat', 'AddChatComment', 'CloseChat', 'StartUndirectedChat',
    'RateAnswer'
]


class StartChat(SecureJsonView):
    def post(self):
        """
        创建一条新的chat
        """
        receiver = User.objects.get(id=self.request.POST['receiver_id'])
        anonymous = (self.request.POST['comment_anonymous'] == 'true')

        _, message_context = create_chat(
            self.request,
            receiver,
            self.request.POST['comment_title'],
            questioner_anonymous=anonymous,
        )
        return self.message_response(message_context)


class AddChatComment(SecureJsonView):
    def post(self):
        """
        向聊天中添加对话
        """
        try:
            chat = Chat.objects.get(id=self.request.POST.get('chat_id'))
        except:
            return self.json_response(wrong('问答不存在!'))

        message_context = add_chat_message(self.request, chat)
        return self.message_response(message_context)


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
        keywords = self.request.POST.get('keywords').split(sep=',')
        respondent, message_context = select_by_keywords(
            self.request.user, keywords)
        if respondent is None:
            return self.message_response(message_context)
        anonymous = (self.request.POST['comment_anonymous'] == 'true')

        chat_id, message_context = create_chat(
            self.request,
            respondent=respondent,
            title=self.request.POST.get('comment_title'),
            questioner_anonymous=anonymous,
            respondent_anonymous=True,
        )
        if chat_id is None:
            return self.message_response(message_context)

        message_context = create_undirected_chat(chat_id, keywords)
        return self.message_response(message_context)


class RateAnswer(SecureJsonView):
    def post(self):
        """
        提问方对回答质量给出评价
        """
        chat_id = self.request.POST.get('chat_id')
        rating = self.request.POST.get('rating')

        return self.message_response(modify_rating(chat_id, rating))
