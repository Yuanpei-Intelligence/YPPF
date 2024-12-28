import math
from datetime import datetime
from typing import Callable

import numpy
import pandas as pd
from tqdm import tqdm
from django.db import transaction

import utils.models.query as SQ
from boot.config import DEBUG
from app.config import *
from app.models import (
    User,
    NaturalPerson,
    Position,
    Organization,
    OrganizationTag,
    OrganizationType,
    Help,
    Semester,
    Comment,
)
from app.utils import random_code_init



__all__ = [
    # utils
    'create_user', 'create_person', 'create_org',
    'create_person_account', 'create_org_account',
    # load functions
    'load_stu', 'load_orgtype', 'load_org',
    'load_help', 
    'load_org_tag', 'load_old_org_tags',
]


def _get_or_create_np(user: User, defaults = None, **kwargs):
    kwargs[SQ.f(NaturalPerson.person_id)] = user
    return NaturalPerson.objects.get_or_create(defaults=defaults, **kwargs)

# local tools
def create_user(id, rand_pw=False, reset_pw=None, **defaults):
    '''create user locally'''
    try:
        stage = 'convert userid'
        id = str(id)
        stage = 'create user'
        user, created = User.objects.get_or_create(
            username=id, defaults=defaults)
        if created or reset_pw is not None:
            stage = 'get password'
            password = reset_pw
            if not isinstance(password, str):
                password = random_code_init(id) if rand_pw else id
            stage = 'set password'
            user.set_password(password)
            user.save()
        return user
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_person(name, user, **defaults):
    '''create naturalperson locally, but why not call `get_or_create`?'''
    try:
        stage = 'get user'
        user = user if isinstance(user, User) else User.objects.get(username=user)
        stage = 'create naturalperson'
        person, created = _get_or_create_np(user, name=name, defaults=defaults)
        return person
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_org(name, user, otype, **defaults):
    '''create organization locally, but why not call `get_or_create`?'''
    try:
        stage = 'get user'
        user = user if isinstance(user, User) else User.objects.get(username=user)
        stage = 'get organization type'
        if not isinstance(otype, OrganizationType):
            if isinstance(otype, int):
                otype = OrganizationType.objects.get(pk=otype)
            elif OrganizationType.objects.filter(otype_name=otype).exists():
                otype = OrganizationType.objects.get(otype_name=otype)
            else:
                otype = OrganizationType.objects.get(otype_name__contains=otype)
        stage = 'create organization'
        org, created = Organization.objects.get_or_create(
            organization_id=user, oname=name, otype=otype, defaults=defaults)
        return org
    except RuntimeError: raise
    except: raise RuntimeError(f'{stage} failed')


def create_person_account(name, pid, rand_pw=False, reset_pw=None, **defaults):
    '''create person user locally'''
    user = create_user(pid, rand_pw=rand_pw, reset_pw=reset_pw)
    person = create_person(name, user, **defaults)
    return person


def create_org_account(name, oid, otype, rand_pw=False, reset_pw=None, **defaults):
    '''create organization user locally'''
    user = create_user(oid, rand_pw=rand_pw, reset_pw=reset_pw)
    org = create_org(name, user, otype, **defaults)
    return org


def get_user_by_name(name):
    """通过 name/oname 获取 user 对象，用于导入评论者
    Comment只接受User对象
    Args:
        name/oname
    Returns:
        user<object>: 用户对象
        user_type: 用户类型
    """
    try: return NaturalPerson.objects.get(name=name).get_user()
    except: pass
    try: return Organization.objects.get(oname=name).get_user()
    except: pass
    print(f"{name} is neither natural person nor organization!")


def try_output(msg: str, output_func: Callable=None, html=True):
    '''
    工具函数，尝试用output_func输出msg的内容，如output_func为None则直接返回msg

    :param msg: 输出内容
    :type msg: str
    :param output_func: 输出函数, defaults to None
    :type output_func: Callable, optional
    :param html: 允许以HTML格式输出，否则将br标签替换为\n, defaults to True
    :type html: bool, optional
    :return: 若有输出函数则不返回，否则返回修改后的消息
    :rtype: str | None
    '''
    if not html:          # 如果不是呈现在html文档，则将<br/>标签换为\n
        msg = msg.replace('<br/>', '\n')

    if output_func is not None:
        output_func(msg)  # output_func不为None，直接用output_func输出msg
        return None
    else:
        return msg        # output_func为None，返回msg的内容


