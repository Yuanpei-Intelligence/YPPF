from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from utils.global_messages import wrong, succeed, message_url
from utils.http.dependency import HttpRequest, HttpResponse, JsonResponse, UserRequest
from utils.http.dependency import reverse, redirect
from generic.models import User

from app.config import CONFIG, GLOBAL_CONFIG
from app.log import logger
from app.view.base import ProfileTemplateView, ProfileJsonView

# TODO: 只保留和View类有关的部分
__all__ = [
    'login_required',
    'render',
    'wrong', 'succeed', 'message_url',
    'HttpRequest', 'HttpResponse', 'JsonResponse', 'UserRequest',
    'reverse', 'redirect',
    'User',
    'CONFIG', 'GLOBAL_CONFIG',
    'logger',
    'ProfileTemplateView', 'ProfileJsonView',
]
