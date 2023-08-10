from django.shortcuts import render
from rest_framework import viewsets
from dormitory.models import Dormitory, DormitoryAssignment
from dormitory.serializers import DormitorySerializer, DormitoryAssignmentSerializer


class DormitoryViewSet(viewsets.ModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ModelViewSet):
    queryset = DormitoryAssignment.objects.all()
    serializer_class = DormitoryAssignmentSerializer
