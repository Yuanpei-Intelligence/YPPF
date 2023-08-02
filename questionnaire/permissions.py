from rest_framework import permissions

def CheckOwner(request, owner, asker):
    return request.user.is_staff or request.user == owner or request.user == asker


class IsTextOwnerOrAsker(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.answersheet.creator
        asker = obj.question.survey.creator
        return CheckOwner(request, owner, asker)


class IsSheetOwnerOrAsker(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.creator
        asker = obj.survey.creator
        return CheckOwner(request, owner, asker)


def CheckOwnerOrReadOnly(request, owner):
    return (request.user.is_staff 
            or request.method in permissions.SAFE_METHODS
            or request.user == owner)


class IsSurveyOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.creator
        return CheckOwnerOrReadOnly(request, owner)


class IsQuestionOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.survey.creator
        return CheckOwnerOrReadOnly(request, owner)


class IsChoiceOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        owner = obj.question.survey.creator
        return CheckOwnerOrReadOnly(request, owner)