from rest_framework import serializers

from dormitory.models import Dormitory, DormitoryAssignment, Agreement


class DormitorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Dormitory
        fields = '__all__'


class DormitoryAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryAssignment
        fields = '__all__'


class AgreementSerializerFixme(serializers.ModelSerializer):
    class Meta:
        model = Agreement
        fields = ['id']


class AgreementSerializer(serializers.ModelSerializer):

    user = serializers.StringRelatedField()

    class Meta:
        model = Agreement
        fields = ['user', 'sign_time']
        read_only_fields = ['user', 'sign_time']
