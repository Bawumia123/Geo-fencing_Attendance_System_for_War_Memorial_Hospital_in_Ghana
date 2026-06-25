from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Allow dict[key] lookups in templates."""
    return dictionary.get(key)
