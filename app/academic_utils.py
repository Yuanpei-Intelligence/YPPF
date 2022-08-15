from app.utils_dependency import *
from app.models import (
    AcademicTag,
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
    # 首先搜索所有含有关键词的学术地图项目，忽略大小写，同时转换成一个List[dict]
    academic_tags = AcademicTagEntry.objects.filter(tag__tag_content__icontains=query).values(
        "person__name", "person__stu_grade", "tag__atype", "tag__tag_content",
    )
    academic_texts = AcademicTextEntry.objects.filter(content__icontains=query).values(
        "person__name", "person__stu_grade", "atype", "content",
    )
    academic_tags = [tag.update({
        "tag__atype": AcademicTag.AcademicTagType(tag["tag__atype"]).label
    }) for tag in academic_tags]     # 将choice的值更新为choice对应的名字
    academic_texts = [text.update({
        "atype": AcademicTextEntry.AcademicTextType(text["atype"]).label
    }) for text in academic_texts]   # 将choice的值更新为choice对应的名字

    # 然后根据tag/text对应的人，整合学术地图项目
    academic_map_dict = {}  # 整理一个以人名为key，以含有年级和学术地图项目的dict为value的dict
    for tag in academic_tags:
        person_name = tag["person__name"]
        academic_map_dict[person_name] = academic_map_dict.get(
            person_name, {"年级": tag["person__stu_grade"]}
        )
        academic_map_dict[person_name].update(
            {tag["tag__atype"]: tag["tag__content"]}
        )
    for text in academic_texts:
        person_name = text["person__name"]
        academic_map_dict[person_name] = academic_map_dict.get(
            person_name, {"年级": tag["person__stu_grade"]}
        )
        academic_map_dict[person_name].update({tag["atype"]: tag["content"]})
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = [
        dict({"姓名": key}, **value) for key, value in academic_map_dict.items()
    ]
    return academic_map_list
