"""Tests for alerting pipeline."""

import hashlib
import hmac
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from driftguard.alerting.webhook import WebhookDelivery
from driftguard.config import WebhookConfig
from driftguard.models import EventType, WebhookPayload


@pytest.fixture
def webhook_config():
    return WebhookConfig(
        name="test-webhook",
        url="https://example.com/webhook",
        secret="test-secret",
        events=["anomaly", "recovery"],
        timeout_seconds=5,
    )


@pytest.fixture
def payload():
    return WebhookPayload(
        event_type=EventType.ANOMALY,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        source_name="test-source",
        source_type="sql",
        decision={"status": "ANOMALY", "reasons": []},
        metrics={"row_count": 100},
        agent_id="test-agent",
    )


class TestWebhookDelivery:
    def test_dry_run_returns_success(self, webhook_config, payload):
        delivery = WebhookDelivery(dry_run=True)

        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.attempts == 0

    def test_signature_generation(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        headers = delivery._build_headers(body, payload, webhook_config)

        assert "X-DriftGuard-Signature" in headers
        assert headers["X-DriftGuard-Signature"].startswith("sha256=")

    def test_signature_verification(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        signature = delivery._sign(body, webhook_config.secret)

        expected = hmac.new(
            webhook_config.secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected

    def test_headers_include_metadata(self, webhook_config, payload):
        delivery = WebhookDelivery()
        body = payload.to_canonical_json()

        headers = delivery._build_headers(body, payload, webhook_config)

        assert headers["Content-Type"] == "application/json"
        assert headers["X-DriftGuard-Event"] == "anomaly"
        assert "X-DriftGuard-Event-ID" in headers
        assert "X-DriftGuard-Timestamp" in headers

    @patch("driftguard.alerting.webhook.httpx.Client")
    def test_successful_delivery(self, mock_client_class, webhook_config, payload):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.status_code == 200
        assert result.attempts == 1

    @patch("driftguard.alerting.webhook.httpx.Client")
    def test_4xx_is_considered_success(self, mock_client_class, webhook_config, payload):
        mock_response = MagicMock()
        mock_response.status_code = 400

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.status_code == 400

    @patch("driftguard.alerting.webhook.httpx.Client")
    @patch("driftguard.alerting.webhook.time.sleep")
    def test_retry_on_5xx(self, mock_sleep, mock_client_class, webhook_config, payload):
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [mock_response_500, mock_response_200]
        mock_client_class.return_value = mock_client

        delivery = WebhookDelivery()
        result = delivery.deliver(payload, webhook_config)

        assert result.success is True
        assert result.attempts == 2


class TestWebhookPayload:
    def test_canonical_json_is_deterministic(self, payload):
        json1 = payload.to_canonical_json()
        json2 = payload.to_canonical_json()

        assert json1 == json2

    def test_canonical_json_has_no_whitespace(self, payload):
        json_str = payload.to_canonical_json()

        assert "\n" not in json_str
        assert ": " not in json_str

    def test_build_payload(self):
        delivery = WebhookDelivery()

        payload = delivery.build_payload(
            source_name="test",
            source_type="sql",
            event_type=EventType.ANOMALY,
            decision_dict={"status": "ANOMALY"},
            metrics={"row_count": 100},
            baseline_dict={"median": 1000},
            agent_id="agent-1",
        )

        assert payload.source_name == "test"
        assert payload.event_type == EventType.ANOMALY
        assert payload.version == "1"
