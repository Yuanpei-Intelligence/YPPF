from datetime import datetime

from generic.models import User

def calculate_enrollment_years(goal: int):
    '''
    传入目标入学年份数，返回满足的、未毕业的学生User列表。
    示例：今年是2023年，我希望返回入学第二年的user，即查找username前两位为22的user
    仅限秋季学期开始后使用。
    '''
    current_year = datetime.now().year - 2000 - goal + 1
    user = User.objects.filter(utype=User.Type.STUDENT, active=True, username__startswith=str(current_year))

    return list(user)