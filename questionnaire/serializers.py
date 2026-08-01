from rest_framework import serializers

from questionnaire.models import Survey, Question, Choice, AnswerText, AnswerSheet

__all__ = [
    'ChoiceSerializer',
    'QuestionSerializer',
    'SurveySerializer',
    'AnswerSheetSerializer',
    'AnswerTextSerializer',
]


class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = '__all__'


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = '__all__'


class SurveySerializer(serializers.ModelSerializer):
    creator = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Survey
        fields = '__all__'

    def validate(self, attrs):
        if attrs['start_time'] >= attrs['end_time']:
            raise serializers.ValidationError("起始时间不得晚于终止时间！")
        return attrs


class AnswerSheetSerializer(serializers.ModelSerializer):
    creator = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = AnswerSheet
        fields = '__all__'


class AnswerTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerText
        fields = '__all__'

    def validate(self, attrs):
        question = attrs['question']
        answersheet = attrs['answersheet']
        body = (attrs.get('body') or '').strip()

        if question.survey != answersheet.survey:
            raise serializers.ValidationError("问题与答卷不属于同一问卷！")

        if not body:
            raise serializers.ValidationError('答案不能为空！')

        if question.type == Question.Type.TEXT:
            return attrs

        valid_choice_orders = set(question.choices.values_list('order', flat=True))
        body_orders = [segment.strip() for segment in body.split(',') if segment.strip()]
        if not body_orders:
            raise serializers.ValidationError('选项答案不能为空！')

        try:
            parsed_orders = [int(order) for order in body_orders]
        except ValueError as exc:
            raise serializers.ValidationError('选项答案格式错误！') from exc

        order_set = set(parsed_orders)
        if not order_set.issubset(valid_choice_orders):
            raise serializers.ValidationError('选项答案超出有效范围！')

        if question.type == Question.Type.SINGLE and len(parsed_orders) != 1:
            raise serializers.ValidationError('单选题必须且只能选择一个选项！')

        if question.type == Question.Type.MULTIPLE:
            if len(parsed_orders) != len(order_set):
                raise serializers.ValidationError('多选题不允许重复选项！')

            selected_count = len(order_set)
            if question.min_choices is not None and selected_count < question.min_choices:
                raise serializers.ValidationError(
                    f'多选题至少需要选择 {question.min_choices} 个选项！')
            if question.max_choices is not None and selected_count > question.max_choices:
                raise serializers.ValidationError(
                    f'多选题最多只能选择 {question.max_choices} 个选项！')
        if question.type == Question.Type.RANKING:
            if len(parsed_orders) != len(order_set):
                raise serializers.ValidationError('排序题不允许重复选项！')
            if order_set != valid_choice_orders:
                raise serializers.ValidationError('排序题需要包含所有选项且仅包含一次！')

        return attrs