def load_file(filepath: str) -> 'pd.DataFrame':
    '''
    加载表格

    :param filepath: 测试目录下的相对路径，通常为文件名文件名
    :type filepath: str
    :return: 加载出的表格
    :rtype: DataFrame
    '''
    full_path = filepath
    if filepath.endswith('xlsx') or filepath.endswith('xls'):
        return pd.read_excel(f'{full_path}', sheet_name=None)
    if filepath.endswith('csv'):
        return pd.read_csv(f'{full_path}', dtype=object, encoding='utf-8')
    return pd.read_table(f'{full_path}', dtype=object, encoding='utf-8')


def load_orgtype(filepath: str, output_func: Callable=None, html=False, debug=True):
    if debug:
        username = "someone"
        user, _ = User.objects.get_or_create(username=username)
        password = random_code_init(username)
        user.set_password(password)
        user.save()

        Nperson, _ = _get_or_create_np(user)
        Nperson.name = "待定"
        Nperson.save()
    org_type_df = load_file(filepath)
    for _, otype_dict in org_type_df.iterrows():
        type_id = int(otype_dict["otype_id"])
        type_name = otype_dict["otype_name"]
        control_pos_threshold = int(otype_dict.get("control_pos_threshold", 0))
        # type_superior_id = int(otype_dict["otype_superior_id"])
        incharge = otype_dict.get("incharge", "待定")
        orgtype, _ = OrganizationType.objects.get_or_create(otype_id=type_id)
        orgtype.otype_name = type_name
        # orgtype.otype_superior_id = type_superior_id
        try:
            Nperson = NaturalPerson.objects.get(name=incharge)
        except:
            user, _ = User.objects.get_or_create(username=incharge)
            Nperson, _ = _get_or_create_np(user)
        orgtype.incharge = Nperson
        orgtype.job_name_list = otype_dict["job_name_list"]
        orgtype.control_pos_threshold = control_pos_threshold
        orgtype.save()
    return try_output("导入小组类型信息成功！", output_func, html)


