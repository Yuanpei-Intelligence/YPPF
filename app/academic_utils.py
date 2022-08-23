from app.utils_dependency import *
from app.models import (
    NaturalPerson,
    AcademicTag,
    AcademicEntry,
    AcademicTagEntry,
    AcademicTextEntry,
)
from app.constants import UTYPE_PER
from app.utils import get_person_or_org

from django.http import HttpRequest
from django.db.models import QuerySet

from typing import List
from collections import defaultdict

__all__ = [
    'get_search_results',
    'get_js_tag_list',
    'get_text_list',
    'get_hidden_text_input',
    'get_tag_status',
    'get_text_status',
    'update_tag_entry',
    'update_text_entry',
    'update_academic_map',
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
        tag_content = tag["tag__tag_content"]
        if not person_id in academic_map_dict:
            academic_map_dict[person_id] = defaultdict(list)
            academic_map_dict[person_id]["姓名"] = tag["person__name"]
            academic_map_dict[person_id]["年级"] = tag["person__stu_grade"]
        academic_map_dict[person_id][tag_type].append(tag_content)
    
    for text in academic_texts:
        person_id = text["person__person_id_id"]
        text_type = text["atype"]
        text_content = text["content"]
        if not person_id in academic_map_dict:
            academic_map_dict[person_id] = defaultdict(list)
            academic_map_dict[person_id]["姓名"] = text["person__name"]
            academic_map_dict[person_id]["年级"] = text["person__stu_grade"]
        academic_map_dict[person_id][text_type].append(text_content)
    
    # 最后将整理好的dict转换成前端利用的list
    academic_map_list = [value for value in academic_map_dict.values()]
    return academic_map_list


def get_js_tag_list(request: HttpRequest, type: AcademicTag.AcademicTagType, selected: bool) -> List[dict]:
    """
    用于前端显示支持搜索的专业/项目列表，返回形如[{id, content}]的列表。

    :param tags: http请求，用于读取学号
    :type tags: HttpRequest
    :param type: 标记所需的tag类型
    :type type: AcademicTag.AcademicTagType
    :param selected: 用于标记是否获取本人已有的专业项目，selected代表获取前端默认选中的项目
    :type tags: bool
    :return: 所有专业/项目组成的List[dict]，key值如上所述
    :rtype: List[dict]
    """
    if selected:
        me = get_person_or_org(request.user, UTYPE_PER)
        all_my_tags = AcademicTagEntry.objects.filter(person=me)
        tags = all_my_tags.filter(tag__atype=type).values('tag__id', 'tag__tag_content')
        js_list = [{"id": tag['tag__id'], "text": tag['tag__tag_content']} for tag in tags]
    else:
        tags = AcademicTag.objects.filter(atype=type)
        js_list = [{"id": tag.id, "text": tag.tag_content} for tag in tags]

    return js_list


def get_text_list(request: HttpRequest, type: AcademicTextEntry.AcademicTextType) -> List[str]:
    """
    获取自己的所有类型为type的TextEntry的内容列表。

    :param request: http请求
    :type request: HttpRequest
    :param type: TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    :return: 含有所有类型为type的TextEntry的content的list
    :rtype: List[str]
    """
    me = get_person_or_org(request.user, UTYPE_PER)
    all_my_text = AcademicTextEntry.objects.filter(person=me, atype=type)
    text_list = [text.content for text in all_my_text]
    return text_list


def get_hidden_text_input(contents: List[str]) -> str:
    """
    根据TextEntry的内容列表，生成前端hidden input的默认填写内容。

    :param contents: TextEntry的content组成的list
    :type contents: List[str]
    :return: 前端hidden input的默认填写内容
    :rtype: str
    """
    input_string = ""
    SEP_STR = "(END OF AN ENTRY)"
    for content in contents:
        input_string += content + SEP_STR
    return input_string


def get_tag_status(person: NaturalPerson, type: AcademicTag.AcademicTagType) -> str:
    """
    获取person的类型为type的TagEntry的公开状态。
    如果person没有类型为type的TagEntry，返回"公开"。

    :param person: 需要获取公开状态的人
    :type person: NaturalPerson
    :param type: TagEntry的类型
    :type type: AcademicTag.AcademicTagType
    :return: 公开状态，返回"公开/私密"
    :rtype: str
    """
    # 首先获取person所有的TagEntry
    all_tag_entries = AcademicTagEntry.objects.filter(person=person, tag__atype=type)
    
    if all_tag_entries.exists():
        # 因为所有类型为type的TagEntry的公开状态都一样，所以直接返回第一个entry的公开状态
        entry = all_tag_entries[0]
        return "私密" if entry.status == AcademicEntry.EntryStatus.PRIVATE else "公开"
    else:
        return "公开"


def get_text_status(person: NaturalPerson, type: AcademicTextEntry.AcademicTextType) -> str:
    """
    获取person的类型为type的TextEntry的公开状态。
    如果person没有类型为type的TextEntry，返回"公开"。

    :param person: 需要获取公开状态的人
    :type person: NaturalPerson
    :param type: TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    :return: 公开状态，返回"公开/私密"
    :rtype: str
    """
    # 首先获取person所有的类型为type的TextEntry
    all_text_entries = AcademicTextEntry.objects.filter(person=person, atype=type)
    
    if all_text_entries.exists():
        # 因为所有类型为type的TextEntry的公开状态都一样，所以直接返回第一个entry的公开状态
        entry = all_text_entries[0]
        return "私密" if entry.status == AcademicEntry.EntryStatus.PRIVATE else "公开"
    else:
        return "公开"


def update_tag_entry(person: NaturalPerson, 
                     tag_ids: List[str], 
                     status: bool,
                     type: AcademicTag.AcademicTagType) -> None:
    """
    更新TagEntry的工具函数。

    :param person: 需要更新学术地图的人
    :type person: NaturalPerson
    :param tag_ids: 含有一系列tag_id(未经类型转换)的list
    :type tag_ids: List[str]
    :param status: tag_ids对应的所有tags的公开状态
    :type status: bool
    :param type: tag_ids对应的所有tags的类型
    :type type: AcademicTag.AcademicTagType
    """
    # 首先获取person所有的TagEntry
    all_tag_entries = AcademicTagEntry.objects.filter(person=person, tag__atype=type)
    
    # 如果用户原有的TagEntry的id在tag_ids中未出现，则将其删除
    for entry in all_tag_entries:
        if not str(entry.tag.id) in tag_ids:
            entry.delete()
    
    for tag_id in tag_ids:
        tag_entry = all_tag_entries.filter(tag=AcademicTag.objects.get(id=int(tag_id)))
        if tag_entry.exists():
            # 用户已经有对应的entry，则更新entry的状态
            tag_entry = tag_entry[0]
            tag_entry.status = AcademicEntry.EntryStatus.PUBLIC if status == "公开" \
                           else AcademicEntry.EntryStatus.PRIVATE
            tag_entry.save()
        else:
            # 用户没有对应的entry，则根据用户填写的内容创建entry
            AcademicTagEntry.objects.create(
                person=person, tag=AcademicTag.objects.get(id=int(tag_id)),
                status=AcademicEntry.EntryStatus.PUBLIC if status == "公开" \
                    else AcademicEntry.EntryStatus.PRIVATE
            )


def update_text_entry(person: NaturalPerson, 
                      contents: List[str], 
                      status: bool, 
                      type: AcademicTextEntry.AcademicTextType) -> None:
    """
    更新TextEntry的工具函数。

    :param person: 需要更新学术地图的人
    :type person: NaturalPerson
    :param tag_ids: 含有一系列TextEntry的内容的list
    :type tag_ids: List[str]
    :param status: 该用户所有类型为type的TextEntry的公开状态
    :type status: bool
    :param type: contents对应的TextEntry的类型
    :type type: AcademicTextEntry.AcademicTextType
    """
    # 首先获取person所有的类型为type的TextEntry
    all_text_entries = AcademicTextEntry.objects.filter(person=person, atype=type)
    
    # 如果用户原有的TextEntry的内容在contents中没有出现，则将其删除
    for entry in all_text_entries:
        if not entry.content in contents:
            entry.delete()
    
    for content in contents:
        text_entry = all_text_entries.filter(content=content)
        if text_entry.exists():
            # 用户已经有对应的entry，则更新entry的状态
            text_entry = text_entry[0]
            text_entry.status = AcademicEntry.EntryStatus.PUBLIC if status == "公开" \
                           else AcademicEntry.EntryStatus.PRIVATE
            text_entry.save()
        else:
            # 用户没有对应的entry，则根据用户填写的内容创建entry
            AcademicTextEntry.objects.create(
                person=person, atype=type, content=content,
                status=AcademicEntry.EntryStatus.PUBLIC if status == "公开" \
                    else AcademicEntry.EntryStatus.PRIVATE
            )


def update_academic_map(request: HttpRequest) -> dict:
    """
    从前端获取填写的学术地图信息，并在数据库中进行更新，返回含有成功/错误信息的dict。

    :param request: http请求
    :type request: HttpRequest
    :return: 含成功/错误信息的dict，用于redirect后页面的前端展示
    :rtype: dict
    """
    # 首先从select栏获取所有选中的TagEntry
    majors = request.POST.getlist('majors')
    minors = request.POST.getlist('minors')
    double_degrees = request.POST.getlist('double_degrees')
    projects = request.POST.getlist('projects')
    
    # 然后从其余栏目获取即将更新的TextEntry
    SEP_STR = "(END OF AN ENTRY)"
    scientific_research = request.POST['scientific_research'].split(SEP_STR)[:-1]
    challenge_cup = request.POST['challenge_cup'].split(SEP_STR)[:-1]
    internship = request.POST['internship'].split(SEP_STR)[:-1]
    scientific_direction = request.POST['scientific_direction'].split(SEP_STR)[:-1]
    graduation = request.POST['graduation'].split(SEP_STR)[:-1]
    
    # 对上述五个列表中的所有填写项目，检查是否超过数据库要求的字数上限
    max_length_of = lambda items: max([len(item) for item in items]) if len(items) > 0 else 0
    MAX_LENGTH = 4095
    if max_length_of(scientific_research) > MAX_LENGTH:
        return wrong("您设置的本科生科研经历太长啦！请修改~")
    elif max_length_of(challenge_cup) > MAX_LENGTH:
        return wrong("您设置的挑战杯经历太长啦！请修改~")
    elif max_length_of(internship) > MAX_LENGTH:
        return wrong("您设置的实习经历太长啦！请修改~")
    elif max_length_of(scientific_direction) > MAX_LENGTH:
        return wrong("您设置的科研方向太长啦！请修改~")
    elif max_length_of(graduation) > MAX_LENGTH:
        return wrong("您设置的毕业去向太长啦！请修改~")
    
    # 从checkbox获取所有栏目的公开状态
    major_status = request.POST['major_status']
    minor_status = request.POST['minor_status']
    double_degree_status = request.POST['double_degree_status']
    project_status = request.POST['project_status']
    scientific_research_status = request.POST['scientific_research_status']
    challenge_cup_status = request.POST['challenge_cup_status']
    internship_status = request.POST['internship_status']
    scientific_direction_status = request.POST['scientific_direction_status']
    graduation_status = request.POST['graduation_status']
    
    # 获取前端信息后对数据库进行更新
    with transaction.atomic():
        me = get_person_or_org(request.user, UTYPE_PER)
        
        # 首先更新自己的TagEntry
        update_tag_entry(me, majors, major_status, AcademicTag.AcademicTagType.MAJOR)
        update_tag_entry(me, minors, minor_status, AcademicTag.AcademicTagType.MINOR)
        update_tag_entry(me, double_degrees, double_degree_status, 
                         AcademicTag.AcademicTagType.DOUBLE_DEGREE)
        update_tag_entry(me, projects, project_status, AcademicTag.AcademicTagType.PROJECT)
        
        # 然后更新自己的TextEntry
        update_text_entry(
            me, scientific_research, scientific_research_status, 
            AcademicTextEntry.AcademicTextType.SCIENTIFIC_RESEARCH
        )
        update_text_entry(
            me, challenge_cup, challenge_cup_status, 
            AcademicTextEntry.AcademicTextType.CHALLENGE_CUP
        )
        update_text_entry(
            me, internship, internship_status, 
            AcademicTextEntry.AcademicTextType.INTERNSHIP
        )
        update_text_entry(
            me, scientific_direction, scientific_direction_status, 
            AcademicTextEntry.AcademicTextType.SCIENTIFIC_DIRECTION
        )
        update_text_entry(
            me, graduation, graduation_status, 
            AcademicTextEntry.AcademicTextType.GRADUATION
        )
    
    return succeed("学术地图修改成功！")
