from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

import requests
from django.utils import timezone

from books.models import ImportJob, ReadingLog, WebhookEndpoint

logger = logging.getLogger(__name__)

WEBHOOK_EVENT_READING_STATUS_CHANGED = "reading.status_changed"
WEBHOOK_EVENT_IMPORT_COMPLETED = "import.completed"

WEBHOOK_EVENTS = (
    WEBHOOK_EVENT_READING_STATUS_CHANGED,
    WEBHOOK_EVENT_IMPORT_COMPLETED,
)

MAX_DELIVERY_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)


def generate_webhook_secret() -> str:
    return secrets.token_hex(32)


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_payload(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event,
        "timestamp": timezone.now().isoformat(),
        "data": data,
    }


def deliver_webhook(endpoint: WebhookEndpoint, event: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "openbook-webhooks/0.1",
        "X-Openbook-Event": event,
        "X-Openbook-Signature": sign_payload(endpoint.secret, body),
    }

    for attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        try:
            response = requests.post(
                endpoint.url,
                data=body,
                headers=headers,
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                return True
            logger.warning(
                "Webhook %s delivery failed (HTTP %s) on attempt %s",
                endpoint.pk,
                response.status_code,
                attempt,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Webhook %s delivery error on attempt %s: %s",
                endpoint.pk,
                attempt,
                exc,
            )

        if attempt < MAX_DELIVERY_ATTEMPTS:
            time.sleep(RETRY_DELAYS_SECONDS[attempt - 1])

    return False


def emit_event(event: str, data: dict[str, Any]) -> int:
    payload = _build_payload(event, data)
    delivered = 0
    for endpoint in WebhookEndpoint.objects.filter(enabled=True):
        if event not in (endpoint.events or []):
            continue
        if deliver_webhook(endpoint, event, payload):
            delivered += 1
    return delivered


def emit_reading_status_changed(
    reading_log: ReadingLog,
    old_status: str,
    new_status: str,
) -> int:
    book = reading_log.book
    return emit_event(
        WEBHOOK_EVENT_READING_STATUS_CHANGED,
        {
            "book_id": str(book.pk),
            "title": book.title,
            "old_status": old_status,
            "new_status": new_status,
            "reading_log_id": reading_log.pk,
        },
    )


def emit_import_completed(job: ImportJob) -> int:
    return emit_event(
        WEBHOOK_EVENT_IMPORT_COMPLETED,
        {
            "job_id": str(job.pk),
            "kind": job.kind,
            "status": job.status,
            "result": job.result or {},
        },
    )
