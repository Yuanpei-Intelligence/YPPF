"""
初始化 AchievementType Achievement
假定achievement_type都存在
"""
from django.core.management.base import BaseCommand
from achievement.models import AchievementType, Achievement


class Command(BaseCommand):
    help = "init AchievementType Achievement"

    def handle(self, *args, **options):
        DISPLAYED = True
        HIDDEN = False
        AUTO = True
        MANUAL = False
        achievement_info = [('元气人生',
                             [('完成游园会印章收集任务', 3, DISPLAYED, MANUAL),
                              ('集齐游园会全部印章', 10, HIDDEN, MANUAL),
                                 ('开始大学第二年', 5, DISPLAYED, AUTO),
                                 ('开始大学第三年', 5, DISPLAYED, AUTO),
                                 ('开始大学第四年', 5, DISPLAYED, AUTO),
                                 ('开始大学第五年', 5, HIDDEN, AUTO),
                                 ('开始大学第六年', 5, HIDDEN, AUTO),
                                 ('完成军训', 1, DISPLAYED, AUTO),
                                 ('完成书院实践育人活动', 3, DISPLAYED, MANUAL),
                                 ('参与书院嘉年华', 2, DISPLAYED, MANUAL),
                                 ('本科顺利毕业', 35, DISPLAYED, AUTO)]),
                            ('洁身自好',
                             [('月度卫生检查通过', 1, DISPLAYED, MANUAL),
                              ('一学期月度卫生检查均获得“优秀”评价', 10, HIDDEN, AUTO),
                                 ('一学年月度卫生检查均获得“优秀”评价', 15, HIDDEN, AUTO),
                                 ('本科月度卫生检查均获得“优秀”评价', 50, HIDDEN, AUTO)]),
                            ('五育并举',
                             [('首次报名书院课程', 1, DISPLAYED, AUTO),
                              ('完成德育学分要求', 2, DISPLAYED, AUTO),
                                 ('完成智育学分要求', 2, DISPLAYED, AUTO),
                                 ('完成体育学分要求', 2, DISPLAYED, AUTO),
                                 ('完成美育学分要求', 2, DISPLAYED, AUTO),
                                 ('完成劳动教育学分要求', 2, DISPLAYED, AUTO),
                                 ('完成一半书院学分要求', 4, DISPLAYED, AUTO),
                                 ('完成全部书院学分要求', 5, DISPLAYED, AUTO),
                                 ('超额完成一半书院学分要求', 7, HIDDEN, AUTO),
                                 ('超额完成一倍书院学分要求', 10, HIDDEN, AUTO)]),
                            ('志同道合',
                             [('加入书院组织', 1, DISPLAYED, AUTO),
                              ('参与书院俱乐部一半活动', 2, HIDDEN, AUTO),
                                 ('参与书院俱乐部全部活动', 5, HIDDEN, AUTO),
                                 ('成为书院小组负责人', 10, HIDDEN, AUTO),
                                 ('成为书院俱乐部负责人', 10, HIDDEN, AUTO),
                                 ('成为书院星级俱乐部负责人', 20, HIDDEN, AUTO),
                                 ('发起成立书院小组', 5, HIDDEN, AUTO)]),
                            ('严于律己',
                             [('当月没有扣除信用分', 0, DISPLAYED, AUTO),
                              ('一学期没有扣除信用分', 2, HIDDEN, AUTO),
                                 ('一学年没有扣除信用分', 10, HIDDEN, AUTO),
                                 ('本科均没有扣除信用分', 20, HIDDEN, AUTO)]),
                            ('元气满满',
                             [('首次获得元气值', 0, DISPLAYED, AUTO),
                              ('学期内获得10元气值', 0, DISPLAYED, AUTO),
                                 ('学期内获得30元气值', 0, HIDDEN, AUTO),
                                 ('学期内获得50元气值', 0, HIDDEN, AUTO),
                                 ('学期内获得100元气值', 0, HIDDEN, AUTO),
                                 ('首次消费元气值', 1, DISPLAYED, AUTO),
                                 ('学期内消费10元气值', 1, DISPLAYED, AUTO),
                                 ('学期内消费30元气值', 2, HIDDEN, AUTO),
                                 ('学期内消费50元气值', 5, HIDDEN, AUTO),
                                 ('学期内消费100元气值', 10, HIDDEN, AUTO)]),
                            ('三五成群',
                             [('加入宿舍群', 1, DISPLAYED, MANUAL),
                              ('参与宿舍片区管理', 0, DISPLAYED, MANUAL),
                                 ('参与宿舍片区活动', 0, DISPLAYED, MANUAL)]),
                            ('智慧生活',
                             [('注册智慧书院', 2, DISPLAYED, AUTO),
                              ('连续登录一周', 0, HIDDEN, AUTO),
                                 ('连续登录一学期', 20, HIDDEN, AUTO),
                                 ('连续登录一整年', 50, HIDDEN, AUTO),
                                 ('完成地下室预约', 1, DISPLAYED, AUTO),
                                 ('更新一次个人档案', 2, DISPLAYED, AUTO),
                                 ('编辑自己的学术地图', 10, DISPLAYED, AUTO),
                                 ('参与学术问答', 5, DISPLAYED, AUTO),
                                 ('使用一次反馈中心', 2, DISPLAYED, AUTO),
                                 ('使用一次元培书房查询', 2, DISPLAYED, AUTO)]),
                            ('纪念成就',
                             [('参与9月5日的团学联宣讲会', 0, DISPLAYED, MANUAL)]),]
        for achievement_type_name, achievement_list in achievement_info:
            try:
                achievement_type = AchievementType.objects.get(
                    title=achievement_type_name)
                for achievement_name, reward_points, if_displayed, if_auto_trigger in achievement_list:
                    Achievement.objects.update_or_create(
                        name=achievement_name,
                        description=achievement_name,  # 默认重复一遍name
                        achievement_type=achievement_type,
                        hidden=not if_displayed,
                        auto_trigger=if_auto_trigger,
                        reward_points=reward_points
                    )
            except AchievementType.DoesNotExist:
                print('AchievementType %s does not exist' %
                      achievement_type_name)
                continue
