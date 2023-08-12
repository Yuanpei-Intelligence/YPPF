import pandas as pd
import numpy as np
import random
import copy
from collections import defaultdict

from django.core.management.base import BaseCommand

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
        score = 0

        major_score = sum([s.data['major'] for s in self.stu])
        if major_score == 2:
            score += 1000
        elif major_score == 0 or major_score == 4:
            score += 700
        
        origin = [s.data['origin'] for s in self.stu]
        beijing = [s for s in origin if s == "北京"]
        if len(beijing) >= 2:
            score -= 600
        
        wake_score = np.var([s.data['wake'] for s in self.stu])
        score -= 5 * wake_score

        sleep_score = np.var([s.data['sleep'] for s in self.stu])
        score -= 5 * sleep_score

        ac_score = 10 * np.var([s.data['ac_temp'] for s in self.stu])
        ac_score += (len(set([s.data['all_night_ac'] for s in self.stu])) - 1) * 300
        score -= ac_score

        stu_cnt_map = {4: 100, 
                       3: 50, 
                       2: 10, 
                       1: 0, 
                       0: 0, }
        score += stu_cnt_map.get(len(self.stu))

        if len(self.stu) != 4:
            score += np.prod([s.data['international'] for s in self.stu])

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
    dorm = []

    df = pd.read_excel("/workspace/dormitory/references/dorm.xlsx")

    for index, room in df.iterrows():
        rid = int(room["房间"])
        if len(dorm) == 0 or dorm[-1].id != rid:
            dorm.append(Dormitory(rid, 1))
        else:
            dorm[-1].remain += 1
    
    male_dorm = [d for d in dorm if (d.id < 400 or (d.id < 500 and d.id > 464)) and d.remain == 4]
    female_dorm = [d for d in dorm if d.id > 500 and d.remain == 4]

    return male_dorm, female_dorm


def try_swap(room1: Dormitory, room2: Dormitory, bid1: int, bid2: int):
    if bid1 >= len(room1.stu) and bid2 >= len(room2.stu):
        return room1, room2
    elif bid1 >= len(room1.stu) and bid2 < len(room2.stu):
        if len(room1.stu) == 1:
            if len(room2.stu) == 4:
                return room1, room2
            else:
                room2.add(room1.stu[0])
                if room2.check_must():
                    room2.remain -= 1
                    room1.stu.pop()
                    room1.remain += 1
                    return room1, room2
                else:
                    room2.stu.pop()
                    return room1, room2
        else:
            student = room2.stu[bid2]
            temp1 = copy.deepcopy(room1)
            temp2 = copy.deepcopy(room2)
            del temp2.stu[bid2]
            temp1.add(student)
            if temp1.check_must() and temp2.check_must() and (room1.check_better() + room2.check_better() < temp1.check_better() + temp2.check_better()):
                return temp1, temp2
            return room1, room2
    elif bid1 < len(room1.stu) and bid2 >= len(room2.stu):
        return try_swap(room2, room1, bid2, bid1)
    elif bid1 < len(room1.stu) and bid2 < len(room2.stu):
        student1, student2 = room1.stu[bid1], room2.stu[bid2]
        temp1 = copy.deepcopy(room1)
        temp2 = copy.deepcopy(room2)
        del temp1.stu[bid1]
        del temp2.stu[bid2]
        temp1.add(student2)
        temp2.add(student1)
        if temp1.check_must() and temp2.check_must() and (room1.check_better() + room2.check_better() < temp1.check_better() + temp2.check_better()):
            return temp1, temp2
        return room1, room2


def assign_dorm():
    freshmen = read_info()
    male_dorm, female_dorm = read_dorm()

    # 初始随机分配
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
    for episode in range(250000):
        print(episode)
        male_habitat = [d for d in male_dorm if d.remain != 4]
        room1 = random.choice(male_habitat)
        room2 = random.choice(male_habitat)
        bid1 = random.randint(0, 3)
        bid2 = random.randint(0, 3)

        if (room1 == room2 and bid1 == bid2):
            continue
        else:
            temp1, temp2 = try_swap(room1, room2, bid1, bid2)
            room1 = copy.deepcopy(temp1)
            room2 = copy.deepcopy(temp2)
    
    for episode in range(250000):
        print(episode)
        female_habitat = [d for d in female_dorm if d.remain != 4]
        room1 = random.choice(female_habitat)
        room2 = random.choice(female_habitat)
        bid1 = random.randint(0, 3)
        bid2 = random.randint(0, 3)

        if (room1 == room2 and bid1 == bid2):
            continue
        else:
            temp1, temp2 = try_swap(room1, room2, bid1, bid2)
            room1 = copy.deepcopy(temp1)
            room2 = copy.deepcopy(temp2)
        

    dorm_result = male_dorm + female_dorm
    return dorm_result


def out_as_excel():
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
    
    df.to_excel('/workspace/dormitory/references/dorm_assigned.xlsx', index=False)


class Command(BaseCommand):
    help = "Assign dormitory."

    def handle(self, *args, **options):
        pass
