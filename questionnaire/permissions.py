from rest_framework import permissions

from questionnaire.models import AnswerSheet

__all__ = [
    'IsTextOwnerOrAsker',
    'IsSheetOwnerOrAsker',
    'IsSurveyOwnerOrReadOnly',
    'IsQuestionOwnerOrReadOnly',
    'IsChoiceOwnerOrReadOnly',
]

class IsTextOwnerOrAsker(permissions.BasePermission):
    allowed_actions = {
        'answer_owner',
        'create',
        'destroy',
        'metadata',
        'partial_update',
        'retrieve',
        'survey_owner',
        'update',
    }

    def has_permission(self, request, view):
        return view.action in self.allowed_actions

    def has_object_permission(self, request, view, obj):
        sheet = obj.answersheet
        if request.user == sheet.creator:
            return (
                request.method in permissions.SAFE_METHODS
                or sheet.status == AnswerSheet.Status.DRAFT
            )
        return (
            request.method in permissions.SAFE_METHODS
            and sheet.status == AnswerSheet.Status.SUBMITTED
            and request.user == sheet.survey.creator
        )


class IsSheetOwnerOrAsker(permissions.BasePermission):
    allowed_actions = {
        'answer_owner',
        'create',
        'destroy',
        'metadata',
        'partial_update',
        'retrieve',
        'submit',
        'survey_owner',
        'update',
    }

    def has_permission(self, request, view):
        return view.action in self.allowed_actions

    def has_object_permission(self, request, view, obj):
        if request.user == obj.creator:
            if (
                request.method in permissions.SAFE_METHODS
                or view.action == 'submit'
            ):
                return True
            return obj.status == AnswerSheet.Status.DRAFT
        return (
            request.method in permissions.SAFE_METHODS
            and obj.status == AnswerSheet.Status.SUBMITTED
            and request.user == obj.survey.creator
        )


def check_owner_or_read_only(request, owner):
    return (request.user.is_staff 
            or request.method in permissions.SAFE_METHODS
            or request.user == owner)


class IsSurveyOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.creator
        return check_owner_or_read_only(request, owner)


class IsQuestionOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.survey.creator
        return check_owner_or_read_only(request, owner)


class IsChoiceOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.question.survey.creator
        return check_owner_or_read_only(request, owner)
