import copy
import random
from collections import defaultdict

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand

'''
有关reference文件夹的说明：
reference文件夹用于存放宿舍分配时的参考信息。
results.xlsx是新生问卷填写结果；
info.xlsx是学院提供的含有新生姓名、学号、生源地、生源高中的表格；
dorm.xlsx是学院提供的含有空余宿舍列表的表格；
dorm_assigned.xlsx是保存宿舍分配结果的目标文件。
'''


class Freshman:
    def __init__(self, data):
        self.data = data


class Dormitory:
    def __init__(self, id: int, remain: int, is_noisy: bool):
        self.id = id
        self.remain = remain
        self.stu = []
        # 盥洗室和楼道口比较吵闹，此属性为 True，其他寝室为 False
        self.noisy = is_noisy

    def add(self, student: Freshman):
        self.stu.append(student)

    def check_must(self):
        '''
        一个宿舍必须满足的条件：
        宿舍里的同学至少来自3个不同的省份
        来自同一省份的2人不能来自同一所高中
        '''
        origin = [s.data['origin'] for s in self.stu]
        if len(set(origin)) < len(self.stu) - 1:
            return False
        elif len(set(origin)) == len(self.stu) - 1:
            indices = {}
            for i, p in enumerate(origin):
                indices[p] = indices.get(p, []) + [i]
            dupl = [v for k, v in indices.items() if len(v) > 1][0]
            hs = [self.stu[i].data['high_school'] for i in dupl]
            if hs[0] == hs[1]:
                return False
        return True

    def check_better(self):
        '''
        计算宿舍得分，应用于交换优化场景。
        宿舍计分项包括：
        存在来自同一省份的同学减分，并针对北京地区特别操作
        专业是否平均分配：2文2理 > 4文/4理 > 文理1:3
        性格分配是否合理：尽量一个寝室不要多于两个内向
        是否愿意和留学生/交换生同宿舍
        衡量能接受的最低空调温度接近程度，计算方差，特别计算能否接受整夜开空调的统一程度
        衡量起床时间、睡眠时间的接近程度，计算方差
        睡眠困扰同学尽量远离盥洗室和楼梯口（用 Dormitory.noisy 衡量）
        宿舍环境（尽量保证一个宿舍整洁条理的有2人/随性就好的有2人）
        对室友期待（一个寝室尽量不要全部专注学习/全面发展）
        在手动分配前，尽量保证宿舍是4人或3人的
        '''
        score = 0

        # FIXME: Reorder the following blocks to match the precedence mentioned above.

        major_score = sum([s.data['major'] for s in self.stu])
        if major_score == 2:
            score += 1200
        elif major_score == 0 or major_score == 4:
            score += 800

        origin = [s.data['origin'] for s in self.stu]
        if len(set(origin)) == len(self.stu) - 1:
            score -= 300
        beijing = [s for s in origin if s == "北京"]
        if len(beijing) >= 2:
            score -= 700

        wake_score = np.var([s.data['wake'] for s in self.stu])
        score -= 30 * wake_score

        sleep_score = np.var([s.data['sleep'] for s in self.stu])
        score -= 30 * sleep_score

        ac_score = 20 * np.var([s.data['ac_temp'] for s in self.stu])
        ac_score += (len(set([s.data['all_night_ac']
                     for s in self.stu])) - 1) * 400
        score -= ac_score

        stu_cnt_map = {4: 600,
                       3: 400,
                       2: 0,
                       1: 0,
                       0: 0, }
        score += stu_cnt_map.get(len(self.stu))

        score += 8 * np.prod([s.data['international'] for s in self.stu])

        return score


