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
    def __init__(self, id, remain):
        self.id = id
        self.remain = remain
        self.stu = []

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
        专业是否平均分配：2文2理 > 4文/4理 > 文理1:3
        存在来自同一省份的同学减分，并针对北京地区特别操作
        衡量起床时间、睡眠时间的接近程度，计算方差
        衡量能接受的最低空调温度接近程度，计算方差，特别计算能否接受整夜开空调的统一程度
        在手动分配前，尽量保证宿舍是4人或3人的
        与留学生住宿意愿也加入得分中
        '''
        score = 0

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


def read_info():
    '''返回一个Freshman的list'''
    freshmen = []

    df = pd.read_excel("/workspace/dormitory/references/results.xlsx")
    df2 = pd.read_excel("/workspace/dormitory/references/info.xlsx")

    for index, stu in df.iterrows():
        data = defaultdict()

        data['name'] = stu["姓名*"]
        data['gender'] = stu["性别*"]
        data['sid'] = stu["学号*"]
        data['origin'] = stu["生源地*"]
        data['high_school'] = stu["生源高中*"]
        data['major'] = stu["大学专业意向*"]
        data['weight'] = stu["体重*（单位：kg）"]
        data['international'] = stu["是否愿意与留学生住在同一间宿舍? (都在元培35号宿舍楼居住，即你是否愿意舍友中有留学生同学? )*"]
        data['wake'] = stu["起床时间*"]
        data['sleep'] = stu["入睡时间*"]
        data['ac_temp'] = stu["夏天能接受的最低空调温度*"]
        data['all_night_ac'] = stu["是否接受夏天整夜开空调*"]

        # 在info表格中，根据学号找到对应行，读取生源地和生源高中信息，保证信息准确
        info_row = df2.loc[df2["学号"] == data['sid']].iloc[0]
        data['origin'] = info_row["省市"]
        data['high_school'] = info_row["中学"]

        major_map = {"文科类": 0,
                     "理工类": 1, }
        data['major'] = major_map.get(data['major'])

        data['weight'] = float(data['weight'].replace("kg", ""))

        international_map = {"愿意": 5,
                             "都可以": 1,
                             "不愿意": 0, }
        data['international'] = international_map.get(data['international'])

        wake_map = {"上午6点之前": 0,
                    "6点-7点": 1,
                    "7点-8点": 2,
                    "8点-9点": 3,
                    "9点-10点": 4,
                    "10点之后": 5, }
        data['wake'] = wake_map.get(data['wake'])

        sleep_map = {"22点之前": 0,
                     "22点-23点": 1,
                     "23点-24点": 2,
                     "0点-1点": 3,
                     "1点-2点": 4,
                     "2点之后": 5, }
        data['sleep'] = sleep_map.get(data['sleep'])

        data['ac_temp'] = int(data['ac_temp'][:2])

        ac_map = {"是": 1,
                  "否": 0, }
        data['all_night_ac'] = ac_map.get(data['all_night_ac'])

        freshman_data = dict(data)
        freshman = Freshman(freshman_data)
        freshmen.append(freshman)

    return freshmen


def read_dorm():
    '''返回一个Dormitory的list'''
    dorm = []

    df = pd.read_excel("/workspace/dormitory/references/dorm.xlsx")

    for index, room in df.iterrows():
        rid = int(room["房间"])
        if len(dorm) == 0 or dorm[-1].id != rid:
            dorm.append(Dormitory(rid, 1))
        else:
            dorm[-1].remain += 1

    # 注意，只选择了剩余床位为4的作为分配目标
    male_dorm = [d for d in dorm if (d.id < 400 or (
        d.id < 500 and d.id > 464)) and d.remain == 4]
    female_dorm = [d for d in dorm if d.id > 500 and d.remain == 4][:24]

    return male_dorm, female_dorm


def assign_dorm():
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


def out_as_excel():
    '''将结果导出为excel文件，存储在reference/dorm_assigned.xlsx下'''
    dorm_result = assign_dorm()

    df = pd.DataFrame()

    major_list = ["文科类", "理工类"]
    international_list = ["不愿意", "都可以", "愿意"]
    wake_list = ["上午6点之前", "6点-7点", "7点-8点", "8点-9点", "9点-10点", "10点之后"]
    sleep_list = ["22点之前", "22点-23点", "23点-24点", "0点-1点", "1点-2点", "2点之后"]
    ac_list = ["否", "是"]

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
            }
            temp_df = pd.DataFrame(data, index=[0])
            df = pd.concat([df, temp_df], ignore_index=True)

    df.to_excel(
        '/workspace/dormitory/references/dorm_assigned.xlsx', index=False)


class Command(BaseCommand):
    help = "Assign dormitory."

    def handle(self, *args, **options):
        out_as_excel()