def load_org(filepath: str, output_func: Callable=None, html=False):
    org_df = load_file(filepath)
    msg = ''
    for _, org_dict in org_df.iterrows():
        try:
            username = org_dict.get("organization_id", "")
            if not isinstance(username, str):
                # 如果该列存在但行无数据，会得到numpy.nan: float
                username = ""
            password = 'YPPFtest' if DEBUG else random_code_init(username)
            # 现在找不到直接出错
            org_found = True
            if username[:2] == "zz":
                oname = org_dict["oname"]
                type_id = org_dict["otype_id"]
                user, created = User.objects.get_or_create(username=username)
                if created:
                    user.set_password(password)
                    user.save()
                # 组织类型必须已经创建
                orgtype = OrganizationType.objects.get(otype_id=type_id)
                org, created = Organization.objects.get_or_create(
                    organization_id=user, otype=orgtype
                )
                org.oname = oname
                org.save()
                msg += '<br/>成功创建组织：'+oname
            # 否则不会创建用户，只会查找或修改已有的组织
            else:
                # 先尝试以组织名检索
                oname = username
                orgs = Organization.objects.filter(oname=oname)
                if not len(orgs):
                    orgs = Organization.objects.filter(oname__contains=oname)
                oname = org_dict["oname"]
                if len(orgs) == 1:
                    # 如果只有一个，一定是所需的组织，重命名
                    org = orgs.first()
                    origin_oname = org.oname
                    org.oname = oname
                    org.save()
                    msg += f'<br/>重命名组织：{origin_oname}->{oname}'
                else:
                    # 直接读取名称
                    orgs = Organization.objects.filter(oname=oname)
                    if not len(orgs):
                        orgs = Organization.objects.filter(oname__contains=oname)
                    assert len(orgs) == 1, f'未找到组织：{oname}'
                    org = orgs[0]
                    oname = org.oname
                    msg += f'<br/>检索到已存在组织：{oname}'

            if org_found:
                # 必须是本学期的才更新，否则创建
                all_positions = Position.objects.current()
                pos = max(0, int(org_dict.get("pos", 0)))
                pos_display = org.otype.get_name(pos)
                persons = org_dict.get("person", "待定")
                if not isinstance(persons, str):
                    # 如果该列存在但行无数据，会得到numpy.nan: float
                    persons = ""
                for person in persons.split(','):
                    people = NaturalPerson.objects.get(name=person)
                    # 获得其当前的职位
                    get_kws = dict(person=people, org=org)
                    position, created = all_positions.get_or_create(**get_kws)
                    # 更新为可用职位
                    position.status = Position.Status.INSERVICE
                    position.pos = pos
                    position.is_admin = org.otype.default_is_admin(pos)
                    if created:
                        # 书院课程以学期为单位更新
                        position.semester = org.otype.default_semester()
                    position.save()
                    msg += f'<br/>&emsp;&emsp;成功增加{pos_display}：{person}'
        except Exception as e:
            msg += '<br/>未能创建组织'+oname+',原因：'+str(e)
    if CONFIG.yqpoint.org_name:
        username = 'zz00001'
        user, created = User.objects.get_or_create(username=username)
        if created:
            password = random_code_init(username)
            user.set_password(password)
            user.save()
            orgtype, mid = OrganizationType.objects.get_or_create(otype_id=0)
            org, mid = Organization.objects.get_or_create(
                organization_id=user, otype=orgtype
            )
            org.oname = CONFIG.yqpoint.org_name
            org.save()
            msg += '<br/>成功创建元气值发放组织：'+CONFIG.yqpoint.org_name
    return try_output(msg, output_func, html)


def load_stu(filepath: str, output_func: Callable=None, html=False):
    stu_df = load_file(filepath)
    total = 0
    stu_list = []
    exist_list = []
    failed_list = []
    Char2Gender = {"男": NaturalPerson.Gender.MALE, "女": NaturalPerson.Gender.FEMALE}
    username = 'null'
    fail_info = None
    for _, stu_dict in tqdm(stu_df.iterrows()):
        total += 1
        try:
            sid = username = stu_dict["学号"]
            password = username
            name = stu_dict["姓名"]
            gender = Char2Gender[stu_dict["性别"]]
            stu_major = stu_dict["专业"]
            if not stu_major or stu_major == "None":
                stu_major = "元培计划（待定）"
            stu_grade = "20" + sid[:2]
            stu_class = stu_dict["班级"]
            email = stu_dict["邮箱"]
            if not email or email == "None":
                if sid[0] == "2":
                    email = sid + "@stu.pku.edu.cn"
                else:
                    email = sid + "@pku.edu.cn"
            tel = stu_dict["手机号"]
            if not tel or tel == "None":
                tel = None

            user, created = User.objects.get_or_create(username=username)
            if not created:
                exist_list.append(username)
                continue
            # 这一步的PBKDF2加密算法太慢了
            else:
                # 设置密码
                user.set_password(password)
                user.save()

            # 批量导入比循环导入快很多，但可惜由于外键pid的存在，必须先保存user，User模型无法批量导入。
            # 但重点还是 set_password 的加密算法太 TM 的慢了！
            stu_list.append(
                NaturalPerson(
                    **{SQ.f(NaturalPerson.person_id): user},
                    stu_id_dbonly=sid,
                    name=name,
                    gender=gender,
                    stu_major=stu_major,
                    stu_grade=stu_grade,
                    stu_class=stu_class,
                    email=email,
                    telephone=tel,
                )
            )
        except Exception as e:
            fail_info = str(e)
            failed_list.append(username)
            continue
    NaturalPerson.objects.bulk_create(stu_list)

    msg = '<br/>'.join((
                "导入学生信息成功！",
                f"共{total}人，尝试导入{len(stu_list)}人",
                f"已存在{len(exist_list)}人，名单为",
                ','.join(exist_list),
                f"失败{len(failed_list)}人，名单为",
                ','.join(failed_list),
                f'最后一次失败原因为: {fail_info}' if fail_info is not None else '',
                ))
    return try_output(msg, output_func, html)


