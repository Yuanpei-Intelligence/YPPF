import pandas as pd
import os
from app.models import NaturalPerson, Position, Organization, OrganizationType
from django.contrib.auth.models import User

BASE_DIR = "/Users/rickymac/Documents/20Autmun/ypdev/YPPF/boot/boottest/"


def load(format=0):
    # df_2018 = pd.read_csv(BASE_DIR + 'static/2018.csv')
    if format == 0:
        df_1819 = pd.read_csv('test_data/stuinf.csv',encoding='utf-8')
    elif format == 1:
        df_1819 = pd.read_csv("test_data/orginf.csv",encoding='utf-8')
    elif format == 2:
        df_1819 = pd.read_csv("test_data/orgtypeinf.csv",encoding='utf-8')
    return df_1819


def load_orgtype():
    username = "YPadmin"
    user, mid = User.objects.get_or_create(username=username)
    password = "YPPFtest"
    user.set_password(password)
    user.save()
    Nperson, mid = NaturalPerson.objects.get_or_create(person_id=user)
    Nperson.name = username
    Nperson.save()
    orgfile = load(format=2)
    for i in range(len(orgfile)):
        type_id = int(orgfile["otype_id"].iloc[i])
        type_name = str(orgfile["otype_name"].iloc[i])
        # otype_superior_id = int(orgfile['otype_superior_id'].iloc[i])
        incharge = str(orgfile["incharge"].iloc[i])
        orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
        orgtype.otype_name = type_name
        # orgtype.otype_superior_id=otype_superior_id
        Nperson, mid = NaturalPerson.objects.get_or_create(name=incharge)
        orgtype.incharge = Nperson
        orgtype.job_name_list = str(orgfile['job_name_list'].iloc[i])
        orgtype.save()
    return


def load_org():
    orgfile = load(format=1)
    for i in range(len(orgfile)):
        username = str(orgfile["organization_id"].iloc[i])
        if username[:2] == "zz":
            password = "YPPFtest"
            oname = str(orgfile["oname"].iloc[i])
            type_id = str(orgfile["otype_id"].iloc[i])
            person = str(orgfile["person"].iloc[i])
            user, mid = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()
            orgtype, mid = OrganizationType.objects.get_or_create(otype_id=type_id)
            org, mid = Organization.objects.get_or_create(organization_id=user, otype=orgtype)
            org.oname = oname
            org.save()

            people, mid = NaturalPerson.objects.get_or_create(name=person)
            pos, mid = Position.objects.get_or_create(person=people, org=org)
            pos.save()
            # orgtype=OrganizationType.objects.create(otype_id=type_id)
            # orgtype.otype

    return
