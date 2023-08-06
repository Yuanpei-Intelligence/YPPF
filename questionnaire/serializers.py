from rest_framework import serializers
from generic.models import User
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
        if attrs['question'].survey != attrs['answersheet'].survey:
            raise serializers.ValidationError("问题与答卷不属于同一问卷！")
        return attrs
