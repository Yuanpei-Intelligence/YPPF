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
             一个条目名可能对应一个或多个内容（如参与多个科研项目等），因此条目名对应的value统一用list打包。
    :rtype: List[dict]
    """
    # 首先搜索所有含有关键词的公开的学术地图项目，忽略大小写，同时转换成QuerySet[dict]
    academic_tags = AcademicTagEntry.objects.filter( 
        tag__tag_content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values(
        "person__person_id_id", "person__name",   # person_id_id用于避免重名
        "person__stu_grade", "tag__atype", "tag__tag_content",
    )
    academic_texts = AcademicTextEntry.objects.filter(
        content__icontains=query,
        status=AcademicEntry.EntryStatus.PUBLIC,
    ).values(
        "person__person_id_id", "person__name",   # person_id_id用于避免重名
        "person__stu_grade", "atype", "content",
    )
    
    # 将choice的值更新为对应的选项名
    for tag in academic_tags:
        tag.update({"tag__atype": AcademicTag.AcademicTagType(tag["tag__atype"]).label})
    for text in academic_texts:
        text.update({"atype": AcademicTextEntry.AcademicTextType(text["atype"]).label})
        
    # 然后根据tag/text对应的人，整合学术地图项目
    academic_map_dict = {}  # 整理一个以person_id_id为key，以含有姓名、年级和学术地图项目的dict为value的dict
    for tag in academic_tags:
        person_id = tag["person__person_id_id"]
        tag_type = tag["tag__atype"]
        if not academic_map_dict.__contains__(person_id):
            academic_map_dict[person_id] = {
                "姓名": tag["person__name"],
                "年级": tag["person__stu_grade"],
            }
        if academic_map_dict[person_id].__contains__(tag_type):
            academic_map_dict[person_id][tag_type].append(tag["tag__tag_content"])
        else:
            academic_map_dict[person_id][tag_type] = [tag["tag__tag_content"],]
    
    for text in academic_texts:
        person_id = text["person__person_id_id"]
        text_type = text["atype"]
        if not academic_map_dict.__contains__(person_id):
            academic_map_dict[person_id] = {
                "姓名": text["person__name"],
                "年级": text["person__stu_grade"],
            }
        if academic_map_dict[person_id].__contains__(text_type):
            academic_map_dict[person_id][text_type].append(text["content"])
        else:
            academic_map_dict[person_id][text_type] = [text["content"],]
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = [value for value in academic_map_dict.values()]
    return academic_map_list