def read_info() -> list[Freshman]:
    '''返回一个Freshman的list'''
    freshmen = []

    df = pd.read_excel("/workspace/dormitory/references/results.xlsx")
    df2 = pd.read_excel("/workspace/dormitory/references/info.xlsx")

    for index, stu in df.iterrows():
        data = defaultdict()

        data['name'] = stu["姓名"]
        data['gender'] = stu["性别"]
        data['sid'] = stu["学号"]
        data['origin'] = stu["生源地"]
        data['high_school'] = stu["生源高中"]
        data['major'] = stu["专业意向"]
        data['weight'] = stu["体重"]
        data['international'] = stu["是否愿意和留学生住一起"]
        data['wake'] = stu["你预期的大学生活起床时间"]
        data['sleep'] = stu["你预期的大学生活睡觉时间"]
        data['ac_temp'] = stu["夏天能接受的最低空调温度"]
        data['all_night_ac'] = stu["是否接受夏天整晚开空调"]
        data['personality'] = stu["你的性格"]
        data['sleep_quality'] = stu["你的睡眠质量是"]
        data['environment'] = stu["你希望你的宿舍环境是"]
        data['expectation'] = stu["你本人更希望大学生活是"]

        # 在info表格中，根据学号找到对应行，读取生源地和生源高中信息，保证信息准确
        info_row = df2.loc[df2["学号"] == data['sid']].iloc[0]
        data['origin'] = info_row["省市"]
        # 2024年的 info 表格不包含这个列，只能选择相信问卷里填的
        # data['high_school'] = info_row["中学"]

        # 注意此处 map 的值要和 out_as_excel() 中对应
        major_map = {"文科类": 0,
                     "理工类": 1, }
        data['major'] = major_map.get(data['major'])

        data['weight'] = float(data['weight'].replace("kg", ""))

        international_map = {"愿意": 5,
                             "都可以": 1,
                             "不愿意": 0, }
        data['international'] = international_map.get(data['international'])

        wake_map = {"7点前": 0,
                    "7~8点": 1,
                    "8~9点": 2,
                    "9-10点": 3,
                    "10-11点": 4,
                    "11点后": 5, }
        data['wake'] = wake_map.get(data['wake'])

        sleep_map = {"23点前": 0,
                     "23-24点": 1,
                     "24-1点": 2,
                     "1-2点": 3,
                     "2点后": 4, }
        data['sleep'] = sleep_map.get(data['sleep'])

        data['ac_temp'] = int(data['ac_temp'][:2])

        ac_map = {"是": 1,
                  "否": 0, }
        data['all_night_ac'] = ac_map.get(data['all_night_ac'])

        personality_map = {"内向型（独处时精力充沛；更封闭，更愿意在经挑选的小群体中分享个人的情况；不把兴奋说出来。）": 0,
                           "适中型（介于二者之间，能够在内外向之间切换，在人群中乐意与人交谈结交朋友，同时也享受独处。）": 1,
                           "外向型（与他人相处时精力充沛；易于“读”和了解，随意地分享个人情况；高度热情地社交。）": 2, }
        data['personality'] = personality_map.get(data['personality'])

        sleep_quality_map = {"浅眠型（易受声、光影响）": 0,
                             "酣睡型（较少受影响，一觉到天亮）": 1, }
        data['sleep_quality'] = sleep_quality_map.get(data['sleep_quality'])

        environment_map = {"整洁条理": 0, "随性就好": 1, }
        data['environment'] = environment_map.get(data['environment'])

        expectation_map = {"专注学习": 0, "全面发展": 1}
        data['expectation'] = expectation_map.get(data['expectation'])

        freshman_data = dict(data)
        freshman = Freshman(freshman_data)
        freshmen.append(freshman)

    return freshmen


def read_dorm() -> tuple[list[Dormitory], list[Dormitory]]:
    '''返回一个Dormitory的list'''
    dorm = []

    df = pd.read_excel("/workspace/dormitory/references/dorm.xlsx")

    for index, room in df.iterrows():
        rid = int(room["房间"])
        if len(dorm) == 0 or dorm[-1].id != rid:
            # We can tell if a dormitory is noisy from its last two digits
            dorm.append(Dormitory(rid, 1, (rid % 100) in (12, 25, 35, 36, 38, 39, 40, 49, 64)))
        else:
            dorm[-1].remain += 1

    # 注意，只选择了剩余床位为4的作为分配目标
    # FIXME: The dormitory partition scheme changed this year.
    male_dorm = [d for d in dorm if (d.id < 400 or (
        d.id < 500 and d.id > 464)) and d.remain == 4]
    female_dorm = [d for d in dorm if d.id > 500 and d.remain == 4][:24]

    return male_dorm, female_dorm


