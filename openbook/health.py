from django.db import connection
from django.http import JsonResponse
from django.views import View


class HealthCheckView(View):
    def get(self, request):
        db_ok = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                db_ok = True
        except Exception:
            pass

        status = 200 if db_ok else 503
        return JsonResponse(
            {"status": "ok" if db_ok else "error", "database": db_ok},
            status=status,
        )
