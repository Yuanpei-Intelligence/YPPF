from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from questionnaire.models import Survey, Question, Choice, AnswerText, AnswerSheet
from questionnaire.validators import validate_answer_body

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
        fields = ['id', 'survey', 'creator', 'create_time', 'status']
        read_only_fields = ['id', 'create_time', 'status']


class AnswerTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerText
        fields = '__all__'

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        question = attrs.get(
            'question',
            instance.question if instance is not None else None,
        )
        answersheet = attrs.get(
            'answersheet',
            instance.answersheet if instance is not None else None,
        )
        body = (
            attrs.get(
                'body',
                instance.body if instance is not None else '',
            )
            or ''
        ).strip()

        if question.survey != answersheet.survey:
            raise serializers.ValidationError("问题与答卷不属于同一问卷！")

        if not body:
            raise serializers.ValidationError('答案不能为空！')

        try:
            validate_answer_body(question, body)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        return attrs
