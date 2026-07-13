from django import template

register = template.Library()


@register.filter
def status_badge(value):
    value = str(value or "").lower()
    if value in {"published", "completed", "ready", "connected"}:
        return "success"
    if value in {"failed", "error", "cancelled"}:
        return "danger"
    if value in {"processing", "rendering", "generating", "uploading"}:
        return "info"
    if value in {"pending", "queued", "retry", "scheduled"}:
        return "warning"
    return "secondary"


@register.filter
def initials(user):
    name = user.get_full_name().strip() if hasattr(user, "get_full_name") else ""
    if name:
        return "".join(part[0] for part in name.split()[:2]).upper()
    identifier = getattr(user, "email", "") or getattr(user, "username", "") or "U"
    return identifier[:2].upper()


@register.filter
def csv_keywords(value):
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(str(item) for item in value.keys())
    return str(value)
