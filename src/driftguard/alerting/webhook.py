"""Webhook delivery with HMAC signature and retry logic."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from driftguard.models import DeliveryResult, EventType, WebhookPayload

if TYPE_CHECKING:
    from driftguard.config import WebhookConfig

RETRY_DELAYS = [1, 5, 15]
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class WebhookDelivery:
    """Webhook delivery with HMAC signature and retry logic."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def deliver(
        self,
        payload: WebhookPayload,
        config: WebhookConfig,
    ) -> DeliveryResult:
        """Deliver webhook with retries."""
        if self.dry_run:
            return DeliveryResult(
                success=True,
                status_code=200,
                latency_ms=0,
                attempts=0,
            )

        canonical_body = payload.to_canonical_json()
        headers = self._build_headers(canonical_body, payload, config)

        start_time = time.time()
        last_error: str | None = None
        last_status: int | None = None
        attempts = 0

        for attempt, delay in enumerate(RETRY_DELAYS + [0], 1):
            attempts = attempt
            try:
                with httpx.Client(timeout=config.timeout_seconds) as client:
                    response = client.post(
                        config.url,
                        content=canonical_body,
                        headers=headers,
                    )

                last_status = response.status_code

                if response.status_code < 400:
                    latency_ms = int((time.time() - start_time) * 1000)
                    return DeliveryResult(
                        success=True,
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        attempts=attempts,
                    )

                if response.status_code not in RETRYABLE_STATUS_CODES:
                    latency_ms = int((time.time() - start_time) * 1000)
                    return DeliveryResult(
                        success=True,
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        attempts=attempts,
                    )

                last_error = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                last_error = "Request timed out"
            except httpx.ConnectError as e:
                last_error = f"Connection failed: {str(e)[:200]}"
            except Exception as e:
                last_error = f"Unexpected error: {str(e)[:200]}"

            if delay > 0 and attempt < len(RETRY_DELAYS) + 1:
                time.sleep(delay)

        latency_ms = int((time.time() - start_time) * 1000)
        return DeliveryResult(
            success=False,
            status_code=last_status,
            error=last_error,
            latency_ms=latency_ms,
            attempts=attempts,
        )

    def _build_headers(
        self,
        body: str,
        payload: WebhookPayload,
        config: WebhookConfig,
    ) -> dict[str, str]:
        """Build request headers including HMAC signature."""
        headers = {
            "Content-Type": "application/json",
            "X-DriftGuard-Event": payload.event_type.value,
            "X-DriftGuard-Timestamp": payload.timestamp.isoformat(),
            "X-DriftGuard-Event-ID": payload.event_id,
        }

        if config.secret:
            signature = self._sign(body, config.secret)
            headers["X-DriftGuard-Signature"] = f"sha256={signature}"

        return headers

    def _sign(self, body: str, secret: str) -> str:
        """Create HMAC-SHA256 signature."""
        return hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def build_payload(
        self,
        source_name: str,
        source_type: str,
        event_type: EventType,
        decision_dict: dict[str, Any],
        metrics: dict[str, Any],
        baseline_dict: dict[str, Any],
        agent_id: str,
    ) -> WebhookPayload:
        """Build webhook payload."""
        return WebhookPayload(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source_name=source_name,
            source_type=source_type,
            decision=decision_dict,
            metrics=metrics,
            baseline_summary=baseline_dict,
            agent_id=agent_id,
        )
