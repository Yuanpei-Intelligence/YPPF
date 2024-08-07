from django.core.management.base import BaseCommand
from questionnaire.models import Survey, Question, Choice


# 创建调查问卷
class Command(BaseCommand):
    help = "Create dormitory questionnaire."

    def handle(self, *args, **options):
        # 创建一个survey
        survey = Survey.objects.create(
            title = "宿舍生活习惯调研",
            description = "根据问卷情况对宿舍进行分配",
            status = Survey.Status.PUBLISHED, # 传参
            creator_id = 1, # 传参
            start_time = "2024-08-09", # 传参
            end_time = "2024-08-19", # 传参
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
            topic = "具体意向专业",
            type = Question.Type.TEXT
        )
        question7.save()

        question8 = Question.objects.create(
            survey = survey,
            order = 8,
            topic = "身高",
            type = Question.Type.TEXT,
            description = "单位：cm",
        )
        question8.save()

        question9 = Question.objects.create(
            survey = survey,
            order = 9,
            topic = "体重",
            type = Question.Type.TEXT,
            description = "单位：kg",
        )
        question9.save()

        question10 = Question.objects.create(
            survey = survey,
            order = 10,
            topic = "衣服尺码",
            type = Question.Type.SINGLE,
        )
        question10.save()

        choice10_1 = Choice.objects.create(
            question = question10,
            order = 1,
            text = "S码",
        )
        choice10_1.save()

        choice10_2 = Choice.objects.create(
            question = question10,
            order = 2,
            text = "M码",
        )
        choice10_2.save()

        choice10_3 = Choice.objects.create(
            question = question10,
            order = 3,
            text = "L码",
        )
        choice10_3.save()

        choice10_4 = Choice.objects.create(
            question = question10,
            order = 4,
            text = "XL码",
        )
        choice10_4.save()

        choice10_5 = Choice.objects.create(
            question = question10,
            order = 5,
            text = "XXL码",
        )
        choice10_5.save()

        choice10_6 = Choice.objects.create(
            question = question10,
            order = 6,
            text = "XXXL码",
        )
        choice10_6.save()

        choice10_7 = Choice.objects.create(
            question = question10,
            order = 7,
            text = "XXXXL码",
        )
        choice10_7.save()

        question11 = Question.objects.create(
            survey = survey,
            order = 11,
            topic = "是否愿意和留学生住一起",
            type = Question.Type.SINGLE,
        )
        question11.save()

        choice11_1 = Choice.objects.create(
            question = question11,
            order = 1,
            text = "愿意",
        )
        choice11_1.save()

        choice11_2 = Choice.objects.create(
            question = question11,
            order = 2,
            text = "都可以",
        )
        choice11_2.save()

        choice11_3 = Choice.objects.create(
            question = question11,
            order = 3,
            text = "不愿意",
        )
        choice11_3.save()

        question12 = Question.objects.create(
            survey = survey,
            order = 12,
            topic = "你的睡眠类型",
            type = Question.Type.SINGLE,
        )
        question12.save()

        choice12_1 = Choice.objects.create(
            question = question12,
            order = 1,
            text = "早睡早起“百灵鸟型”",
        )
        choice12_1.save()

        choice12_2 = Choice.objects.create(
            question = question12,
            order = 2,
            text = "晚睡晚起“猫头鹰型”",
        )
        choice12_2.save()

        question13 = Question.objects.create(
            survey = survey,
            order = 13,
            topic = "你预期的大学生活起床时间",
            type = Question.Type.SINGLE,
        )
        question13.save()

        choice13_1 = Choice.objects.create(
            question = question13,
            order = 1,
            text = "7点前",
        )
        choice13_1.save()

        choice13_2 = Choice.objects.create(
            question = question13,
            order = 2,
            text = "7~8点",
        )
        choice13_2.save()

        choice13_3 = Choice.objects.create(
            question = question13,
            order = 3,
            text = "8~9点",
        )
        choice13_3.save()

        choice13_4 = Choice.objects.create(
            question = question13,
            order = 4,
            text = "9-10点",
        )
        choice13_4.save()

        choice13_5 = Choice.objects.create(
            question = question13,
            order = 5,
            text = "10-11点",
        )
        choice13_5.save()

        choice13_6 = Choice.objects.create(
            question = question13,
            order = 6,
            text = "11点后",
        )
        choice13_6.save()

        question14 = Question.objects.create(
            survey = survey,
            order = 14,
            topic = "你预期的大学生活睡觉时间",
            type = Question.Type.SINGLE,
            description = "指能够躺在床上不发出大的声响的时间（指能够躺在床上不发出大的声响的时间）",
        )
        question14.save()

        choice14_1 = Choice.objects.create(
            question = question14,
            order = 1,
            text = "23点前",
        )
        choice14_1.save()

        choice14_2 = Choice.objects.create(
            question = question14,
            order = 2,
            text = "23-24点",
        )
        choice14_2.save()

        choice14_3 = Choice.objects.create(
            question = question14,
            order = 3,
            text = "24-1点",
        )
        choice14_3.save()

        choice14_4 = Choice.objects.create(
            question = question14,
            order = 4,
            text = "1-2点",
        )
        choice14_4.save()

        choice14_5 = Choice.objects.create(
            question = question14,
            order = 5,
            text = "2点后",
        )
        choice14_5.save()

        question15 = Question.objects.create(
            survey = survey,
            order = 15,
            topic = "你的睡眠质量是",
            type = Question.Type.SINGLE,
        )
        question15.save()

        choice15_1 = Choice.objects.create(
            question = question15,
            order = 1,
            text = "浅眠型（易受声、光影响）",
        )
        choice15_1.save()

        choice15_2 = Choice.objects.create(
            question = question15,
            order = 2,
            text = "酣睡型（较少受影响，一觉到天亮）",
        )
        choice15_2.save()

        question16 = Question.objects.create(
            survey = survey,
            order = 16,
            topic = "你是否存在以下睡眠困扰",
            type = Question.Type.MULTIPLE,
        )
        question16.save()

        choice16_1 = Choice.objects.create(
            question = question16,
            order = 1,
            text = "入睡困难",
        )
        choice16_1.save()

        choice16_2 = Choice.objects.create(
            question = question16,
            order = 2,
            text = "入睡后中间易醒",
        )
        choice16_2.save()

        choice16_3 = Choice.objects.create(
            question = question16,
            order = 3,
            text = "醒后难于再入睡",
        )
        choice16_3.save()

        choice16_4 = Choice.objects.create(
            question = question16,
            order = 4,
            text = "鼾声如雷",
        )
        choice16_4.save()

        choice16_5 = Choice.objects.create(
            question = question16,
            order = 5,
            text = "现在/曾经服用过安眠药",
        )
        choice16_5.save()

        choice16_6 = Choice.objects.create(
            question = question16,
            order = 6,
            text = "以上均无",
        )
        choice16_6.save()

        question17 = Question.objects.create(
            survey = survey,
            order = 17,
            topic = "夏天能接受的最低空调温度",
            type = Question.Type.TEXT,
            description = "单位：℃",
        )
        question17.save()

        question18 = Question.objects.create(
            survey = survey,
            order = 18,
            topic = "是否接受夏天整晚开空调",
            type = Question.Type.SINGLE,
        )
        question18.save()

        choice18_1 = Choice.objects.create(
            question = question18,
            order = 1,
            text = "是",
        )
        choice18_1.save()

        choice18_2 = Choice.objects.create(
            question = question18,
            order = 2,
            text = "否",
        )
        choice18_2.save()

        question19 = Question.objects.create(
            survey = survey,
            order = 19,
            topic = "你的性格",
            type = Question.Type.SINGLE,
        )
        question19.save()

        choice19_1 = Choice.objects.create(
            question = question19,
            order = 1,
            text = "内向型（独处时精力充沛；更封闭，更愿意在经挑选的小群体中分享个人的情况；不把兴奋说出来。）",
        )
        choice19_1.save()

        choice19_2 = Choice.objects.create(
            question = question19,
            order = 2,
            text = "适中型（介于二者之间，能够在内外向之间切换，在人群中乐意与人交谈结交朋友，同时也享受独处。）",
        )
        choice19_2.save()

        choice19_3 = Choice.objects.create(
            question = question19,
            order = 3,
            text = "外向型（与他人相处时精力充沛；易于“读”和了解，随意地分享个人情况；高度热情地社交。）",
        )
        choice19_3.save()

        question20 = Question.objects.create(
            survey = survey,
            order = 20,
            topic = "你希望室友的性格",
            type = Question.Type.SINGLE,
        )
        question20.save()

        choice20_1 = Choice.objects.create(
            question = question20,
            order = 1,
            text = "内向型",
        )
        choice20_1.save()

        choice20_2 = Choice.objects.create(
            question = question20,
            order = 2,
            text = "适中型",
        )
        choice20_2.save()

        choice20_3 = Choice.objects.create(
            question = question20,
            order = 3,
            text = "外向型",
        )
        choice20_3.save()

        question21 = Question.objects.create(
            survey = survey,
            order = 21,
            topic = "你希望你的宿舍环境是",
            type = Question.Type.SINGLE,
        )
        question21.save()

        choice21_1 = Choice.objects.create(
            question = question21,
            order = 1,
            text = "整洁条理",
        )
        choice21_1.save()

        choice21_2 = Choice.objects.create(
            question = question21,
            order = 2,
            text = "随性就好",
        )
        choice21_2.save()

        question22 = Question.objects.create(
            survey = survey,
            order = 22,
            topic = "你对于室友的期待是",
            type = Question.Type.SINGLE,
        )
        question22.save()

        choice22_1 = Choice.objects.create(
            question = question22,
            order = 1,
            text = "专注学习",
        )
        choice22_1.save()

        choice22_2 = Choice.objects.create(
            question = question22,
            order = 2,
            text = "全面发展",
        )
        choice22_2.save()

        question23 = Question.objects.create(
            survey = survey,
            order = 23,
            topic = "你本人更希望大学生活是",
            type = Question.Type.SINGLE,
        )
        question23.save()

        choice23_1 = Choice.objects.create(
            question = question23,
            order = 1,
            text = "专注学习",
        )
        choice23_1.save()

        choice23_2 = Choice.objects.create(
            question = question23,
            order = 2,
            text = "全面发展",
        )
        choice23_2.save()

        question24 = Question.objects.create(
            survey = survey,
            order = 24,
            topic = "你希望在一天结束后与室友进行学业或成长思考上的交流吗",
            type = Question.Type.SINGLE,
        )
        question24.save()

        choice24_1 = Choice.objects.create(
            question = question24,
            order = 1,
            text = "希望",
        )
        choice24_1.save()

        choice24_2 = Choice.objects.create(
            question = question24,
            order = 2,
            text = "不希望",
        )
        choice24_2.save()

        question25 = Question.objects.create(
            survey = survey,
            order = 25,
            topic = "你每周与家人通话累计时长",
            type = Question.Type.SINGLE,
        )
        question25.save()

        choice25_1 = Choice.objects.create(
            question = question25,
            order = 1,
            text = "低于1h",
        )
        choice25_1.save()

        choice25_2 = Choice.objects.create(
            question = question25,
            order = 2,
            text = "约1~3h",
        )
        choice25_2.save()

        choice25_3 = Choice.objects.create(
            question = question25,
            order = 3,
            text = "约3~6h",
        )
        choice25_3.save()

        choice25_4 = Choice.objects.create(
            question = question25,
            order = 4,
            text = "约6~10h",
        )
        choice25_4.save()

        choice25_5 = Choice.objects.create(
            question = question25,
            order = 5,
            text = "大于10h",
        )
        choice25_5.save()

        question26 = Question.objects.create(
            survey = survey,
            order = 26,
            topic = "是否愿意担任宿舍长，担任活跃宿舍氛围、架构沟通桥梁的作用",
            type = Question.Type.SINGLE,
        )
        question26.save()

        choice26_1 = Choice.objects.create(
            question = question26,
            order = 1,
            text = "愿意",
        )
        choice26_1.save()

        choice26_2 = Choice.objects.create(
            question = question26,
            order = 2,
            text = "不愿意",
        )
        choice26_2.save()

        question27 = Question.objects.create(
            survey = survey,
            order = 27,
            topic = "是否愿意担任班干部？",
            type = Question.Type.SINGLE,
        )
        question27.save()

        choice27_1 = Choice.objects.create(
            question = question27,
            order = 1,
            text = "愿意",
        )
        choice27_1.save()

        choice27_2 = Choice.objects.create(
            question = question27,
            order = 2,
            text = "不愿意",
        )
        choice27_2.save()

        question28 = Question.objects.create(
            survey = survey,
            order = 28,
            topic = "如愿意，愿意担任以下哪项职务",
            type = Question.Type.MULTIPLE,
            required = False
        )
        question28.save()

        choice28_1 = Choice.objects.create(
            question = question28,
            order = 1,
            text = "班长",
        )
        choice28_1.save()

        choice28_2 = Choice.objects.create(
            question = question28,
            order = 2,
            text = "团支书",
        )
        choice28_2.save()

        choice28_3 = Choice.objects.create(
            question = question28,
            order = 3,
            text = "组织委员",
        )
        choice28_3.save()

        choice28_4 = Choice.objects.create(
            question = question28,
            order = 4,
            text = "学习委员",
        )
        choice28_4.save()

        choice28_5 = Choice.objects.create(
            question = question28,
            order = 5,
            text = "心理委员",
        )
        choice28_5.save()

        choice28_6 = Choice.objects.create(
            question = question28,
            order = 6,
            text = "宣传委员",
        )
        choice28_6.save()

        choice28_7 = Choice.objects.create(
            question = question28,
            order = 7,
            text = "体育委员",
        )
        choice28_7.save()

        question29 = Question.objects.create(
            survey = survey,
            order = 29,
            topic = "如愿意，可否填写竞选理由或优势?如果可以，请填写在下方。",
            type = Question.Type.TEXT,
            required = False
        )
        question29.save()

        question30 = Question.objects.create(
            survey = survey,
            order = 30,
            topic = "是否愿意担任班级联络人？",
            type = Question.Type.SINGLE,
        )
        question30.save()

        choice30_1 = Choice.objects.create(
            question = question30,
            order = 1,
            text = "是",
        )
        choice30_1.save()

        choice30_2 = Choice.objects.create(
            question = question30,
            order = 2,
            text = "否",
        )
        choice30_2.save()

        question31 = Question.objects.create(
            survey = survey,
            order = 31,
            topic = "你希望宿舍的氛围：",
            type = Question.Type.TEXT,
            required = False
        )
        question31.save()

        question32 = Question.objects.create(
            survey = survey,
            order = 32,
            topic = "你的兴趣/特长/爱好（例如乐器、剪辑、运动、唱歌跳舞等）",
            type = Question.Type.TEXT,
            required = False
        )
        question32.save()

        question33 = Question.objects.create(
            survey = survey,
            order = 33,
            topic = "你对于大学生活的期待：",
            type = Question.Type.TEXT,
            required = False
        )
        question33.save()
