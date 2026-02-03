""" 
Serializers for YQpools API.
"""
from rest_framework import serializers
from app.models import Pool, PoolItem


class PoolSerializer(serializers.ModelSerializer):
    """Serializer for Pool model with computed fields."""
    # Computed fields from get_pools_and_items
    status = serializers.IntegerField(read_only=True)
    capacity = serializers.IntegerField(read_only=True, required=False)
    items = serializers.ListField(
        child=serializers.DictField(), read_only=True, required=False)
    my_entry_time = serializers.IntegerField(read_only=True, required=False)
    records_num = serializers.IntegerField(read_only=True, required=False)
    results = serializers.DictField(
        read_only=True, required=False, allow_null=True)

    class Meta:
        model = Pool
        fields = '__all__'

    def to_representation(self, instance):
        """Handle both Pool instances and dictionaries from get_pools_and_items."""
        # If instance is a dict (from get_pools_and_items), preserve ALL fields including computed ones
        if isinstance(instance, dict):
            # Start with all fields from the dict to preserve computed fields like 'items', 'status', etc.
            # Make a copy to avoid modifying the original
            result = dict(instance)

            # Convert any ImageField objects in the dict to strings
            for key, value in result.items():
                if hasattr(value, 'name') and hasattr(value, 'storage'):  # ImageField
                    result[key] = str(value) if value else ""
                elif isinstance(value, dict):
                    # Recursively handle nested dicts (like results)
                    result[key] = self._convert_imagefields_in_dict(value)
                elif isinstance(value, list):
                    # Handle lists (like items, winners)
                    result[key] = [
                        self._convert_imagefields_in_dict(
                            item) if isinstance(item, dict) else item
                        for item in value
                    ]
            return result

        # Otherwise, serialize the Pool instance normally
        ret = super().to_representation(instance)
        return ret

    def _convert_imagefields_in_dict(self, d):
        """Helper to convert ImageField objects to strings in nested dictionaries."""
        result = {}
        for key, value in d.items():
            if hasattr(value, 'name') and hasattr(value, 'storage'):  # ImageField
                result[key] = str(value) if value else ""
            elif isinstance(value, dict):
                result[key] = self._convert_imagefields_in_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self._convert_imagefields_in_dict(
                        item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result


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
