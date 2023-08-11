from rest_framework import viewsets

from dormitory.models import Dormitory, DormitoryAssignment
from dormitory.serializers import DormitorySerializer, DormitoryAssignmentSerializer


class DormitoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dormitory.objects.all()
    serializer_class = DormitorySerializer


class DormitoryAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DormitoryAssignment.objects.all()
    serializer_class = DormitoryAssignmentSerializer
