from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
            " object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


def brand(request):
    catalog = settings.CATALOG_APP == "catalog"
    return {
        "is_catalog": catalog,
        "brand": "Catalog Manager",
        "admin_url": settings.ADMIN_URL,
    }
