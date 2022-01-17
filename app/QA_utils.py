from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    Organization,
    Notification,
    QandA,
)
from app.notification_utils import notification_create
from app import utils

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
        "send": QandA.objects.activated(sender_flag=True).select_related('receiver').filter(sender=user).order_by("-Q_time"),
        "receive": QandA.objects.activated(receiver_flag=True).select_related('sender').filter(receiver=user).order_by("-Q_time"),
    }

    me = NaturalPerson.objects.get(person_id=user) if hasattr(user, 'naturalperson') \
        else Organization.objects.get(organization_id=user)
    my_name = me.name if hasattr(user, "naturalperson") else me.oname
    
    receiver_userids = instances['send'].values_list('receiver_id', flat=True)
    sender_userids = instances['receive'].values_list('sender_id', flat=True)

    sender_persons = NaturalPerson.objects.filter(person_id__in=sender_userids).values_list('person_id', 'name')
    sender_persons = {userid: name for userid, name in sender_persons}
    sender_orgs = Organization.objects.filter(organization_id__in=sender_userids).values_list('organization_id', 'oname')
    sender_orgs = {userid: name for userid, name in sender_orgs}

    receiver_persons = NaturalPerson.objects.filter(person_id__in=receiver_userids).values_list('person_id', 'name')
    receiver_persons = {userid: name for userid, name in receiver_persons}
    receiver_orgs = Organization.objects.filter(organization_id__in=receiver_userids).values_list('organization_id', 'oname')
    receiver_orgs = {userid: name for userid, name in receiver_orgs}

    for qa in instances['send']:
        QA = dict()
        QA['sender'] = my_name
        if qa.anonymous_flag:
            QA['sender'] += "(匿名)"
        
        _, user_type, _ = utils.check_user_type(qa.receiver)
        if user_type == "Organization":
            QA["receiver"] = receiver_orgs.get(qa.receiver_id)
        else:
            QA["receiver"] = receiver_persons.get(qa.receiver_id)

        QA['Q_text'] = qa.Q_text
        QA['A_text'] = qa.A_text
        QA['Q_time'] = qa.Q_time
        QA['A_time'] = qa.A_time
        QA['id'] = qa.id
        QA['anwser_flag'] = (len(qa.A_text) != 0)
        all_instances['send'].append(QA)

    for qa in instances['receive']:
        QA = dict()
        if qa.anonymous_flag:
            QA['sender'] = "匿名者"
        else:
            _, user_type, _ = utils.check_user_type(qa.sender)
            if user_type == "Organization":
                QA["sender"] = sender_orgs.get(qa.sender_id)
            else:
                QA["sender"] = sender_persons.get(qa.sender_id)
        
        QA['receiver'] = my_name
        QA['Q_text'] = qa.Q_text
        QA['A_text'] = qa.A_text
        QA['Q_time'] = qa.Q_time
        QA['A_time'] = qa.A_time
        QA['id'] = qa.id
        QA['anwser_flag'] = (len(qa.A_text) != 0)
        all_instances['receive'].append(QA)
    return all_instances
