from app.utils_dependency import *
from app.models import (
    AcademicTagEntry,
    AcademicTextEntry,
)

from typing import List

__all__ = [
    'get_search_results',
]


def get_search_results(query: str) -> List[dict]:
    """
    根据提供的关键词获取搜索结果。

    :param keyword: 关键词
    :type keyword: str
    :return: 搜索结果list，元素为dict，包含key：姓名、条目内容中包含关键词的条目名
    :rtype: List[dict]
    """
    # 首先搜索所有含有关键词的学术地图项目，忽略大小写
    academic_tags = AcademicTagEntry.objects.filter(tag__tag_content__icontains=query)
    academic_texts = AcademicTextEntry.objects.filter(content__icontains=query)

    # 然后根据tag/text对应的人，整合学术地图项目
    academic_map_dict = {}  # 整理一个以人名为key，以含有年级和学术地图项目的dict为value的dict
    highlight_query = '<font style="background-color: yellow; font-weight: bold;">' + query + '</font>'
    for tag in academic_tags:
        person_name = tag.person.name
        academic_map_dict[person_name] = academic_map_dict.get(person_name, {"年级": tag.person.stu_grade})
        academic_map_dict[person_name].update(
            {tag.tag.get_atype_display(): tag.content.replace(query, highlight_query)}  # 搜索结果高亮显示
        )
    for text in academic_texts:
        person_name = text.person.name
        academic_map_dict[person_name] = academic_map_dict.get(person_name, {"年级": tag.person.stu_grade})
        academic_map_dict[person_name].update(
            {text.get_atype_display(): text.content.replace(query, highlight_query)}  # 搜索结果高亮显示
        )
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = []
    for key, value in academic_map_dict.items():
        academic_map_list.append(dict({"姓名": key}, **value))
    return academic_map_list
