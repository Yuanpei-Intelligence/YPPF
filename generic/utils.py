from django.db.models import QuerySet

from generic.models import User


__all__ = [
    'to_search_indices',
]


def to_search_indices(
    users: QuerySet[User],
    active: bool | None = True,
) -> list[dict[str, str]]:
    '''
    把用户对象转化为搜索索引

    Args:
    - users: 用户对象列表
    - active: 返回的用户是否为激活用户，为`None`时不筛选，默认为`True`

    Returns:
    - search_indices: 搜索索引列表，每个索引包含以下字段
        - id: 用户id（学号）
        - text: 用户名称
        - pinyin: 用户名称拼音
        - acronym: 用户名称缩写
    '''
    if active is not None:
        users = users.filter(active=active)
    index_values = users.values_list('username', 'name', 'pinyin', 'acronym')
    search_indices = []
    for user in index_values:
        uid, name, pinyin, acronym = user
        search_indices.append({
            'id': uid,
            'text': name + uid[:2],
            'pinyin': pinyin,
            'acronym': acronym,
        })
    return search_indices
