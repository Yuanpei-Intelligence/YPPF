from rest_framework import serializers
from generic.models import User
from questionnaire.models import Survey, Question, Choice, AnswerText, AnswerSheet

# 先全serialize了，之后再说
class ChoiceSerializer(serializers.ModelSerializer):

    class Meta:
        model = Choice
        fields = '__all__'


class QuestionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Question
        fields = '__all__'


class SurveySerializer(serializers.ModelSerializer):

    class Meta:
        model = Survey
        fields = '__all__'


class AnswerSheetSerializer(serializers.ModelSerializer):

    class Meta:
        model = AnswerSheet
        fields = '__all__'


class AnswerTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerText
        fields = '__all__'
        