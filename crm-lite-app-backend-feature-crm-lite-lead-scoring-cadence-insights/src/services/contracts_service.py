"""Contracts module business logic (§1/§8 of the API spec) — Agreements
(NDA/MSA/SOW core). IMPLEMENTED.

Rules enforced:
- create   : starts in DRAFT; sla_due_at computed from agreement_type.default_sla_hours.
- update   : status may not be set to SIGNED or SUPERSEDED directly — use
             /sign and /supersede, which apply their own rules.
- sign     : blocked if already SIGNED or any terminal status (EXPIRED/SUPERSEDED);
             expiry_date must be after effective_date if both are set; stamps
             signed_at/signed_by_employee_id and moves status -> SIGNED.
- supersede: creates a new DRAFT agreement (same account/type, optionally
             overridden title/dates) linked via supersedes_agreement_id, and
             marks the original SUPERSEDED.

repositories.contracts_repository.AgreementRepository already implements
full CRUD plus has_signed_sow()/count_active_for_account() — other modules'
rules (e.g. crm_service's promote/delete) call those directly.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.models import contracts_models
from src.models.enums import AgreementStatus
from src.repositories._base import resolve_lookup_id, resolve_lookup_row
from src.repositories.activity_repository import get_notification_repository
from src.repositories.admin_repository import get_employee_repository
from src.repositories.contracts_repository import (
    AgreementClauseRepository,
    AgreementDocumentRepository,
    AgreementNoteRepository,
    AgreementRepository,
    AgreementReviewRepository,
    get_agreement_status_repository,
    get_agreement_type_repository,
)
from src.repositories.crm_repository import AccountRepository
from src.services.admin_service import employee_ids_with_role, verified_employee_uuid
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError
from src.utils.scope import owned_account_ids, require_account_scope
from src.utils.security import CurrentUser

# only /sign, /supersede may move an agreement to these statuses
_LOCKED_STATUSES = {AgreementStatus.SIGNED.value, AgreementStatus.SUPERSEDED.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _type_row(code: str):
    return resolve_lookup_row(get_agreement_type_repository(), code, "AGREEMENT_TYPE_NOT_FOUND",
                              "agreement_type")


def _status_id(code: str) -> int:
    return resolve_lookup_id(get_agreement_status_repository(), code, "AGREEMENT_STATUS_NOT_FOUND",
                             "status")


def _lookup_maps() -> tuple[dict[int, str], dict[int, str]]:
    """{agreement_type.id: code}, {agreement_status.id: code} — built once
    per list/mapper call instead of resolving each row's type/status via a
    fresh repository round-trip (an N+1 against two tiny, rarely-changing
    lookup tables)."""
    return (
        {t.id: t.code for t in get_agreement_type_repository().list()},
        {s.id: s.code for s in get_agreement_status_repository().list()},
    )


def _out(row, type_map: dict[int, str] | None = None,
         status_map: dict[int, str] | None = None) -> contracts_models.AgreementOut:
    if type_map is None or status_map is None:
        type_map, status_map = _lookup_maps()
    return contracts_models.AgreementOut(
        id=row.id, account_id=row.account_id, agreement_type=type_map[row.agreement_type_id],
        status=status_map[row.agreement_status_id],
        title=row.title, initiated_by_employee_id=row.initiated_by_employee_id,
        effective_date=row.effective_date,
        expiry_date=row.expiry_date, signed_at=row.signed_at,
        signed_by_employee_id=row.signed_by_employee_id,
        supersedes_agreement_id=row.supersedes_agreement_id, sla_due_at=row.sla_due_at,
        sla_breached_at=row.sla_breached_at, sharepoint_folder_url=row.sharepoint_folder_url,
        contract_term_months=row.contract_term_months,
        owner_expiration_notice_days=row.owner_expiration_notice_days,
        customer_signed_contact_id=row.customer_signed_contact_id,
        customer_signed_title=row.customer_signed_title, customer_signed_date=row.customer_signed_date,
        special_terms=row.special_terms, billing_address=row.billing_address,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


def agreement_out(row) -> contracts_models.AgreementOut:
    """Public mapper for other modules that need an AgreementOut without
    reaching into this module's private `_out()` — e.g. project_service's
    project<->SOW linkage."""
    return _out(row)


def _get_or_404(repo: AgreementRepository, aid: str):
    row = repo.get(aid)
    if row is None:
        raise DomainError("AGREEMENT_NOT_FOUND", f"No agreement '{aid}'.", 404)
    return row


def _validate_dates(effective_date, expiry_date) -> None:
    if effective_date and expiry_date and expiry_date <= effective_date:
        raise DomainError("INVALID_DATE_RANGE", "expiry_date must be after effective_date.", 422)


def _employee_name(employee_id) -> str:
    if employee_id is None:
        return "Someone"
    employee = get_employee_repository().get(employee_id)
    return employee.full_name if employee is not None else "Someone"


def _notify(user: CurrentUser, recipient_ids, agreement, notification_type: str, message: str) -> None:
    if not recipient_ids:
        return
    repo = get_notification_repository()
    now = _now()
    for recipient_id in recipient_ids:
        repo.create(
            agreement_id=agreement.id, account_id=agreement.account_id,
            recipient_employee_id=recipient_id, notification_type=notification_type,
            severity="INFO", message=message, sent_at=now,
            created_by=user.employee_id, updated_by=user.employee_id,
        )


# --- Agreements ----------------------------------------------------------------
@handle_errors("list agreements")
def list_agreements(user: CurrentUser, account_repo: AccountRepository,
                    repo: AgreementRepository) -> list[contracts_models.AgreementOut]:
    type_map, status_map = _lookup_maps()
    owned = owned_account_ids(user, account_repo)
    rows = [r for r in repo.list() if owned is None or r.account_id in owned]
    return [_out(r, type_map, status_map) for r in sorted(rows, key=lambda r: r.id)]


@handle_errors("get agreement")
def get_agreement(user: CurrentUser, account_repo: AccountRepository,
                  repo: AgreementRepository, aid: str) -> contracts_models.AgreementOut:
    row = _get_or_404(repo, aid)
    require_account_scope(user, account_repo, row.account_id, "Agreement is outside your data scope.")
    return _out(row)


@handle_errors("create agreement")
def create_agreement(user: CurrentUser, account_repo: AccountRepository,
                     repo: AgreementRepository,
                     payload: contracts_models.AgreementCreate) -> contracts_models.AgreementOut:
    if account_repo.get(payload.account_id) is None:
        raise DomainError("ACCOUNT_NOT_FOUND", f"No account '{payload.account_id}'.", 404)
    _validate_dates(payload.effective_date, payload.expiry_date)
    atype = _type_row(payload.agreement_type)
    now = _now()
    sla_due_at = now + timedelta(hours=atype.default_sla_hours) if atype.default_sla_hours else None
    new_id = repo.next_id()
    row = repo.create(
        id=new_id, account_id=payload.account_id, agreement_type_id=atype.id,
        agreement_status_id=_status_id(AgreementStatus.DRAFT.value), title=payload.title,
        initiated_by_employee_id=verified_employee_uuid(user), effective_date=payload.effective_date,
        expiry_date=payload.expiry_date, sla_due_at=sla_due_at,
        sharepoint_folder_url=payload.sharepoint_folder_url,
        contract_term_months=payload.contract_term_months,
        owner_expiration_notice_days=payload.owner_expiration_notice_days,
        customer_signed_contact_id=payload.customer_signed_contact_id,
        customer_signed_title=payload.customer_signed_title,
        customer_signed_date=payload.customer_signed_date,
        special_terms=payload.special_terms, billing_address=payload.billing_address,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _out(row)


@handle_errors("update agreement")
def update_agreement(user: CurrentUser, repo: AgreementRepository, aid: str,
                     payload: contracts_models.AgreementUpdate) -> contracts_models.AgreementOut:
    row = _get_or_404(repo, aid)
    _validate_dates(payload.effective_date or row.effective_date,
                    payload.expiry_date or row.expiry_date)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        code = changes.pop("status").upper()
        if code in _LOCKED_STATUSES:
            raise DomainError(
                "USE_DEDICATED_ENDPOINT",
                f"Use /sign or /supersede to move an agreement to {code}.", 422)
        changes["agreement_status_id"] = _status_id(code)
    changes["updated_by"] = user.employee_id
    updated = repo.update(aid, **changes)
    return _out(updated)


@handle_errors("delete agreement")
def delete_agreement(repo: AgreementRepository, aid: str) -> None:
    _get_or_404(repo, aid)
    repo.delete(aid)


@handle_errors("send agreement for signature")
def send_for_signature(user: CurrentUser, account_repo: AccountRepository,
                       repo: AgreementRepository, aid: str) -> contracts_models.AgreementOut:
    row = _get_or_404(repo, aid)
    current_status = get_agreement_status_repository().get(row.agreement_status_id)
    if current_status.code == AgreementStatus.SIGNED.value:
        raise DomainError("ALREADY_SIGNED", "Agreement is already SIGNED.", 409)
    if current_status.is_terminal:
        raise DomainError("AGREEMENT_TERMINAL", f"Agreement is {current_status.code}.", 409)
    updated = repo.update(
        aid, agreement_status_id=_status_id(AgreementStatus.SENT.value), updated_by=user.employee_id)

    account = account_repo.get(row.account_id)
    atype = get_agreement_type_repository().get(row.agreement_type_id)
    ae_name = _employee_name(verified_employee_uuid(user))
    account_name = account.legal_name if account is not None else row.account_id
    message = f"{ae_name} sent the {atype.code} for {account_name} for signature."
    _notify(user, employee_ids_with_role("LEADERSHIP"), updated,
           "AGREEMENT_PENDING_SIGNATURE", message)
    return _out(updated)


@handle_errors("sign agreement")
def sign_agreement(user: CurrentUser, account_repo: AccountRepository, repo: AgreementRepository,
                   aid: str) -> contracts_models.AgreementOut:
    row = _get_or_404(repo, aid)
    current_status = get_agreement_status_repository().get(row.agreement_status_id)
    if current_status.code == AgreementStatus.SIGNED.value:
        raise DomainError("ALREADY_SIGNED", "Agreement is already SIGNED.", 409)
    if current_status.is_terminal:
        raise DomainError("AGREEMENT_TERMINAL", f"Agreement is {current_status.code}.", 409)
    _validate_dates(row.effective_date, row.expiry_date)
    updated = repo.update(
        aid, agreement_status_id=_status_id(AgreementStatus.SIGNED.value), signed_at=_now(),
        signed_by_employee_id=verified_employee_uuid(user),
        updated_by=user.employee_id,
    )

    if row.initiated_by_employee_id is not None:
        account = account_repo.get(row.account_id)
        atype = get_agreement_type_repository().get(row.agreement_type_id)
        signer_name = _employee_name(verified_employee_uuid(user))
        account_name = account.legal_name if account is not None else row.account_id
        message = f"{signer_name} signed the {atype.code} for {account_name}."
        _notify(user, [row.initiated_by_employee_id], updated, "AGREEMENT_SIGNED", message)
    return _out(updated)


@handle_errors("supersede agreement")
def supersede_agreement(user: CurrentUser, repo: AgreementRepository, aid: str,
                        payload: contracts_models.AgreementSupersedeRequest,
                        ) -> contracts_models.AgreementOut:
    old = _get_or_404(repo, aid)
    new_id = repo.next_id()
    new_row = repo.create(
        id=new_id, account_id=old.account_id, agreement_type_id=old.agreement_type_id,
        agreement_status_id=_status_id(AgreementStatus.DRAFT.value),
        title=payload.title or old.title, initiated_by_employee_id=verified_employee_uuid(user),
        effective_date=payload.effective_date or old.effective_date,
        expiry_date=payload.expiry_date or old.expiry_date,
        supersedes_agreement_id=old.id,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    repo.update(old.id, agreement_status_id=_status_id(AgreementStatus.SUPERSEDED.value),
               updated_by=user.employee_id)
    return _out(new_row)


# --- Clauses ---------------------------------------------------------------------
def _clause_out(row) -> contracts_models.AgreementClauseOut:
    return contracts_models.AgreementClauseOut(
        id=row.id, agreement_id=row.agreement_id, section_ref=row.section_ref,
        clause_text=row.clause_text, is_flagged=row.is_flagged, flag_reason=row.flag_reason,
        policy_ref=row.policy_ref, resolution_status=row.resolution_status,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list clauses")
def list_clauses(user: CurrentUser, account_repo: AccountRepository,
                 agreement_repo: AgreementRepository, clause_repo: AgreementClauseRepository,
                 aid: str) -> list[contracts_models.AgreementClauseOut]:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.")
    return [_clause_out(c) for c in clause_repo.list_for_agreement(aid)]


@handle_errors("add clause")
def add_clause(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
              clause_repo: AgreementClauseRepository, aid: str,
              payload: contracts_models.AgreementClauseCreate) -> contracts_models.AgreementClauseOut:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    row = clause_repo.create(
        agreement_id=aid, section_ref=payload.section_ref, clause_text=payload.clause_text,
        policy_ref=payload.policy_ref, created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _clause_out(row)


@handle_errors("update clause")
def update_clause(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
                  clause_repo: AgreementClauseRepository, clause_id: UUID,
                  payload: contracts_models.AgreementClauseUpdate) -> contracts_models.AgreementClauseOut:
    clause = clause_repo.get(clause_id)
    if clause is None:
        raise DomainError("CLAUSE_NOT_FOUND", f"No clause '{clause_id}'.", 404)
    agreement = _get_or_404(agreement_repo, clause.agreement_id)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    changes = payload.model_dump(exclude_unset=True)
    changes["updated_by"] = user.employee_id
    return _clause_out(clause_repo.update(clause_id, **changes))


# --- Documents -------------------------------------------------------------------
def _document_out(row) -> contracts_models.AgreementDocumentOut:
    return contracts_models.AgreementDocumentOut(
        id=row.id, agreement_id=row.agreement_id, version_number=row.version_number,
        sharepoint_item_id=row.sharepoint_item_id, sharepoint_url=row.sharepoint_url,
        filename=row.filename, content_type=row.content_type, size_bytes=row.size_bytes,
        uploaded_by_source=row.uploaded_by_source, uploaded_at=row.uploaded_at,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list agreement documents")
def list_agreement_documents(user: CurrentUser, account_repo: AccountRepository,
                             agreement_repo: AgreementRepository,
                             document_repo: AgreementDocumentRepository,
                             aid: str) -> list[contracts_models.AgreementDocumentOut]:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.")
    return [_document_out(d) for d in document_repo.list_for_agreement(aid)]


@handle_errors("add agreement document")
def add_agreement_document(user: CurrentUser, account_repo: AccountRepository,
                           agreement_repo: AgreementRepository,
                           document_repo: AgreementDocumentRepository, aid: str,
                           payload: contracts_models.AgreementDocumentCreate,
                           ) -> contracts_models.AgreementDocumentOut:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    existing = document_repo.list_for_agreement(aid)
    next_version = max((d.version_number for d in existing), default=0) + 1
    row = document_repo.create(
        agreement_id=aid, version_number=next_version, filename=payload.filename,
        content_type=payload.content_type, size_bytes=payload.size_bytes,
        sharepoint_item_id=payload.sharepoint_item_id, sharepoint_url=payload.sharepoint_url,
        uploaded_by_source="API", uploaded_at=_now(),
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _document_out(row)


# --- Reviews ---------------------------------------------------------------------
def _review_out(row) -> contracts_models.AgreementReviewOut:
    return contracts_models.AgreementReviewOut(
        id=row.id, agreement_id=row.agreement_id, reviewer_type=row.reviewer_type,
        reviewer_employee_id=row.reviewer_employee_id, summary=row.summary, outcome=row.outcome,
        reviewed_at=row.reviewed_at, created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list reviews")
def list_reviews(user: CurrentUser, account_repo: AccountRepository,
                 agreement_repo: AgreementRepository, review_repo: AgreementReviewRepository,
                 aid: str) -> list[contracts_models.AgreementReviewOut]:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.")
    return [_review_out(r) for r in review_repo.list_for_agreement(aid)]


@handle_errors("add review")
def add_review(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
              review_repo: AgreementReviewRepository, aid: str,
              payload: contracts_models.AgreementReviewCreate) -> contracts_models.AgreementReviewOut:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    row = review_repo.create(
        agreement_id=aid, reviewer_type=payload.reviewer_type,
        reviewer_employee_id=verified_employee_uuid(user),
        summary=payload.summary, outcome=payload.outcome, reviewed_at=_now(),
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _review_out(row)


# --- Notes -------------------------------------------------------------------
def _note_out(row) -> contracts_models.AgreementNoteOut:
    return contracts_models.AgreementNoteOut(
        id=row.id, agreement_id=row.agreement_id, note_text=row.note_text,
        created_at=row.created_at, updated_at=row.updated_at,
        created_by=row.created_by, updated_by=row.updated_by,
    )


@handle_errors("list notes")
def list_notes(user: CurrentUser, account_repo: AccountRepository,
               agreement_repo: AgreementRepository, note_repo: AgreementNoteRepository,
               aid: str) -> list[contracts_models.AgreementNoteOut]:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.")
    return [_note_out(n) for n in sorted(note_repo.list_for_agreement(aid), key=lambda n: n.created_at)]


@handle_errors("add note")
def add_note(user: CurrentUser, account_repo: AccountRepository, agreement_repo: AgreementRepository,
             note_repo: AgreementNoteRepository, aid: str,
             payload: contracts_models.AgreementNoteCreate) -> contracts_models.AgreementNoteOut:
    agreement = _get_or_404(agreement_repo, aid)
    require_account_scope(user, account_repo, agreement.account_id, "Agreement is outside your data scope.",
                          for_write=True)
    row = note_repo.create(
        agreement_id=aid, note_text=payload.note_text,
        created_by=user.employee_id, updated_by=user.employee_id,
    )
    return _note_out(row)
