from generic.models import User
from semester.api import current_semester
from utils.marker import need_refactor


@need_refactor
def get_students_by_grade(grade: int) -> list[User]:
    '''
    传入目标入学年份数，返回满足的、未毕业的学生User列表。
    示例：今年是2023年，我希望返回入学第二年的user，即查找username前两位为22的user
    仅限秋季学期开始后使用。
    '''

    semester_year = current_semester().year
    goal_year = semester_year - 2000 - grade + 1
    user = User.objects.filter(
        utype=User.Type.STUDENT, active=True, username__startswith=str(goal_year))
    return list(user)
