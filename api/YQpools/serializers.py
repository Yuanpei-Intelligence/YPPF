""" 
Serializers for YQpools API.
"""
from rest_framework import serializers
from app.models import Pool, PoolItem


class PoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pool
        fields = '__all__'


class PoolItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoolItem
        fields = '__all__'


class PoolListSerializer(serializers.Serializer):
    pools_info = PoolSerializer(many=True)


class ExchangePurchaseSerializer(serializers.Serializer):
    """Serializer for exchange item purchase request."""

    poolitem_id = serializers.IntegerField(
        help_text="ID of the pool item to purchase")
    attributes = serializers.DictField(
        child=serializers.CharField(),
        default=dict,
        help_text="Exchange attributes if required"
    )


class LotteryPurchaseSerializer(serializers.Serializer):
    """Serializer for lottery ticket purchase request."""

    pool_id = serializers.IntegerField(help_text="ID of the lottery pool")


class RandomPurchaseSerializer(serializers.Serializer):
    """Serializer for random box purchase request."""

    pool_id = serializers.IntegerField(help_text="ID of the random pool")


class YQPointBalanceSerializer(serializers.Serializer):
    """Serializer for user's YQPoint balance."""

    YQpoint = serializers.IntegerField(help_text="Current YQPoint balance")
