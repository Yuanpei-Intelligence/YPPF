"""Website input for course selection and its prerequisite questionnaire."""
from django import forms
from django.utils.html import escape

from questionnaire.models import Question
from questionnaire.validators import validate_answer_body


class CourseSelectionForm(forms.Form):
    courseid = forms.IntegerField(min_value=1)
    action = forms.ChoiceField(choices=[('select', 'select'), ('cancel', 'cancel')])


class CourseSurveyForm(forms.Form):
    def __init__(self, survey, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.questions = list(survey.questions.prefetch_related('choices').all())
        for question in self.questions:
            options = [(str(choice.order), choice.text) for choice in question.choices.all()]
            params = dict(label=question.topic, required=question.required,
                          help_text=question.description)
            if question.type == Question.Type.SINGLE:
                field = forms.ChoiceField(
                    choices=options,
                    widget=forms.RadioSelect(attrs={'class': 'form-check-input'}), **params)
            elif question.type == Question.Type.MULTIPLE:
                field = forms.MultipleChoiceField(
                    choices=options,
                    widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}), **params)
            else:
                if question.type == Question.Type.RANKING:
                    params['help_text'] += ' 请按偏好顺序输入选项编号，以英文逗号分隔：' + '；'.join(
                        f'{order}: {text}' for order, text in options)
                field = forms.CharField(
                    widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}), **params)
            # Django's form renderer treats help_text as HTML; survey content is text.
            field.help_text = escape(field.help_text)
            self.fields[str(question.pk)] = field

    def clean(self):
        cleaned = super().clean()
        for question in self.questions:
            key = str(question.pk)
            body = cleaned.get(key)
            if isinstance(body, list):
                body = ','.join(body)
            if body:
                try:
                    validate_answer_body(question, body,
                                         {c.order for c in question.choices.all()})
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
            if key in cleaned:
                cleaned[key] = body or ''
        return cleaned
