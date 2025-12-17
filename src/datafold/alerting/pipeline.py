"""Alerting pipeline for processing decisions and sending alerts."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from datafold.alerting.webhook import WebhookDelivery
from datafold.config import resolve_env_vars
from datafold.models import AlertState, DecisionStatus, EventType

if TYPE_CHECKING:
    from datafold.config import AlertingConfig, SourceConfig, WebhookConfig
    from datafold.models import Decision
    from datafold.storage.base import StateStore

logger = logging.getLogger(__name__)


class AlertingPipeline:
    """Pipeline for processing decisions and sending alerts."""

    def __init__(
        self,
        config: AlertingConfig,
        store: StateStore,
        agent_id: str,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.store = store
        self.agent_id = agent_id
        self.delivery = WebhookDelivery(dry_run=dry_run)
        self.dry_run = dry_run

    def process(
        self,
        source_config: SourceConfig,
        decision: Decision,
    ) -> dict[str, bool]:
        """Process a decision and send alerts to appropriate targets."""
        results: dict[str, bool] = {}

        for webhook in self.config.webhooks:
            event_type = self._get_event_type(decision)
            if not self._should_process_event(webhook, event_type):
                continue

            state = self.store.get_alert_state(source_config.name, webhook.name)

            if state is None:
                state = AlertState(
                    source_name=source_config.name,
                    target_name=webhook.name,
                    notified_status=DecisionStatus.UNKNOWN,
                    notified_reason_hash="",
                    last_change_at=datetime.now(timezone.utc),
                    last_sent_at=None,
                    cooldown_until=None,
                )

            if not self._should_alert(decision, state):
                logger.debug(
                    f"Skipping alert for {source_config.name} -> {webhook.name}: "
                    f"no state change or in cooldown"
                )
                results[webhook.name] = True
                continue

            success = self._send_alert(source_config, decision, event_type, webhook, state)
            results[webhook.name] = success

        return results

    def _get_event_type(self, decision: Decision) -> EventType:
        """Determine event type from decision status."""
        if decision.status == DecisionStatus.ANOMALY:
            return EventType.ANOMALY
        if decision.status == DecisionStatus.WARNING:
            return EventType.WARNING
        if decision.status == DecisionStatus.OK:
            return EventType.RECOVERY
        return EventType.INFO

    def _should_process_event(self, webhook: WebhookConfig, event_type: EventType) -> bool:
        """Check if webhook should receive this event type."""
        return event_type.value in webhook.events

    def _should_alert(self, decision: Decision, state: AlertState) -> bool:
        """Determine if alert should be sent based on state and cooldown."""
        now = datetime.now(timezone.utc)

        if state.cooldown_until and now < state.cooldown_until:
            return False

        if decision.status == state.notified_status and decision.reason_hash == state.notified_reason_hash:
            return False

        if state.notified_status == DecisionStatus.UNKNOWN:
            return True

        return True

    def _send_alert(
        self,
        source_config: SourceConfig,
        decision: Decision,
        event_type: EventType,
        webhook: WebhookConfig,
        state: AlertState,
    ) -> bool:
        """Send alert to webhook target."""
        payload = self.delivery.build_payload(
            source_name=source_config.name,
            source_type=source_config.type,
            event_type=event_type,
            decision_dict=decision.to_dict(),
            metrics=decision.metrics,
            baseline_dict=decision.baseline_summary.to_dict() if decision.baseline_summary else {},
            agent_id=self.agent_id,
        )

        if self.dry_run:
            logger.info(f"[DRY RUN] Would send {event_type.value} to {webhook.name}")
            return True

        resolved_url = resolve_env_vars(webhook.url)
        resolved_secret = resolve_env_vars(webhook.secret) if webhook.secret else None

        resolved_webhook = WebhookConfig(
            name=webhook.name,
            url=resolved_url,
            secret=resolved_secret,
            events=webhook.events,
            timeout_seconds=webhook.timeout_seconds,
        )

        result = self.delivery.deliver(payload, resolved_webhook)

        payload_hash = hashlib.sha256(payload.to_canonical_json().encode()).hexdigest()[:16]
        self.store.log_delivery(
            source_name=source_config.name,
            target_name=webhook.name,
            event_type=event_type.value,
            payload_hash=payload_hash,
            result=result,
        )

        if result.success:
            now = datetime.now(timezone.utc)
            new_state = AlertState(
                source_name=source_config.name,
                target_name=webhook.name,
                notified_status=decision.status,
                notified_reason_hash=decision.reason_hash,
                last_change_at=now,
                last_sent_at=now,
                cooldown_until=now + timedelta(minutes=self.config.cooldown_minutes),
            )
            self.store.set_alert_state(new_state)

            logger.info(
                f"Sent {event_type.value} alert for {source_config.name} to {webhook.name} "
                f"(status: {result.status_code}, latency: {result.latency_ms}ms)"
            )
        else:
            logger.warning(
                f"Failed to send alert for {source_config.name} to {webhook.name}: "
                f"{result.error} (attempts: {result.attempts})"
            )

        return result.success
