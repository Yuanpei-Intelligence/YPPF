"""Create the two 2026 autumn tracking surveys from the reviewed Word content."""
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from generic.models import User
from questionnaire.models import Choice, Question, Survey


SURVEY_TITLES = (
    ('2026 秋元培在校生追踪问卷（新生版）', 11),
    ('2026 秋元培在校生追踪问卷', 21),
)
DATA_PATH = Path(__file__).resolve().parent.parent / 'raw_data' / 'student_tracking_survey_2026.json'
LOCK_NAME = 'yppf:create_student_tracking_questionnaire_2026'


def validate_tracking_survey_data(data):
    """Require ordered questions 1–21: twenty SINGLEs followed by one MULTIPLE.

    Validate the complete input before slicing out the freshman version, so an
    invalid regular-version question cannot leave a valid-looking partial import.
    """
    questions = data.get('questions') if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != 21:
        raise ValidationError('追踪问卷必须包含恰好 21 道题目。')
    for order, spec in enumerate(questions, start=1):
        if (not isinstance(spec, dict) or type(spec.get('order')) is not int
                or spec['order'] != order):
            raise ValidationError(
                f'追踪问卷题号必须按 1–21 连续排列且不重复：第 {order} 项题号无效。')
        expected_type = Question.Type.SINGLE if order <= 20 else Question.Type.MULTIPLE
        if spec.get('type') != expected_type:
            raise ValidationError(f'追踪问卷第 {order} 题类型必须为 {expected_type}。')


def create_student_tracking_surveys(creator_username, start, end, *, publish=False):
    """Create missing surveys atomically; never overwrite existing surveys.

    Titles are the release's config_template.json titles, not the local runtime
    configuration. The MySQL named lock serializes this command across creators
    because Survey.title has no unique constraint. It cannot serialize manual
    admin edits; pre-existing duplicate titles are rejected explicitly.
    """
    if start.tzinfo is not None or end.tzinfo is not None or start >= end:
        raise ValidationError('起止时间必须是不带时区的本地时间，且开始时间早于结束时间。')
    try:
        data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValidationError(
            '请先提供问卷数据文件 raw_data/student_tracking_survey_2026.json（不纳入版本控制）。'
        ) from exc
    validate_tracking_survey_data(data)
    if connection.vendor != 'mysql':
        raise ValidationError('此初始化命令需要项目的 MySQL 数据库。')
    with connection.cursor() as cursor:
        cursor.execute('SELECT GET_LOCK(%s, 0)', [LOCK_NAME])
        if cursor.fetchone()[0] != 1:
            raise ValidationError('已有创建追踪问卷的命令正在执行，请稍后重试。')
    try:
        with transaction.atomic():
            try:
                creator = User.objects.get(username=creator_username)
            except User.DoesNotExist as exc:
                raise ValidationError('指定的创建人账号不存在。') from exc
            result = []
            for title, question_count in SURVEY_TITLES:
                existing = list(Survey.objects.select_for_update().filter(title=title))
                if len(existing) > 1:
                    raise ValidationError('存在重名的追踪问卷，请先在管理后台处理。')
                if existing:
                    result.append((title, False))
                    continue
                survey = Survey.objects.create(
                    title=title, description=data['description'], creator=creator,
                    status=Survey.Status.PUBLISHED if publish else Survey.Status.DRAFT,
                    start_time=start, end_time=end,
                )
                for spec in data['questions'][:question_count]:
                    question = Question.objects.create(
                        survey=survey, order=spec['order'], topic=spec['topic'],
                        description=spec['description'], type=spec['type'],
                        required=spec['required'], min_choices=spec.get('min_choices', 1),
                        max_choices=spec.get('max_choices'),
                    )
                    Choice.objects.bulk_create([
                        Choice(question=question, order=order, text=text)
                        for order, text in enumerate(spec['choices'], start=1)
                    ])
                result.append((title, True))
        return result
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT RELEASE_LOCK(%s)', [LOCK_NAME])
