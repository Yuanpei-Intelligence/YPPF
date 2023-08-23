from generic.models import User


def get_user_list_for_search(
    user_type: str,
    is_active: bool = True,
    exclude_user: User | None = None,
) -> list[dict[str, str]]:
    """
    Allowed user_type: 'Student', 'Teacher', 'Organization', 'Person'
    """
    query_set = User.objects.filter(is_active_user=is_active)
    if exclude_user is not None:
        query_set = query_set.exclude(username=exclude_user.username)
    if user_type == 'Person':
        query_set = query_set.filter(utype__in=[User.Type.STUDENT, User.Type.TEACHER])
    else:
        query_set = query_set.filter(utype=user_type)
    users = query_set.values_list('username', 'name', 'pinyin', 'acronym')
    search_data = []
    for user in users:
        uid, name, pinyin, acronym = user
        search_data.append({
            'id': uid,
            'text': name + uid[:2],
            'pinyin': pinyin,
            'acronym': acronym
        })
    return search_data
