from django.db import migrations


TAG_TREE = [
    (
        "艺术与创作",
        "art",
        [
            ("视觉艺术", "art-visual", ["绘画", "摄影", "书法", "设计", "手工"]),
            ("表演艺术", "art-performing", ["音乐", "乐器", "舞蹈", "戏剧", "声乐"]),
            ("内容创作", "art-content", ["写作", "视频创作", "播客", "动漫创作"]),
        ],
    ),
    (
        "运动与户外",
        "sports",
        [
            ("球类运动", "sports-ball", ["篮球", "足球", "羽毛球", "乒乓球", "网球", "排球"]),
            ("健身运动", "sports-fitness", ["跑步", "游泳", "健身", "瑜伽", "武术"]),
            ("户外探索", "sports-outdoor", ["徒步", "骑行", "登山", "露营", "滑雪"]),
        ],
    ),
    (
        "游戏与竞技",
        "games",
        [
            ("电子游戏", "games-video", ["电子游戏", "电子竞技", "独立游戏"]),
            ("桌面游戏", "games-tabletop", ["桌游", "棋牌", "剧本杀", "桌面角色扮演"]),
            ("益智竞技", "games-mind", ["数独", "魔方", "围棋", "象棋"]),
        ],
    ),
    (
        "技术与工程",
        "technology",
        [
            ("软件技术", "technology-software", ["编程", "Web 开发", "移动开发", "开源"]),
            ("数据智能", "technology-data", ["人工智能", "数据分析", "机器学习", "数据可视化"]),
            ("工程制作", "technology-engineering", ["硬件制作", "机器人", "电子设计", "三维打印"]),
        ],
    ),
    (
        "学术与知识",
        "knowledge",
        [
            ("自然科学", "knowledge-science", ["数学", "物理", "化学", "生物", "地球科学"]),
            ("人文社科", "knowledge-humanities", ["历史", "哲学", "文学", "社会科学", "心理学"]),
            ("阅读探索", "knowledge-reading", ["阅读", "科普", "学术写作", "跨学科研究"]),
        ],
    ),
    (
        "语言与表达",
        "communication",
        [
            ("语言", "communication-language", ["英语", "日语", "法语", "德语", "翻译"]),
            ("公共表达", "communication-public", ["演讲", "辩论", "主持", "采访", "讲故事"]),
        ],
    ),
    (
        "生活与公益",
        "life",
        [
            ("生活美学", "life-style", ["烹饪", "烘焙", "咖啡", "园艺", "旅行"]),
            ("公共参与", "life-public", ["志愿服务", "公益", "学生工作", "社群运营"]),
        ],
    ),
]


SKILL_ONLY_TAGS = {
    "绘画", "书法", "设计", "手工", "乐器", "声乐", "写作", "视频创作", "播客", "动漫创作",
    "编程", "Web 开发", "移动开发", "开源", "人工智能", "数据分析", "机器学习", "数据可视化",
    "硬件制作", "机器人", "电子设计", "三维打印", "学术写作", "跨学科研究",
    "英语", "日语", "法语", "德语", "翻译", "演讲", "辩论", "主持", "采访", "讲故事",
    "烹饪", "烘焙", "园艺", "学生工作", "社群运营",
}

BOTH_TAGS = {"摄影", "舞蹈", "戏剧"}


def seed_profile_tags(apps, schema_editor):
    Category = apps.get_model("app", "ProfileTagCategory")
    Tag = apps.get_model("app", "ProfileTag")

    for root_order, (root_name, root_slug, children) in enumerate(TAG_TREE, start=1):
        root, _ = Category.objects.get_or_create(
            slug=root_slug,
            defaults={
                "name": root_name,
                "sort_order": root_order,
                "is_active": True,
            },
        )
        for child_order, (child_name, child_slug, tag_names) in enumerate(children, start=1):
            child, _ = Category.objects.get_or_create(
                slug=child_slug,
                defaults={
                    "name": child_name,
                    "parent": root,
                    "sort_order": child_order,
                    "is_active": True,
                },
            )
            for tag_name in tag_names:
                normalized_name = " ".join(tag_name.strip().split()).casefold()
                applies_to = "interest"
                if tag_name in SKILL_ONLY_TAGS:
                    applies_to = "skill"
                elif tag_name in BOTH_TAGS:
                    applies_to = "both"
                Tag.objects.get_or_create(
                    category=child,
                    normalized_name=normalized_name,
                    defaults={
                        "name": tag_name,
                        "source": "official",
                        "applies_to": applies_to,
                        "status": "visible",
                    },
                )


class Migration(migrations.Migration):
    dependencies = [("app", "0017_profile_tag_tree")]

    operations = [
        # 用户自定义标签会引用这些分类，回滚时删除候选池会破坏用户数据。
        migrations.RunPython(seed_profile_tags, migrations.RunPython.noop),
    ]