def load_help(filepath: str, output_func: Callable=None, html=False):
    try:
        help_df = load_file(filepath)
    except:
        return try_output(f"没有找到{filepath},请确认该文件已经在test_data中。", output_func, html)
    for _, help_dict in help_df.iterrows():
        content = help_dict["content"]
        title = help_dict["title"]
        new_help, mid = Help.objects.get_or_create(title=title)
        new_help.content = content
        new_help.save()
    return try_output("成功导入帮助信息！", output_func, html)


def load_org_tag(filepath: str, output_func: Callable=None, html=False):
    try:
        org_tag_def = load_file(filepath)
    except:
        return try_output(f"没有找到{filepath},请确认该文件已经在test_data中。", output_func, html)
    tag_list = []
    for _, tag_dict in org_tag_def.iterrows():
        tag_name = tag_dict["name"]
        tag_color = tag_dict["color"]
        tag_list.append(
            OrganizationTag(
                name=tag_name,
                color=tag_color,
            )
        )
    OrganizationTag.objects.bulk_create(tag_list)
    return try_output("导入组织标签类型信息成功！", output_func, html)


def load_old_org_tags(filepath: str, output_func: Callable=None, html=False):
    try:
        org_tag_def = load_file(filepath)
    except:
        return try_output(f"没有找到{filepath},请确认该文件已经在test_data中。", output_func, html)
    error_dict = {}
    org_num = 0
    for _, tag_dict in org_tag_def.iterrows():
        org_num += 1
        err = False
        with transaction.atomic():
            try:
                useroj = Organization.objects.select_for_update().get(oname=tag_dict[0])
                for tag in tag_dict[1:]:
                    useroj.tags.add(OrganizationTag.objects.get(name=tag))
            except Exception as e:
                if not(type(tag)==float and math.isnan(tag)): # 说明不是因遍历至空单元格导致的异常
                    error_dict[tag_dict[0]] = e
                    err = True
            if not err:  # 只有未出现异常，组织的标签信息才被保存
                useroj.save()
    msg = '<br/>'.join((
            f"共尝试导入{org_num}个组织的标签信息",
            f"导入成功的组织：{org_num - len(error_dict)}个",
            f"导入失败的组织：{len(error_dict)}个",
            f'错误原因：' if error_dict else ''
            ) + tuple(f'{org}：{err}' for org, err in error_dict.items())
            )
    return try_output(msg, output_func, html)


def load_birthday(filepath: str, use_name: bool=False, slash: bool=False):
    '''
    用来从csv中导入用户生日的函数，调用频率很低
    @params:
        filepath: csv文件的路径，e.g. test_data/birthday.csv
        use_name: 使用name来获取对应的NaturalPerson对象。建议在有学号信息且保证没有重名时使用
        slash: 生日的格式。目前支持两种：yyyymmdd(8位数字)、yyyy/m/d(其中m和d位数不固定)，通过slash选择哪一种
               e.g. slash=True时处理后一种
    '''
    from datetime import date
    try:
        csv = pd.read_csv(filepath)
    except:
        print(f"没有找到{filepath},请确认该文件已经在test_data中。")
    csv = csv.iloc[:, [0, 1, 2]]
    success = []
    for i in range(len(csv)):
        stuid, name, birthday = csv.iloc[i]
        print(stuid, name, birthday)
        if not slash:
            birthday = str(birthday.item())
        try:
            if not slash:
                year, month, day = map(int, (birthday[:4], birthday[4:6], birthday[6:]))
            else:
                year, month, day = map(int, birthday.split("/"))
            if not use_name:
                user = User.objects.get(username=str(stuid))
                stu = NaturalPerson.objects.get_by_user(user)
            else:
                stu = NaturalPerson.objects.get(name=name)
            stu.birthday = date(year, month, day)
            stu.save()
            success.append(name)
        except Exception as e:
            print(e)
            pass
    print(len(success))
