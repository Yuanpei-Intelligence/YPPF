from django.core.management.base import BaseCommand
from questionnaire.models import Survey, Question, Choice


# 创建调查问卷
# 信息 1.姓名 2.性别 3.学号 4.生源地 5.生源高中 6.专业 7.身高 8.体重 9.是否愿意和留学生住一起
# 10.起床时间 11.入睡时间 12.夏天空调温度 13.是否整夜空调 14.是否在宿舍吃外卖 15.是否接受舍友在宿舍吃外卖 16.舍友在宿舍时，会在宿舍打电话吗 17.接受舍友在宿舍打电话吗
# 18.性格偏向 19.希望的宿舍氛围 20.对大学生活的期待
class Command(BaseCommand):
    help = "Create dormitory questionnaire."

    def handle(self, *args, **options):
        # 创建一个survey
        survey = Survey.objects.create(
            title = "宿舍生活习惯调研",
            description = "根据问卷情况对宿舍进行分配",
            status = Survey.Status.PUBLISHED, # 传参
            creator_id = 1, # 传参
            start_time = "2023-08-09", # 传参
            end_time = "2023-08-19", # 传参
        )
        survey.save()

        # 创建问题
        question1 = Question.objects.create(
            survey = survey,
            order = 1,
            topic = "姓名",
            type = Question.Type.TEXT,
        )
        question1.save()

        question2 = Question.objects.create(
            survey = survey,
            order = 2,
            topic = "性别",
            type = Question.Type.SINGLE,
        )
        question2.save()

        choice2_1 = Choice.objects.create(
            question = question2,
            order = 1,
            text = "男",
        )
        choice2_1.save()

        choice2_2 = Choice.objects.create(
            question = question2,
            order = 2,
            text = "女",
        )
        choice2_2.save()

        question3 = Question.objects.create(
            survey = survey,
            order = 3,
            topic = "学号",
            type = Question.Type.TEXT,
        )
        question3.save()

        question4 = Question.objects.create(
            survey = survey,
            order = 4,
            topic = "生源地",
            type = Question.Type.TEXT,
            description = "如：山东济南",
        )
        question4.save()

        question5 = Question.objects.create(
            survey = survey,
            order = 5,
            topic = "生源高中",
            type = Question.Type.TEXT,
            description = "请写全称",
        )
        question5.save()

        question6 = Question.objects.create(
            survey = survey,
            order = 6,
            topic = "专业意向",
            type = Question.Type.SINGLE,
        )
        question6.save()

        choice6_1 = Choice.objects.create(
            question = question6,
            order = 1,
            text = "文科类",
        )
        choice6_1.save()

        choice6_2 = Choice.objects.create(
            question = question6,
            order = 2,
            text = "理工类",
        )
        choice6_2.save()

        question7 = Question.objects.create(
            survey = survey,
            order = 7,
            topic = "身高",
            type = Question.Type.TEXT,
            description = "单位：cm",
        )
        question7.save()

        question8 = Question.objects.create(
            survey = survey,
            order = 8,
            topic = "体重",
            type = Question.Type.TEXT,
            description = "单位：kg",
        )
        question8.save()

        question9 = Question.objects.create(
            survey = survey,
            order = 9,
            topic = "是否愿意和留学生住一起",
            type = Question.Type.SINGLE,
        )
        question9.save()

        choice9_1 = Choice.objects.create(
            question = question9,
            order = 1,
            text = "愿意",
        )
        choice9_1.save()

        choice9_2 = Choice.objects.create(
            question = question9,
            order = 2,
            text = "都可以",
        )
        choice9_2.save()

        choice9_3 = Choice.objects.create(
            question = question9,
            order = 3,
            text = "不愿意",
        )   
        choice9_3.save()

        question10 = Question.objects.create(
            survey = survey,
            order = 10,
            topic = "起床时间",
            type = Question.Type.TEXT,
            description = "24小时制，如：7:30", # 如何统一一下格式
        )
        question10.save()

        question11 = Question.objects.create(
            survey = survey,
            order = 11,
            topic = "入睡时间",
            type = Question.Type.TEXT,
            description = "24小时制，如：23:30",
        )
        question11.save()

        question12 = Question.objects.create(
            survey = survey,
            order = 12,
            topic = "夏天空调温度",
            type = Question.Type.TEXT,
            description = "单位：℃",
        )
        question12.save()

        question13 = Question.objects.create(
            survey = survey,
            order = 13,
            topic = "是否整夜开空调",
            type = Question.Type.SINGLE,
        )
        question13.save()

        choice13_1 = Choice.objects.create(
            question = question13,
            order = 1,
            text = "是",
        )
        choice13_1.save()

        choice13_2 = Choice.objects.create(
            question = question13,
            order = 2,
            text = "否",
        )   
        choice13_2.save()

        question14 = Question.objects.create(
            survey = survey,
            order = 14,
            topic = "是否在宿舍吃外卖",
            type = Question.Type.SINGLE,
        )
        question14.save()

        choice14_1 = Choice.objects.create(
            question = question14,
            order = 1,
            text = "是",
        )   
        choice14_1.save()

        choice14_2 = Choice.objects.create(
            question = question14,
            order = 2,
            text = "否",
        )
        choice14_2.save()

        question15 = Question.objects.create(
            survey = survey,
            order = 15,
            topic = "是否接受舍友在宿舍吃外卖",
            type = Question.Type.SINGLE,
        )
        question15.save()

        choice15_1 = Choice.objects.create(
            question = question15,
            order = 1,
            text = "是",
        )
        choice15_1.save()

        choice15_2 = Choice.objects.create(
            question = question15,
            order = 2,
            text = "否",
        )   
        choice15_2.save()

        question16 = Question.objects.create(
            survey = survey,
            order = 16,
            topic = "舍友在宿舍时，是否会在宿舍视频/电话",
            type = Question.Type.SINGLE,
        )
        question16.save()

        choice16_1 = Choice.objects.create(
            question = question16,
            order = 1,
            text = "是",
        )
        choice16_1.save()

        choice16_2 = Choice.objects.create(
            question = question16,
            order = 2,
            text = "否",
        )
        choice16_2.save()

        question17 = Question.objects.create(
            survey = survey,
            order = 17,
            topic = "是否接受舍友在宿舍视频/电话",
            type = Question.Type.SINGLE,
        )
        question17.save()

        choice17_1 = Choice.objects.create(
            question = question17,
            order = 1,
            text = "是",
        )
        choice17_1.save()

        choice17_2 = Choice.objects.create(
            question = question17,
            order = 2,
            text = "否",
        )
        choice17_2.save()

        question18 = Question.objects.create(
            survey = survey,
            order = 18,
            topic = "性格偏向",
            type = Question.Type.SINGLE,
        )
        question18.save()

        choice18_1 = Choice.objects.create(
            question = question18,
            order = 1,
            text = "外向型",
        )   
        choice18_1.save()

        choice18_2 = Choice.objects.create(
            question = question18,
            order = 2,
            text = "内向型",
        )
        choice18_2.save()

        choice18_3 = Choice.objects.create(
            question = question18,
            order = 3,
            text = "适中型",
        )
        choice18_3.save()

        question19 = Question.objects.create(
            survey = survey,
            order = 19,
            topic = "希望的宿舍氛围",
            type = Question.Type.TEXT,
        )
        question19.save()

        question20 = Question.objects.create(
            survey = survey,
            order = 20,
            topic = "对大学生活的期待",
            type = Question.Type.TEXT,
        )
        question20.save()
