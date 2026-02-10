import json

with open('rank2025.json', 'r', encoding='utf-8') as f:
    rank_data = json.load(f)

has_personal = 0
has_organization = 0
has_both = 0
has_neither = 0

for user_id, user_data in rank_data.items():
    personal = user_data.get('personal_most_frequent_co_appoint')
    organization = user_data.get('organization_most_frequent_co_appoint')
    
    has_p = bool(personal and isinstance(personal, dict) and personal.get('co_name'))
    has_o = bool(organization and isinstance(organization, dict) and organization.get('co_name'))
    
    if has_p and has_o:
        has_both += 1
    elif has_p:
        has_personal += 1
    elif has_o:
        has_organization += 1
    else:
        has_neither += 1

print(f'只有 personal: {has_personal} 人')
print(f'只有 organization: {has_organization} 人')
print(f'两者都有: {has_both} 人')
print(f'两者都没有: {has_neither} 人')
print(f'总计: {len(rank_data)} 人')
