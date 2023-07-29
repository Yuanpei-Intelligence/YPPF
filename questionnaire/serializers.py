from rest_framework import serializers
from questionnaire.models import Survey, Question, Choice, AnswerText, AnswerSheet
# 先全serialize了，之后再说

class SurveySerializer(serializers.ModelSerializer):
    class Meta:
        model = Survey
        fields = 'all'


class AnswerSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerSheet
        fields = 'all'


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = 'all'


class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = 'all'


class AnswerTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerText
        fields = 'all'


# class UserSerializer(serializers.ModelSerializer):
    # class Meta:
        # model = User
        # fields = ['username', 'email', 'password']
