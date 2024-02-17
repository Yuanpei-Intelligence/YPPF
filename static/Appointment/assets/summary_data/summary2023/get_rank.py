import json
from collections import defaultdict

def get_rank(data_dict, data_name, rank_dict):
    '''
    data_dict: 包含(data_name, value)的dict
    data_name: 需要获取排名的数据名称，如study_room_num
    rank_dict: 用于保存所有排名信息的dict，用于导出包含所有排名信息的json文件
    '''
    data_name = data_name + '_rank'
    sorted_username_list = sorted(data_dict, key=lambda x: data_dict.get(x))
    num_students = len(sorted_username_list)

    num_to_rank_dict = {}

    for idx, username in enumerate(sorted_username_list):
        data = data_dict[username]
        if data in num_to_rank_dict:
            rank_dict[username][data_name] = num_to_rank_dict[data]
            continue
        rank = round((idx + 1) / num_students * 100, 1)
        num_to_rank_dict[data] = rank
        rank_dict[username][data_name] = rank


with open("summary2023.json", "r") as f:
    summary_dict = json.load(f)
    study_room_num_dict, max_consecutive_days_dict = {}, {}
    for username, user_dict in summary_dict.items():
        study_room_num_dict[username] = user_dict.get('study_room_num', 0)
        max_consecutive_days_dict[username] = user_dict.get('max_consecutive_days', 0)

    rank_dict = defaultdict(dict)

    get_rank(study_room_num_dict, 'study_room_num', rank_dict)
    get_rank(max_consecutive_days_dict, 'max_consecutive_days', rank_dict)

    with open("rank2023.json", "w", encoding="utf-8") as f1:
        json.dump(rank_dict, f1)

