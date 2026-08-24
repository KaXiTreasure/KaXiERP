from django.db import connection
from django.http import JsonResponse
from django.views import View


class HealthView(View):
    def get(self, request):  # type: ignore[no-untyped-def]
        database = "unavailable"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                database = "ok" if cursor.fetchone() == (1,) else "unexpected"
        except Exception:
            pass

        status = 200 if database == "ok" else 503
        payload = {
            "status": "ok" if status == 200 else "degraded",
            "database": database,
        }
        return JsonResponse(payload, status=status)
