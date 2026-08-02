from django.core.exceptions import ValidationError

from questionnaire.models import Question


def validate_answer_body(question: Question, body: str) -> None:
    """Validate a non-empty answer against its question's choice rules."""
    if question.type == Question.Type.TEXT:
        return

    body_orders = [segment.strip() for segment in body.split(',') if segment.strip()]
    if not body_orders:
        raise ValidationError('选项答案不能为空！')

    try:
        parsed_orders = [int(order) for order in body_orders]
    except ValueError as exc:
        raise ValidationError('选项答案格式错误！') from exc

    valid_choice_orders = set(question.choices.values_list('order', flat=True))
    order_set = set(parsed_orders)
    if not order_set.issubset(valid_choice_orders):
        raise ValidationError('选项答案超出有效范围！')

    if question.type == Question.Type.SINGLE and len(parsed_orders) != 1:
        raise ValidationError('单选题必须且只能选择一个选项！')

    if question.type == Question.Type.MULTIPLE:
        if len(parsed_orders) != len(order_set):
            raise ValidationError('多选题不允许重复选项！')

        selected_count = len(order_set)
        if selected_count < question.min_choices:
            raise ValidationError(
                f'多选题至少需要选择 {question.min_choices} 个选项！')
        if (question.max_choices is not None
                and selected_count > question.max_choices):
            raise ValidationError(
                f'多选题最多只能选择 {question.max_choices} 个选项！')

    if question.type == Question.Type.RANKING:
        if len(parsed_orders) != len(order_set):
            raise ValidationError('排序题不允许重复选项！')
        if order_set != valid_choice_orders:
            raise ValidationError('排序题需要包含所有选项且仅包含一次！')
