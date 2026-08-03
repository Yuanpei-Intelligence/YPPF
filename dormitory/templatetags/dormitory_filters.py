from django import template

register = template.Library()


@register.filter
def contains(value, arg):
    """Check if a comma-separated string contains a specific item."""
    items = [item.strip() for item in value.split(',') if item.strip()]
    return str(arg) in items
