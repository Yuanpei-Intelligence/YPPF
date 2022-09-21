from django.http import HttpRequest

def get_ip(request: HttpRequest) -> 'str | None':
    x_forwarded_for: str = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
