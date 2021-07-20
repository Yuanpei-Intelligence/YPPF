import pandas as pd
import os
from app.models import NaturalPerson, Position, Organization, OrganizationType
from django.contrib.auth.models import User

BASE_DIR = '/Users/rickymac/Documents/20Autmun/ypdev/YPPF/boot/boottest/'


def load(format=0):
    # df_2018 = pd.read_csv(BASE_DIR + 'static/2018.csv')
    if format == 0:
        df_1819 = pd.read_csv('app/append.csv')
    elif format == 1:
        df_1819 = pd.read_csv('./orginf.csv')
    elif format == 2:
        df_1819 = pd.read_csv('./orgtypeinf.csv')
    return df_1819


def load_orgtype():
    username = 'YPadmin'
    user, mid = User.objects.get_or_create(username=username)
    user.set_password('YPPFtest')
    Nperson, mid = NaturalPerson.objects.get_or_create(pid=user)
    Nperson.pname = username
    Nperson.save()
    orgfile = load(format=2)
    for i in range(len(orgfile)):
        type_id = int(orgfile['otype_id'].iloc[i])
        type_name = str(orgfile['otype_name'].iloc[i])
        # otype_superior_id = int(orgfile['otype_superior_id'].iloc[i])
        incharge = str(orgfile['oincharge'].iloc[i])
        orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
        orgtype.otype_name = type_name
        # orgtype.otype_superior_id=otype_superior_id
        Nperson, mid = NaturalPerson.objects.get_or_create(pname=incharge)
        orgtype.oincharge = Nperson
        orgtype.save()
    return


def load_org():
    orgfile = load(format=1)
    for i in range(len(orgfile)):
        username = str(orgfile['oid'].iloc[i])
        if username[:2] == 'zz':
            password = 'YPPFtest'
            oname = str(orgfile['oname'].iloc[i])
            type_id = str(orgfile['otype_id'].iloc[i])
            person = str(orgfile['person'].iloc[i])
            user, mid = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()
            orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
            org, mid = Organization.objects.get_or_create(oid=user, otype=orgtype, oname=oname)
            org.save()

            people, mid = NaturalPerson.objects.get_or_create(pname=person)
            pos, mid = Position.objects.get_or_create(person=people, org=org)
            pos.save()
            # orgtype=OrganizationType.objects.create(otype_id=type_id)
            # orgtype.otype

    return
