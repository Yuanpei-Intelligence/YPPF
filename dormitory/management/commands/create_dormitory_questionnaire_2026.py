from django.core.management.base import BaseCommand
from django.db import transaction
from questionnaire.models import Survey, Question, Choice


# 创建调查问卷
class Command(BaseCommand):
    help = "Create dormitory questionnaire."

    @transaction.atomic
    def handle(self, *args, **options):
        # 检查是否已存在同名问卷，避免重复创建
        if Survey.objects.filter(title="宿舍生活习惯调研-2026").exists():
            self.stdout.write(self.style.WARNING(
                "问卷「宿舍生活习惯调研-2026」已存在，跳过创建。"
            ))
            return

        # 创建一个survey
        survey = Survey.objects.create(
            title="宿舍生活习惯调研-2026",
            description="根据问卷情况对宿舍进行分配",
            status=Survey.Status.PUBLISHED,
            creator_id=1,
            start_time="2026-08-08",
            end_time="2026-08-14",
        )
        survey.save()

        # ========== 一、基本信息 ==========

        question1 = Question.objects.create(
            survey=survey,
            order=1,
            topic="姓名",
            type=Question.Type.TEXT,
        )
        question1.save()

        question2 = Question.objects.create(
            survey=survey,
            order=2,
            topic="性别",
            type=Question.Type.SINGLE,
        )
        question2.save()

        choice2_1 = Choice.objects.create(
            question=question2,
            order=1,
            text="男",
        )
        choice2_1.save()

        choice2_2 = Choice.objects.create(
            question=question2,
            order=2,
            text="女",
        )
        choice2_2.save()

        question3 = Question.objects.create(
            survey=survey,
            order=3,
            topic="学号",
            type=Question.Type.TEXT,
        )
        question3.save()

        question4 = Question.objects.create(
            survey=survey,
            order=4,
            topic="生源地",
            type=Question.Type.TEXT,
            description="如：山东济南",
        )
        question4.save()

        question5 = Question.objects.create(
            survey=survey,
            order=5,
            topic="生源高中",
            type=Question.Type.TEXT,
            description="请写全称",
        )
        question5.save()

        question6 = Question.objects.create(
            survey=survey,
            order=6,
            topic="意向专业大类",
            type=Question.Type.SINGLE,
        )
        question6.save()

        choice6_1 = Choice.objects.create(
            question=question6,
            order=1,
            text="数理（数学、物理等）",
        )
        choice6_1.save()

        choice6_2 = Choice.objects.create(
            question=question6,
            order=2,
            text="生化（化学、生物、整合科学等）",
        )
        choice6_2.save()

        choice6_3 = Choice.objects.create(
            question=question6,
            order=3,
            text="信工（人工智能、信息科学技术、工学各专业、数据科学等）",
        )
        choice6_3.save()

        choice6_4 = Choice.objects.create(
            question=question6,
            order=4,
            text="文科（人文、社科、经管）",
        )
        choice6_4.save()

        choice6_5 = Choice.objects.create(
            question=question6,
            order=5,
            text="待定",
        )
        choice6_5.save()

        question7 = Question.objects.create(
            survey=survey,
            order=7,
            topic="具体意向专业",
            type=Question.Type.TEXT,
        )
        question7.save()

        question8 = Question.objects.create(
            survey=survey,
            order=8,
            topic="你希望宿舍成员的专业构成是",
            type=Question.Type.SINGLE,
        )
        question8.save()

        choice8_1 = Choice.objects.create(
            question=question8,
            order=1,
            text="与我专业意向相同或相近（便于学业交流）",
        )
        choice8_1.save()

        choice8_2 = Choice.objects.create(
            question=question8,
            order=2,
            text="跨学科混合（接触不同专业背景同学）",
        )
        choice8_2.save()

        choice8_3 = Choice.objects.create(
            question=question8,
            order=3,
            text="都可以",
        )
        choice8_3.save()

        question9 = Question.objects.create(
            survey=survey,
            order=9,
            topic="身高",
            type=Question.Type.TEXT,
            description="单位：cm",
        )
        question9.save()

        question10 = Question.objects.create(
            survey=survey,
            order=10,
            topic="体重",
            type=Question.Type.TEXT,
            description="单位：kg",
        )
        question10.save()

        question11 = Question.objects.create(
            survey=survey,
            order=11,
            topic="衣服尺码",
            type=Question.Type.SINGLE,
        )
        question11.save()

        choice11_1 = Choice.objects.create(
            question=question11, order=1, text="S码")
        choice11_1.save()
        choice11_2 = Choice.objects.create(
            question=question11, order=2, text="M码")
        choice11_2.save()
        choice11_3 = Choice.objects.create(
            question=question11, order=3, text="L码")
        choice11_3.save()
        choice11_4 = Choice.objects.create(
            question=question11, order=4, text="XL码")
        choice11_4.save()
        choice11_5 = Choice.objects.create(
            question=question11, order=5, text="XXL码")
        choice11_5.save()
        choice11_6 = Choice.objects.create(
            question=question11, order=6, text="XXXL码")
        choice11_6.save()
        choice11_7 = Choice.objects.create(
            question=question11, order=7, text="XXXXL码")
        choice11_7.save()

        question12 = Question.objects.create(
            survey=survey,
            order=12,
            topic="是否愿意与留学生住一个宿舍",
            type=Question.Type.SINGLE,
            description="都在元培35号宿舍楼居住，即你是否愿意舍友中有留学生同学？",
        )
        question12.save()

        choice12_1 = Choice.objects.create(
            question=question12,
            order=1,
            text="愿意",
        )
        choice12_1.save()

        choice12_2 = Choice.objects.create(
            question=question12,
            order=2,
            text="都可以",
        )
        choice12_2.save()

        choice12_3 = Choice.objects.create(
            question=question12,
            order=3,
            text="不愿意",
        )
        choice12_3.save()

        question13 = Question.objects.create(
            survey=survey,
            order=13,
            topic="你的兴趣/特长/爱好",
            type=Question.Type.TEXT,
            description="例如乐器、剪辑、运动、唱歌跳舞等",
            required=False,
        )
        question13.save()

        question14 = Question.objects.create(
            survey=survey,
            order=14,
            topic="你想参加哪些类型的社团",
            type=Question.Type.MULTIPLE,
            required=False,
        )
        question14.save()

        choice14_1 = Choice.objects.create(
            question=question14, order=1, text="体育运动队")
        choice14_1.save()
        choice14_2 = Choice.objects.create(
            question=question14, order=2, text="音乐类社团（如元声合唱团）")
        choice14_2.save()
        choice14_3 = Choice.objects.create(
            question=question14, order=3, text="美术类社团")
        choice14_3.save()
        choice14_4 = Choice.objects.create(
            question=question14, order=4, text="文学类社团")
        choice14_4.save()
        choice14_5 = Choice.objects.create(
            question=question14, order=5, text="志愿服务社团（如爱心社）")
        choice14_5.save()
        choice14_6 = Choice.objects.create(
            question=question14, order=6, text="思维类社团")
        choice14_6.save()
        choice14_7 = Choice.objects.create(
            question=question14, order=7, text="天文类社团")
        choice14_7.save()
        choice14_8 = Choice.objects.create(
            question=question14, order=8, text="地域文化类社团")
        choice14_8.save()
        choice14_9 = Choice.objects.create(
            question=question14, order=9, text="生活技能类社团")
        choice14_9.save()
        choice14_10 = Choice.objects.create(
            question=question14, order=10, text="其他")
        choice14_10.save()
        choice14_11 = Choice.objects.create(
            question=question14, order=11, text="暂无参加意愿")
        choice14_11.save()

        # ========== 二、宿舍环境：睡眠作息&空调温度 ==========

        question15 = Question.objects.create(
            survey=survey,
            order=15,
            topic="你的睡眠类型",
            type=Question.Type.SINGLE,
        )
        question15.save()

        choice15_1 = Choice.objects.create(
            question=question15,
            order=1,
            text='早睡早起\u201c百灵鸟型\u201d',
        )
        choice15_1.save()

        choice15_2 = Choice.objects.create(
            question=question15,
            order=2,
            text='晚睡晚起\u201c猫头鹰型\u201d',
        )
        choice15_2.save()

        question16 = Question.objects.create(
            survey=survey,
            order=16,
            topic="你预期的大学生活起床时间",
            type=Question.Type.SINGLE,
        )
        question16.save()

        choice16_1 = Choice.objects.create(
            question=question16, order=1, text="7点前")
        choice16_1.save()
        choice16_2 = Choice.objects.create(
            question=question16, order=2, text="7-8点")
        choice16_2.save()
        choice16_3 = Choice.objects.create(
            question=question16, order=3, text="8-9点")
        choice16_3.save()
        choice16_4 = Choice.objects.create(
            question=question16, order=4, text="9-10点")
        choice16_4.save()
        choice16_5 = Choice.objects.create(
            question=question16, order=5, text="10-11点")
        choice16_5.save()
        choice16_6 = Choice.objects.create(
            question=question16, order=6, text="11点后")
        choice16_6.save()

        question17 = Question.objects.create(
            survey=survey,
            order=17,
            topic="你预期的大学生活睡觉时间",
            type=Question.Type.SINGLE,
            description="指能够躺在床上不发出大的声响的时间",
        )
        question17.save()

        choice17_1 = Choice.objects.create(
            question=question17, order=1, text="23点前")
        choice17_1.save()
        choice17_2 = Choice.objects.create(
            question=question17, order=2, text="23-24点")
        choice17_2.save()
        choice17_3 = Choice.objects.create(
            question=question17, order=3, text="24-1点")
        choice17_3.save()
        choice17_4 = Choice.objects.create(
            question=question17, order=4, text="1-2点")
        choice17_4.save()
        choice17_5 = Choice.objects.create(
            question=question17, order=5, text="2点后")
        choice17_5.save()

        question18 = Question.objects.create(
            survey=survey,
            order=18,
            topic="你的睡眠质量是",
            type=Question.Type.SINGLE,
        )
        question18.save()

        choice18_1 = Choice.objects.create(
            question=question18,
            order=1,
            text="浅眠型（易受声、光影响）",
        )
        choice18_1.save()

        choice18_2 = Choice.objects.create(
            question=question18,
            order=2,
            text="酣睡型（较少受影响，一觉到天亮）",
        )
        choice18_2.save()

        question19 = Question.objects.create(
            survey=survey,
            order=19,
            topic="你是否存在以下睡眠困扰",
            type=Question.Type.MULTIPLE,
        )
        question19.save()

        choice19_1 = Choice.objects.create(
            question=question19, order=1, text="入睡困难")
        choice19_1.save()
        choice19_2 = Choice.objects.create(
            question=question19, order=2, text="入睡后中间易醒")
        choice19_2.save()
        choice19_3 = Choice.objects.create(
            question=question19, order=3, text="醒后难于再入睡")
        choice19_3.save()
        choice19_4 = Choice.objects.create(
            question=question19, order=4, text="现在/曾经服用过安眠药")
        choice19_4.save()
        choice19_5 = Choice.objects.create(
            question=question19, order=5, text="以上均无")
        choice19_5.save()

        question20 = Question.objects.create(
            survey=survey,
            order=20,
            topic="夏天能接受的最低空调温度",
            type=Question.Type.TEXT,
            description="单位：℃",
        )
        question20.save()

        question21 = Question.objects.create(
            survey=survey,
            order=21,
            topic="冬天供暖时是否接受人在室内时开窗通风",
            type=Question.Type.SINGLE,
        )
        question21.save()

        choice21_1 = Choice.objects.create(
            question=question21, order=1, text="是")
        choice21_1.save()
        choice21_2 = Choice.objects.create(
            question=question21, order=2, text="否")
        choice21_2.save()

        question22 = Question.objects.create(
            survey=survey,
            order=22,
            topic="是否接受夏天整晚开空调",
            type=Question.Type.SINGLE,
        )
        question22.save()

        choice22_1 = Choice.objects.create(
            question=question22, order=1, text="是")
        choice22_1.save()
        choice22_2 = Choice.objects.create(
            question=question22, order=2, text="否")
        choice22_2.save()

        question23 = Question.objects.create(
            survey=survey,
            order=23,
            topic="你希望你的宿舍环境是",
            type=Question.Type.SINGLE,
        )
        question23.save()

        choice23_1 = Choice.objects.create(
            question=question23, order=1, text="整洁条理")
        choice23_1.save()
        choice23_2 = Choice.objects.create(
            question=question23, order=2, text="随性就好")
        choice23_2.save()

        # ========== 三、性格（与室友、家人关系） ==========

        question24 = Question.objects.create(
            survey=survey,
            order=24,
            topic="你的性格",
            type=Question.Type.SINGLE,
        )
        question24.save()

        choice24_1 = Choice.objects.create(
            question=question24,
            order=1,
            text='内向型：独处时精力充沛；更封闭，更愿意在经挑选的小群体中分享个人的情况；不把兴奋说出来。',
        )
        choice24_1.save()
        choice24_2 = Choice.objects.create(
            question=question24,
            order=2,
            text='适中型：介于二者之间，能够在内外向之间切换，在人群中乐意与人交谈结交朋友，同时也享受独处。',
        )
        choice24_2.save()
        choice24_3 = Choice.objects.create(
            question=question24,
            order=3,
            text='外向型：与他人相处时精力充沛；易于“读”和了解，随意地分享个人情况；高度热情地社交。',
        )
        choice24_3.save()

        question25 = Question.objects.create(
            survey=survey,
            order=25,
            topic="你希望室友的性格",
            type=Question.Type.SINGLE,
        )
        question25.save()

        choice25_1 = Choice.objects.create(
            question=question25, order=1, text="内向型")
        choice25_1.save()
        choice25_2 = Choice.objects.create(
            question=question25, order=2, text="适中型")
        choice25_2.save()
        choice25_3 = Choice.objects.create(
            question=question25, order=3, text="外向型")
        choice25_3.save()

        question26 = Question.objects.create(
            survey=survey,
            order=26,
            topic="你对于室友的期待是",
            type=Question.Type.SINGLE,
        )
        question26.save()

        choice26_1 = Choice.objects.create(
            question=question26, order=1, text="专注学习")
        choice26_1.save()
        choice26_2 = Choice.objects.create(
            question=question26, order=2, text="全面发展")
        choice26_2.save()

        question27 = Question.objects.create(
            survey=survey,
            order=27,
            topic="你本人更希望大学生活是",
            type=Question.Type.SINGLE,
        )
        question27.save()

        choice27_1 = Choice.objects.create(
            question=question27, order=1, text="专注学习")
        choice27_1.save()
        choice27_2 = Choice.objects.create(
            question=question27, order=2, text="全面发展")
        choice27_2.save()

        question28 = Question.objects.create(
            survey=survey,
            order=28,
            topic="你希望宿舍的氛围",
            type=Question.Type.TEXT,
            required=False,
        )
        question28.save()

        # ========== 四、价值观测量 ==========

        # --- 价值观陈述（10题） ---
        values_description = '请判断以下各陈述多大程度上与你的真实情况或想法相一致。请注意：这些题目没有任何\u201c标准答案\u201d，你可以放心按照你对自己的直觉理解作答。'

        values_topics = [
            "我有信心我将在大学期间延续自己过去在学业上的成功",
            "我在成长道路上所经历的挫折，比身边大多数同龄人更少",
            "对我而言，在大学期间结识很多好朋友非常重要",
            "我比大部分同龄人更富领导能力",
            "我对我的人际交往能力非常自信",
            "对于未来的我而言，获得事业上的卓越成就比拥有一个幸福家庭更为重要",
            "我现在清醒地知道未来一年中我应该朝向何种目标努力、为此需要付出哪些行动",
            "我比大部分同龄人更擅长在挫折面前重新振作起来",
            "如果有人与我观点不同，我会想尽一切办法来努力说服他",
            "我对自己的自我约束能力（自制力）缺乏信心",
        ]

        for idx, topic in enumerate(values_topics):
            q = Question.objects.create(
                survey=survey,
                order=29 + idx,
                topic=topic,
                type=Question.Type.SINGLE,
                description=values_description,
            )
            q.save()

            for choice_order, text in enumerate(["完全不同", "比较不同", "不确定", "比较一致", "完全一致"], start=1):
                c = Choice.objects.create(
                    question=q,
                    order=choice_order,
                    text=text,
                )
                c.save()

        # --- 排序题：书院制吸引力排序 ---
        question30 = Question.objects.create(
            survey=survey,
            order=39,
            topic="请对元培学院书院制育人模式的各项事物，按照吸引力从高到低排序",
            type=Question.Type.RANKING,
            description="元培学院的书院制育人模式依托于一系列独特的制度、设施和举措。请评估下列事物对你的吸引力，并按照最具有吸引力到最不具有吸引力排序。",
        )
        question30.save()

        ranking_items = [
            "元培宿舍楼（35楼）的地下公共空间",
            '\u201c尚自然展个性、化孤独为共同\u201d和\u201c自主学习、自由探索、完全人格、共同生活\u201d的育人理念',
            '\u201c双自由\u201d机制（自由选择并转换专业、自由选课）',
            '\u201c德、智、体、美、劳\u201d五育书院课程',
            "书院内开设的各类学生俱乐部",
            "文理融通的通识教育",
        ]

        for idx, item in enumerate(ranking_items, start=1):
            c = Choice.objects.create(
                question=question30,
                order=idx,
                text=item,
            )
            c.save()

        # --- 优秀大学生特质（限选6项） ---
        question31 = Question.objects.create(
            survey=survey,
            order=40,
            topic="请在以下选项中，勾选出你认为优秀大学生应当具备的6项最重要特质",
            type=Question.Type.MULTIPLE,
            description="限选6项",
            min_choices=6,
            max_choices=6,
        )
        question31.save()

        traits = [
            "高雅的艺术品位",
            "优秀的身体素质和体育水平",
            "对社会主义的坚定信念",
            "杰出的学术研究能力",
            "优秀的学生工作履历",
            "无私的奉献精神",
            "健康卫生的生活习惯",
            "有规律的作息",
            "优秀的表达能力",
            "长远清晰的生涯规划和职业定位",
            "领先的学业成绩",
            "高度的民族自豪感和自信心",
            "广泛的社会交往",
            "积极的社会责任感",
            "过硬的职业训练",
        ]

        for idx, trait in enumerate(traits, start=1):
            c = Choice.objects.create(
                question=question31,
                order=idx,
                text=trait,
            )
            c.save()

        # --- 三段开放式文本（选答） ---
        question32 = Question.objects.create(
            survey=survey,
            order=41,
            topic="请用一段话描述现在的你",
            type=Question.Type.TEXT,
            required=False,
        )
        question32.save()

        question33 = Question.objects.create(
            survey=survey,
            order=42,
            topic="请用一段话描述你对大学生活的期待",
            type=Question.Type.TEXT,
            required=False,
        )
        question33.save()

        question34 = Question.objects.create(
            survey=survey,
            order=43,
            topic="请用一段话描述你对本科毕业后的自己的期待",
            type=Question.Type.TEXT,
            required=False,
        )
        question34.save()

        # Finished message
        self.stdout.write(self.style.SUCCESS('2026问卷创建完成！请在管理后台查看。'))
