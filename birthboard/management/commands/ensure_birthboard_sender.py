"""幂等创建 birthboard 官方发送组织账号（站内信/企业微信通知的发件人）。

发件人账号与组织名由 birthboard config 决定：
    config.birthboard.sender_username（默认 yppf_birthboard）
    config.birthboard.sender_name（默认 生日灯牌）
改 config.json 后重新运行本命令即可切换/补齐账号。

用法：
    python manage.py ensure_birthboard_sender
"""
from django.core.management.base import BaseCommand

from generic.models import User
from app.models import Organization, OrganizationType

from birthboard.config import CONFIG


class Command(BaseCommand):
    help = 'Ensure the birthboard official sender org account exists (config-driven).'

    def handle(self, *args, **options):
        username = CONFIG.sender_username
        name = CONFIG.sender_name
        if not username or not name:
            self.stderr.write(self.style.ERROR(
                'birthboard.sender_username / sender_name 未配置，无法创建发送账号。'))
            return

        # 1) 确保账号（User，Organization 类型）存在
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User.objects.create_user(
                username=username,
                name=name,
                usertype=User.Type.ORG,
                active=True,
                is_active=True,
                is_newuser=False,
            )
            self.stdout.write(self.style.SUCCESS(
                f'创建发送账号：{username}（{name}）'))
        else:
            updates = {}
            if user.name != name:
                updates['name'] = name
            if user.utype != User.Type.ORG:
                updates['utype'] = User.Type.ORG
            if not user.active:
                updates['active'] = True
            if not user.is_active:
                updates['is_active'] = True
            if user.is_newuser:
                updates['is_newuser'] = False
            if updates:
                User.objects.filter(pk=user.pk).update(**updates)
                self.stdout.write(self.style.WARNING(
                    f'更新发送账号字段：{", ".join(sorted(updates))}'))

        # 2) 确保账号对应的组织资料（Organization 一对一）存在
        org = Organization.objects.filter(organization_id=user).first()
        if org is not None:
            if org.oname != name:
                self.stdout.write(self.style.WARNING(
                    f'组织资料已存在（oname={org.oname}），与 sender_name={name!r} 不一致，'
                    '未自动改名，请按需在 admin 调整。'))
            return
        # 组织名唯一，先检查是否被其它账号占用
        org_by_name = Organization.objects.filter(oname=name).first()
        if org_by_name is not None:
            self.stderr.write(self.style.ERROR(
                f'组织名 {name!r} 已被其他账号（{org_by_name.organization_id.username}）'
                '占用，请调整 birthboard.sender_name。'))
            return
        otype = OrganizationType.objects.order_by('otype_id').first()
        if otype is None:
            self.stderr.write(self.style.ERROR(
                '数据库中不存在 OrganizationType，无法为发送账号创建组织资料。'))
            return
        Organization.objects.create(
            organization_id=user,
            oname=name,
            otype=otype,
        )
        self.stdout.write(self.style.SUCCESS(
            f'创建组织资料：{name}（账号 {username}）'))
