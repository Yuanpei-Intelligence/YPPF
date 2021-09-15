from django.dispatch.dispatcher import receiver
from app.models import (
    NaturalPerson,
    Organization,
    Notification,
    QandA,
)
import app.utils as utils
from django.db import transaction
from datetime import datetime
from app.notification_utils import notification_create

def QA_create(sender, receiver, Q_text, anonymous_flag=False):
    # sender: user
    # receiver: user
    # Q_text: str(提问内容)
    # anonymous_flag: 是否匿名
    new_qa = QandA.objects.create(
        sender=sender,
        receiver=receiver,
        Q_text=Q_text,
        anonymous_flag=anonymous_flag,
    )
    notification_create(
        receiver=receiver,
        sender=sender,
        typename=Notification.Type.NEEDREAD,
        title="您收到了一条提问",
        content="请点击本条通知的标题，进入问答中心查看我的提问！",
        URL='/QAcenter/',
        anonymous_flag=anonymous_flag
    )

def QA_anwser(QA_id, A_text):
    with transaction.atomic():
        qa = QandA.objects.select_for_update().get(id=QA_id)
        qa.A_text = A_text
        qa.save()
    notification_create(
        receiver=qa.sender,
        sender=qa.receiver,
        typename=Notification.Type.NEEDREAD,
        title="您收到了一条回答",
        content=A_text,
        URL='/QAcenter/',
    )

def QA_ignore(QA_id, sender_flag=True):
    with transaction.atomic():
        qa = QandA.objects.select_for_update().get(id=QA_id)
        # 如果两边都ignore了，就delete
        if sender_flag:
            qa.status = QandA.Status.DELETE if qa.status == QandA.Status.IGNORE_RECEIVER else QandA.Status.IGNORE_SENDER
        else:
            qa.status = QandA.Status.DELETE if qa.status == QandA.Status.IGNORE_SENDER else QandA.Status.IGNORE_RECEIVER
        qa.save()

def QA_delete(QA_id):
    with transaction.atomic():
        qa = QandA.objects.select_for_update().get(id=QA_id)
        qa.status = QandA.Status.DELETE
        qa.save()
    
def QA2Display(user):
    all_instances = dict()
    all_instances['send'], all_instances['receive'] = [], []
    instances = {
        "send": QandA.objects.activated(sender_flag=True).filter(sender=user).order_by("-Q_time"),
        "receive": QandA.objects.activated(receiver_flag=True).filter(receiver=user).order_by("-Q_time"),
    }

    for qa in instances['send']:
        QA = dict()
        sender, receiver = utils.get_person_or_org(qa.sender), utils.get_person_or_org(qa.receiver)
        QA['sender'] = sender.name if hasattr(qa.sender, "naturalperson") else sender.oname
        if qa.anonymous_flag:
            QA['sender'] = "匿名者"
        QA['receiver'] = receiver.name if hasattr(qa.receiver, "naturalperson") else receiver.oname
        QA['Q_text'] = qa.Q_text
        QA['A_text'] = qa.A_text
        QA['Q_time'] = qa.Q_time
        QA['A_time'] = qa.A_time
        QA['id'] = qa.id
        QA['anwser_flag'] = (len(qa.A_text) != 0)
        all_instances['send'].append(QA)

    for qa in instances['receive']:
        QA = dict()
        sender, receiver = utils.get_person_or_org(qa.sender), utils.get_person_or_org(qa.receiver)
        QA['sender'] = sender.name if hasattr(qa.sender, "naturalperson") else sender.oname
        if qa.anonymous_flag:
            QA['sender'] = "匿名者"
        QA['receiver'] = receiver.name if hasattr(qa.receiver, "naturalperson") else receiver.oname
        QA['Q_text'] = qa.Q_text
        QA['A_text'] = qa.A_text
        QA['Q_time'] = qa.Q_time
        QA['A_time'] = qa.A_time
        QA['id'] = qa.id
        QA['anwser_flag'] = (len(qa.A_text) != 0)
        all_instances['receive'].append(QA)
    return all_instances