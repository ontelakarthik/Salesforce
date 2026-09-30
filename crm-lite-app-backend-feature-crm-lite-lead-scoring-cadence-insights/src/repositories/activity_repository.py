"""Activity module repositories (§1/§11 of the API spec) — real, Postgres-
backed data access for every table this module owns. This is the central
"database logic" layer: developers building activity_service.py /
activity_routes.py call these classes directly and never open a Session
themselves.

Tables covered: communication, notification, audit_log, call_disposition.
"""
from functools import lru_cache

from src.models.activity_models import (
    AuditLog,
    CallDisposition,
    Communication,
    Notification,
    WhatsAppTemplate,
)
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository


class CallDispositionRepository(CrudRepository[CallDisposition]):
    model = CallDisposition


class WhatsAppTemplateRepository(SoftDeleteCrudRepository[WhatsAppTemplate]):
    model = WhatsAppTemplate

    def list_approved_active(self) -> list[WhatsAppTemplate]:
        """Only templates a send may actually use — see
        services/whatsapp_service.py, which re-checks this itself rather
        than trusting a caller filtered the list first."""
        return self.list(approval_status="APPROVED", is_active=True)


class CommunicationRepository(SoftDeleteCrudRepository[Communication]):
    model = Communication

    def list_for_account(self, account_id: str) -> list[Communication]:
        return self.list(account_id=account_id)

    def list_for_agreement(self, agreement_id: str) -> list[Communication]:
        return self.list(agreement_id=agreement_id)

    def list_for_lead(self, lead_id) -> list[Communication]:
        return self.list(lead_id=lead_id)

    def find_by_graph_message_id(self, graph_message_id: str) -> Communication | None:
        """Used by email-intake (crm_service.run_email_intake()) to make
        ingesting a given inbound message idempotent, independent of the
        IMAP \\Seen flag — see Communication.graph_message_id."""
        rows = self.list(graph_message_id=graph_message_id)
        return rows[0] if rows else None

    def find_by_provider_message_id(self, provider_message_id: str) -> Communication | None:
        """Used by crm_service.process_inbound_sms() to make ingesting a
        given inbound Twilio webhook call idempotent against Twilio's own
        retry behavior (it retries a webhook that doesn't answer 2xx
        quickly) — mirrors find_by_graph_message_id's role for inbound
        email above."""
        rows = self.list(provider_message_id=provider_message_id)
        return rows[0] if rows else None


class NotificationRepository(SoftDeleteCrudRepository[Notification]):
    model = Notification

    def list_unacknowledged(self) -> list[Notification]:
        return self.list(acknowledged=False)


class AuditLogRepository(CrudRepository[AuditLog]):
    """Hard-delete Protocol only in name — audit rows are meant to be
    immutable; callers should only ever use create()/list()/get() here."""
    model = AuditLog

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[AuditLog]:
        return self.list(entity_type=entity_type, entity_id=entity_id)


@lru_cache(maxsize=1)
def get_call_disposition_repository() -> CallDispositionRepository:
    return CallDispositionRepository()


@lru_cache(maxsize=1)
def get_whatsapp_template_repository() -> WhatsAppTemplateRepository:
    return WhatsAppTemplateRepository()


@lru_cache(maxsize=1)
def get_communication_repository() -> CommunicationRepository:
    return CommunicationRepository()


@lru_cache(maxsize=1)
def get_notification_repository() -> NotificationRepository:
    return NotificationRepository()


@lru_cache(maxsize=1)
def get_audit_log_repository() -> AuditLogRepository:
    return AuditLogRepository()
