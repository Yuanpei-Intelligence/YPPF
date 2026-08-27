"""Serializers for generic mini-program APIs."""

from rest_framework import serializers


class CarouselItemSerializer(serializers.Serializer):
    """One homepage carousel item."""

    image = serializers.CharField(help_text="Image URL")
    redirect_url = serializers.CharField(help_text="Click-through URL")


class CarouselResponseSerializer(serializers.Serializer):
    """Homepage carousel response."""

    items = CarouselItemSerializer(many=True)