def assign_dorm() -> list[Dormitory]:
    '''
    分配宿舍算法：
    执行若干次（250000次）随机交换（选取任一宿舍，选取任一床位），
    衡量交换前后两宿舍得分之和，使得总得分最大化
    '''
    freshmen = read_info()
    male_dorm, female_dorm = read_dorm()

    # 初始随机分配
    # TODO: 如果运气很烂，最后剩余4人无法分到同一宿舍，可能导致算法卡死。
    for stu in freshmen:
        assigned = False
        while not assigned:
            male_vacant = [d for d in male_dorm if d.remain > 0]
            female_vacant = [d for d in female_dorm if d.remain > 0]
            if stu.data['gender'] == "男":
                dorm = random.choice(male_vacant)
                dorm.add(stu)
                if dorm.check_must():
                    dorm.remain -= 1
                    assigned = True
                else:
                    dorm.stu.pop()
            else:
                dorm = random.choice(female_vacant)
                dorm.add(stu)
                if dorm.check_must():
                    dorm.remain -= 1
                    assigned = True
                else:
                    dorm.stu.pop()

    # 随机交换
    epsilon = 0.3
    for episode in range(250000):
        print(episode)

        rid1 = random.randint(0, len(male_dorm) - 1)
        rid2 = random.randint(0, len(male_dorm) - 1)
        if rid1 == rid2:
            continue

        room1: Dormitory = copy.deepcopy(male_dorm[rid1])
        room2: Dormitory = copy.deepcopy(male_dorm[rid2])
        o_score = room1.check_better() + room2.check_better()
        if len(room1.stu) == 0 or len(room2.stu) == 0:
            continue

        temp1: Dormitory = copy.deepcopy(room1)
        temp2: Dormitory = copy.deepcopy(room2)

        del male_dorm[max(rid1, rid2)]
        del male_dorm[min(rid1, rid2)]

        if random.random() < epsilon:
            if len(room1.stu) != 4 and len(room2.stu) != 4:
                temp2.add(temp1.stu.pop())
                if temp1.check_must() and temp2.check_must() and (temp1.check_better() + temp2.check_better() > o_score):
                    room1 = temp1
                    room2 = temp2
                    o_score = room1.check_better() + room2.check_better()

        if len(room1.stu) == 0 or len(room2.stu) == 0:
            male_dorm.append(room1)
            male_dorm.append(room2)
            continue

        temp1: Dormitory = copy.deepcopy(room1)
        temp2: Dormitory = copy.deepcopy(room2)

        bid1 = random.randint(0, len(room1.stu) - 1)
        bid2 = random.randint(0, len(room2.stu) - 1)

        temp1.stu[bid1], temp2.stu[bid2] = temp2.stu[bid2], temp1.stu[bid1]
        if temp1.check_must() and temp2.check_must() and (temp1.check_better() + temp2.check_better() > o_score):
            male_dorm.append(temp1)
            male_dorm.append(temp2)
        else:
            male_dorm.append(room1)
            male_dorm.append(room2)

    for episode in range(250000):
        print(episode)

        rid1 = random.randint(0, len(female_dorm) - 1)
        rid2 = random.randint(0, len(female_dorm) - 1)
        if rid1 == rid2:
            continue

        room1: Dormitory = copy.deepcopy(female_dorm[rid1])
        room2: Dormitory = copy.deepcopy(female_dorm[rid2])
        o_score = room1.check_better() + room2.check_better()
        if len(room1.stu) == 0 or len(room2.stu) == 0:
            continue

        temp1: Dormitory = copy.deepcopy(room1)
        temp2: Dormitory = copy.deepcopy(room2)

        del female_dorm[max(rid1, rid2)]
        del female_dorm[min(rid1, rid2)]

        if random.random() < epsilon:
            if len(room1.stu) != 4 and len(room2.stu) != 4:
                temp2.add(temp1.stu.pop())
                if temp1.check_must() and temp2.check_must() and (temp1.check_better() + temp2.check_better() > o_score):
                    room1 = temp1
                    room2 = temp2
                    o_score = room1.check_better() + room2.check_better()

        if len(room1.stu) == 0 or len(room2.stu) == 0:
            female_dorm.append(room1)
            female_dorm.append(room2)
            continue

        temp1: Dormitory = copy.deepcopy(room1)
        temp2: Dormitory = copy.deepcopy(room2)

        bid1 = random.randint(0, len(room1.stu) - 1)
        bid2 = random.randint(0, len(room2.stu) - 1)

        temp1.stu[bid1], temp2.stu[bid2] = temp2.stu[bid2], temp1.stu[bid1]
        if temp1.check_must() and temp2.check_must() and (temp1.check_better() + temp2.check_better() > o_score):
            female_dorm.append(temp1)
            female_dorm.append(temp2)
        else:
            female_dorm.append(room1)
            female_dorm.append(room2)

    male_dorm.sort(key=lambda d: d.id)
    female_dorm.sort(key=lambda d: d.id)

    dorm_result = male_dorm + female_dorm
    return dorm_result


