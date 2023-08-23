from generic.models import User


def get_user_list_for_search(
    user_type: str,
    is_active: bool = True,
    exclude_user: User | None = None,
) -> list[dict[str, str]]:
    """
    Allowed user_type: 'Student', 'Teacher', 'Organization', 'Person'
    """
    query_set = User.objects.filter(is_active=is_active)
    if exclude_user is not None:
        query_set = query_set.exclude(username=exclude_user.username)
    if user_type == 'Person':
        query_set = query_set.filter(utype__in=['Student', 'Teacher'])
    else:
        query_set = query_set.filter(utype=user_type)
    ret = query_set.values('username', 'name', 'username', 'pinyin', 'acronym')
    return [
        {
            'id': user['username'],
            'text': user['name'] + user['username'][:2],
            'pinyin': user['pinyin'],
            'acronym': user['acronym']
        } for user in ret
    ]
