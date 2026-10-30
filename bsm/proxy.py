from django.conf import settings


def client_ip(request):
    peer = (request.META.get('REMOTE_ADDR') or '').strip()
    if peer in settings.BSM_TRUSTED_PROXIES:
        real = (request.META.get('HTTP_X_REAL_IP') or '').strip()
        if real:
            return real.split(',')[0].strip()
    return peer