def out_as_excel(dorm_result: list[Dormitory]):
    '''将结果导出为excel文件，存储在reference/dorm_assigned.xlsx下'''
    df = pd.DataFrame()

    major_list = ["文科类", "理工类"]
    international_list = ["不愿意", "都可以", "愿意"]
    wake_list = ["7点前", "7~8点", "8~9点", "9-10点", "10-11点", "11点后"]
    sleep_list = ["23点前", "23-24点", "24-1点", "1-2点", "2点后"]
    ac_list = ["否", "是"]
    personality_list = ["内向型（独处时精力充沛；更封闭，更愿意在经挑选的小群体中分享个人的情况；不把兴奋说出来。）",
                        "适中型（介于二者之间，能够在内外向之间切换，在人群中乐意与人交谈结交朋友，同时也享受独处。）",
                        "外向型（与他人相处时精力充沛；易于“读”和了解，随意地分享个人情况；高度热情地社交。）"]
    sleep_quality_list = ["浅眠型（易受声、光影响）", "酣睡型（较少受影响，一觉到天亮）"]
    environment_list = ["整洁条理", "随性就好"]
    expectation_list = ["专注学习", "全面发展"]

    for dorm in dorm_result:
        for stu in dorm.stu:
            data = {
                "宿舍号": dorm.id,
                "姓名": stu.data['name'],
                "性别": stu.data['gender'],
                "学号": stu.data['sid'],
                "生源地": stu.data['origin'],
                "生源高中": stu.data['high_school'],
                "意向专业": major_list[stu.data['major']],
                "体重": stu.data['weight'],
                "是否愿意与留学生住在同一间宿舍?": international_list[stu.data['international'] % 3],
                "起床时间": wake_list[stu.data['wake']],
                "入睡时间": sleep_list[stu.data['sleep']],
                "夏天能接受的最低空调温度": stu.data['ac_temp'],
                "是否接受夏天整夜开空调": ac_list[stu.data['all_night_ac']],
                "性格": personality_list[stu.data['personality']],
                "睡眠质量": sleep_quality_list[stu.data['sleep_quality']],
                "希望宿舍环境": environment_list[stu.data['environment']],
                "对大学生活期待": expectation_list[stu.data['expectation']],
            }
            temp_df = pd.DataFrame(data, index=[0])
            df = pd.concat([df, temp_df], ignore_index=True)

    df.to_excel(
        '/workspace/dormitory/references/dorm_assigned.xlsx', index=False)


class Command(BaseCommand):
    help = "Assign dormitory."

    def handle(self, *args, **options):
        out_as_excel()
