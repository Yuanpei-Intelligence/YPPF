from rest_framework import serializers
from dormitory.models import Dormitory, DormitoryAssignment


class DormitorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Dormitory
        fields = '__all__'


class DormitoryAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryAssignment
        fields = '__all__'
        