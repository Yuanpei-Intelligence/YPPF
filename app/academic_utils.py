from app.utils_dependency import *
from app.models import (
    AcademicTag,
    AcademicEntry,
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
    :return: 搜索结果list，元素为dict，包含key：姓名、年级、条目内容中包含关键词的条目名。
             一个条目名可能对应一个或多个内容（如参与多个科研项目等），因此条目名对应的value统一用tuple打包。
    :rtype: List[dict]
    """
    # 首先搜索所有含有关键词的公开的学术地图项目，忽略大小写，同时转换成QuerySet[dict]
    academic_tags = AcademicTagEntry.objects.filter( 
        tag__tag_content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values("person__name", "person__stu_grade", "tag__atype", "tag__tag_content")
    academic_texts = AcademicTextEntry.objects.filter(
        content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values("person__name", "person__stu_grade", "atype", "content")
    
    # 将choice的值更新为对应的选项名
    for tag in academic_tags:
        tag.update({"tag__atype": AcademicTag.AcademicTagType(tag["tag__atype"]).label})
    for text in academic_texts:
        text.update({"atype": AcademicTextEntry.AcademicTextType(text["atype"]).label})
        
    # 然后根据tag/text对应的人，整合学术地图项目
    academic_map_dict = {}  # 整理一个以人名为key，以含有年级和学术地图项目的dict为value的dict
    for tag in academic_tags:
        person_name = tag["person__name"]
        academic_map_dict[person_name] = academic_map_dict.get(
            person_name, {"年级": tag["person__stu_grade"]}
        )
        entry = academic_map_dict[person_name].get(tag["tag__atype"], tuple())
        academic_map_dict[person_name][tag["tag__atype"]] = entry + (tag["tag__tag_content"],)
    for text in academic_texts:
        person_name = text["person__name"]
        academic_map_dict[person_name] = academic_map_dict.get(
            person_name, {"年级": text["person__stu_grade"]}
        )
        entry = academic_map_dict[person_name].get(text["atype"], tuple())
        academic_map_dict[person_name][text["atype"]] = entry + (text["content"],)
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = [
        dict({"姓名": key}, **value) for key, value in academic_map_dict.items()
    ]
    return academic_map_list
