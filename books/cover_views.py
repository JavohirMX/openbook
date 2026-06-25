from django.conf import settings
from django.http import FileResponse, Http404
from django.views import View

from books.covers import cover_content_type


class ServeCoverView(View):
    def get(self, request, path):
        covers_root = (settings.MEDIA_ROOT / "covers").resolve()
        file_path = (settings.MEDIA_ROOT / "covers" / path).resolve()

        if covers_root not in file_path.parents and file_path != covers_root:
            raise Http404
        if not file_path.is_file():
            raise Http404

        response = FileResponse(
            file_path.open("rb"),
            content_type=cover_content_type(str(file_path)),
        )
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
