from rest_framework import serializers
from .models import Survey, Question, Choice, AnswerText, AnswerSheet

# 先全serialize了，之后再说

class SurveySerializer(serializers.ModelSerializer):
    class Meta:
        model = Survey
        fields = ['title', 'description', 'creator', 'create_time', 'is_published', 'start_time', 'end_time']


class AnswerSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerSheet
        fields = ['survey', 'creator', 'create_time']


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ['survey', 'order', 'topic', 'description', 'type']


class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ['question', 'order', 'text']


class AnswerTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerText
        fields = ['question', 'answersheet', 'body']
