from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.utils import timezone
from django.views.generic import TemplateView

from books.book_view import BookViewContextMixin
from books.models import Book, ReadingLog, ReadingProgress, ReadingStatus


class ReadingLogView(BookViewContextMixin, LoginRequiredMixin, TemplateView):
    template_name = "reading/log.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()

        month_param = self.request.GET.get("month")
        if month_param:
            try:
                parsed_month = datetime.strptime(month_param, "%Y-%m").date().replace(day=1)
                month_start = parsed_month
            except ValueError:
                month_start = today.replace(day=1)
        else:
            month_start = today.replace(day=1)

        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)

        ctx["currently_reading"] = (
            Book.objects.filter(reading_log__status=ReadingStatus.READING)
            .prefetch_related("authors")
            .select_related("reading_log", "review")
            .order_by("-reading_log__updated_at")
        )

        ctx["recent_progress"] = (
            ReadingProgress.objects.select_related("book", "reading_log")
            .prefetch_related(
                Prefetch("book__authors", to_attr="_author_list"),
            )
            .order_by("-logged_on", "-created_at")[:25]
        )

        ctx["finished_this_month"] = (
            Book.objects.filter(
                reading_log__status=ReadingStatus.FINISHED,
                reading_log__finished_at__gte=month_start,
                reading_log__finished_at__lt=next_month_start,
            )
            .prefetch_related("authors")
            .select_related("reading_log", "review")
            .order_by("-reading_log__finished_at")
        )

        ctx["month_label"] = month_start.strftime("%B %Y")
        ctx["month_param"] = month_start.strftime("%Y-%m")
        prev_month = (month_start - timedelta(days=1)).replace(day=1)
        ctx["prev_month_param"] = prev_month.strftime("%Y-%m")
        ctx["next_month_param"] = next_month_start.strftime("%Y-%m")
        ctx["show_next_month"] = next_month_start <= today.replace(day=1)

        journal_date = self.request.GET.get("date")
        ctx["journal_date"] = None
        ctx["journal_entries"] = None
        if journal_date:
            try:
                parsed = datetime.strptime(journal_date, "%Y-%m-%d").date()
                ctx["journal_date"] = parsed
                ctx["journal_entries"] = (
                    ReadingProgress.objects.select_related("book")
                    .filter(logged_on=parsed)
                    .order_by("-created_at")
                )
            except ValueError:
                pass
        return ctx
