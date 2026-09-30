"""CRM module repositories (§1/§6 of the API spec) — real, Postgres-backed
data access for every table this module owns. This is the central "database
logic" layer: developers building crm_service.py / crm_routes.py call these
classes directly and never open a Session themselves.

Tables covered: account_type (lookup), account, contact_type (lookup),
contact, account_assignment, opportunity_stage (lookup), opportunity,
opportunity_document.
"""
from functools import lru_cache

from sqlalchemy import select

from src.models.crm_models import (
    CadenceStep,
    CadenceTask,
    CadenceTemplate,
    Campaign,
    CampaignMember,
    Contact,
    ContactType,
    Account,
    AccountAssignment,
    AccountType,
    FieldPermission,
    Lead,
    LeadCadenceEnrollment,
    LeadScoringRule,
    Opportunity,
    OpportunityDocument,
    OpportunityStage,
    OrgWideDefault,
    Product,
    RecordShare,
    Signal,
)
from src.repositories._base import CrudRepository, SoftDeleteCrudRepository, next_business_id


class AccountTypeRepository(CrudRepository[AccountType]):
    model = AccountType


class AccountRepository(SoftDeleteCrudRepository[Account]):
    model = Account

    def next_id(self) -> str:
        with self._session_factory() as db:
            return next_business_id(db, Account, "id", "ACC-")

    def list_for_owner(self, owner_employee_id) -> list[Account]:
        """Convenience read used by any scope rule that limits results to
        accounts a given employee owns."""
        return self.list(owner_employee_id=owner_employee_id)

    def list_for_owners(self, owner_employee_ids) -> list[Account]:
        """Batched counterpart to list_for_owner() — used by scope.py's
        owned_account_ids() to resolve "self + every Role-Hierarchy
        subordinate" in one query instead of one per owner."""
        if not owner_employee_ids:
            return []
        with self._session_factory() as db:
            stmt = select(Account).where(
                Account.deleted_at.is_(None), Account.owner_employee_id.in_(owner_employee_ids))
            return list(db.execute(stmt).scalars().all())


class ContactTypeRepository(CrudRepository[ContactType]):
    model = ContactType


class ContactRepository(SoftDeleteCrudRepository[Contact]):
    model = Contact

    def list_for_account(self, account_id: str) -> list[Contact]:
        return self.list(account_id=account_id)


class AccountAssignmentRepository(SoftDeleteCrudRepository[AccountAssignment]):
    model = AccountAssignment

    def list_for_account(self, account_id: str) -> list[AccountAssignment]:
        return self.list(account_id=account_id)


class OpportunityStageRepository(CrudRepository[OpportunityStage]):
    model = OpportunityStage


class OpportunityRepository(SoftDeleteCrudRepository[Opportunity]):
    model = Opportunity

    def next_id(self) -> str:
        with self._session_factory() as db:
            return next_business_id(db, Opportunity, "id", "OPP-")

    def list_for_account(self, account_id: str) -> list[Opportunity]:
        return self.list(account_id=account_id)


class OpportunityDocumentRepository(SoftDeleteCrudRepository[OpportunityDocument]):
    model = OpportunityDocument

    def list_for_opportunity(self, opportunity_id: str) -> list[OpportunityDocument]:
        return self.list(opportunity_id=opportunity_id)


class CampaignRepository(SoftDeleteCrudRepository[Campaign]):
    model = Campaign

    def list_for_owner(self, owner_employee_id) -> list[Campaign]:
        return self.list(owner_employee_id=owner_employee_id)


class CampaignMemberRepository(SoftDeleteCrudRepository[CampaignMember]):
    model = CampaignMember

    def list_for_campaign(self, campaign_id) -> list[CampaignMember]:
        return self.list(campaign_id=campaign_id)


class LeadRepository(SoftDeleteCrudRepository[Lead]):
    model = Lead

    def list_for_owner(self, owner_employee_id) -> list[Lead]:
        return self.list(owner_employee_id=owner_employee_id)

    def list_for_campaign(self, campaign_id) -> list[Lead]:
        return self.list(campaign_id=campaign_id)

    def find_by_contact_email(self, email: str) -> Lead | None:
        matches = self.list(contact_email=email)
        return matches[0] if matches else None

    def find_by_phone(self, phone: str) -> Lead | None:
        """Matches contact_phone first, then mobile_phone — same fallback
        order activity_service.send_lead_sms() uses to pick a number to send
        to. Used by crm_service.process_inbound_sms() to find which Lead an
        inbound text's From number belongs to."""
        matches = self.list(contact_phone=phone)
        if matches:
            return matches[0]
        matches = self.list(mobile_phone=phone)
        return matches[0] if matches else None

    def find_by_whatsapp_number(self, whatsapp_number: str) -> Lead | None:
        """Used by the inbound WhatsApp webhook to find which Lead a
        message's From number (already stripped of Twilio's "whatsapp:"
        prefix) belongs to — same shape as find_by_phone() above."""
        matches = self.list(whatsapp_number=whatsapp_number)
        return matches[0] if matches else None

    def find_by_company_name(self, company_name: str) -> Lead | None:
        """Case-insensitive exact match — used by ingest_signals() to decide
        whether a sourced signal belongs to an existing Lead or should create
        a new one (see crm_service.ingest_signals())."""
        with self._session_factory() as db:
            stmt = select(Lead).where(
                Lead.deleted_at.is_(None), Lead.company_name.ilike(company_name))
            return db.execute(stmt).scalars().first()


class LeadScoringRuleRepository(SoftDeleteCrudRepository[LeadScoringRule]):
    model = LeadScoringRule

    def list_active(self) -> list[LeadScoringRule]:
        return self.list(is_active=True)


class SignalRepository(CrudRepository[Signal]):
    """Immutable evidence rows — hard-delete CRUD (no soft-delete: see
    crm_models.Signal's docstring)."""
    model = Signal

    def list_for_lead(self, lead_id) -> list[Signal]:
        return self.list(lead_id=lead_id)

    def list_for_company(self, company_name: str) -> list[Signal]:
        with self._session_factory() as db:
            stmt = select(Signal).where(Signal.company_name.ilike(company_name))
            return list(db.execute(stmt).scalars().all())

    def exists(self, company_name: str, type_: str, source: str) -> bool:
        """Matches the identity ingest_signals() dedupes a mock-catalog entry
        against (see Signal's unique constraint) without relying on that
        constraint firing (a caught IntegrityError would abort the whole
        ingest transaction for every other signal in the same run)."""
        with self._session_factory() as db:
            stmt = select(Signal.id).where(
                Signal.company_name.ilike(company_name), Signal.type == type_, Signal.source == source,
            )
            return db.execute(stmt).first() is not None


class FieldPermissionRepository(SoftDeleteCrudRepository[FieldPermission]):
    model = FieldPermission

    def list_for_object(self, object_name: str) -> list[FieldPermission]:
        return self.list(object_name=object_name)

    def hard_delete(self, id_) -> None:
        """A full-matrix Save replaces the ENTIRE row set for one object in
        one call — soft-deleting old rows would leave them still occupying
        the (role_id, object_name, field_name) unique constraint, blocking
        any future save that re-adds the same key. These rows are pure
        config toggles with no audit value in preserving deleted history
        (unlike every other soft-deleted table here), so a real delete is
        correct."""
        CrudRepository.delete(self, id_)


class OrgWideDefaultRepository(CrudRepository[OrgWideDefault]):
    """Hard-delete base is fine here (unlike FieldPermission) — rows are
    never created/deleted through the API, only ever get(object_name)/
    update(id, access_level=...) against the 5 migration-seeded rows."""
    model = OrgWideDefault

    def get_by_object(self, object_name: str) -> OrgWideDefault | None:
        rows = self.list(object_name=object_name)
        return rows[0] if rows else None


class RecordShareRepository(SoftDeleteCrudRepository[RecordShare]):
    """Backs services.record_access_service — see RecordShare's own
    docstring for why record_id is a plain string rather than a typed FK."""
    model = RecordShare

    def list_for_record(self, object_name: str, record_id: str) -> list[RecordShare]:
        return self.list(object_name=object_name, record_id=record_id)

    def get_for_employee(self, object_name: str, record_id: str, employee_id) -> RecordShare | None:
        with self._session_factory() as db:
            stmt = select(RecordShare).where(
                RecordShare.deleted_at.is_(None),
                RecordShare.object_name == object_name,
                RecordShare.record_id == record_id,
                RecordShare.shared_with_employee_id == employee_id,
            )
            return db.execute(stmt).scalars().first()

    def has_access(self, object_name: str, record_id: str, employee_id, required) -> bool:
        """`required` is a models.enums.RecordAccessLevel — DELETE is never
        satisfiable via sharing (see record_access_service.
        can_user_access_record(), which never calls this for DELETE) but is
        handled defensively here too rather than assumed."""
        share = self.get_for_employee(object_name, record_id, employee_id)
        if share is None:
            return False
        access_level = required.value if hasattr(required, "value") else required
        if access_level == "DELETE":
            return False
        if access_level == "EDIT":
            return share.access_level == "EDIT"
        return True  # any share (READ or EDIT) covers a READ check

    def list_shared_record_ids(self, object_name: str, employee_id) -> set[str]:
        """One query for a whole list-endpoint call — used to filter a list
        of candidate rows without a per-row round trip."""
        with self._session_factory() as db:
            stmt = select(RecordShare.record_id).where(
                RecordShare.deleted_at.is_(None),
                RecordShare.object_name == object_name,
                RecordShare.shared_with_employee_id == employee_id,
            )
            return set(db.execute(stmt).scalars().all())


class ProductRepository(SoftDeleteCrudRepository[Product]):
    model = Product

    def list_active(self) -> list[Product]:
        return self.list(is_active=True)


class CadenceTemplateRepository(SoftDeleteCrudRepository[CadenceTemplate]):
    model = CadenceTemplate


class CadenceStepRepository(SoftDeleteCrudRepository[CadenceStep]):
    model = CadenceStep

    def list_for_template(self, cadence_template_id) -> list[CadenceStep]:
        return self.list(cadence_template_id=cadence_template_id)


class LeadCadenceEnrollmentRepository(SoftDeleteCrudRepository[LeadCadenceEnrollment]):
    model = LeadCadenceEnrollment

    def list_for_lead(self, lead_id) -> list[LeadCadenceEnrollment]:
        return self.list(lead_id=lead_id)

    def get_active_for_lead(self, lead_id) -> LeadCadenceEnrollment | None:
        actives = [e for e in self.list_for_lead(lead_id) if e.status == "ACTIVE"]
        return actives[0] if actives else None

    def list_active(self) -> list[LeadCadenceEnrollment]:
        """Every ACTIVE enrollment, filtered at the DB level — used by
        crm_service.advance_due_cadence_steps() (the cadence scheduler) so
        one run doesn't load every enrollment ever created just to find the
        handful still in progress."""
        return self.list(status="ACTIVE")


class CadenceTaskRepository(SoftDeleteCrudRepository[CadenceTask]):
    model = CadenceTask

    def list_for_enrollment(self, enrollment_id) -> list[CadenceTask]:
        return self.list(enrollment_id=enrollment_id)

    def list_pending(self) -> list[CadenceTask]:
        return self.list(status="PENDING")


@lru_cache(maxsize=1)
def get_account_type_repository() -> AccountTypeRepository:
    return AccountTypeRepository()


@lru_cache(maxsize=1)
def get_account_repository() -> AccountRepository:
    return AccountRepository()


@lru_cache(maxsize=1)
def get_contact_type_repository() -> ContactTypeRepository:
    return ContactTypeRepository()


@lru_cache(maxsize=1)
def get_contact_repository() -> ContactRepository:
    return ContactRepository()


@lru_cache(maxsize=1)
def get_account_assignment_repository() -> AccountAssignmentRepository:
    return AccountAssignmentRepository()


@lru_cache(maxsize=1)
def get_opportunity_stage_repository() -> OpportunityStageRepository:
    return OpportunityStageRepository()


@lru_cache(maxsize=1)
def get_opportunity_repository() -> OpportunityRepository:
    return OpportunityRepository()


@lru_cache(maxsize=1)
def get_opportunity_document_repository() -> OpportunityDocumentRepository:
    return OpportunityDocumentRepository()


@lru_cache(maxsize=1)
def get_campaign_repository() -> CampaignRepository:
    return CampaignRepository()


@lru_cache(maxsize=1)
def get_campaign_member_repository() -> CampaignMemberRepository:
    return CampaignMemberRepository()


@lru_cache(maxsize=1)
def get_lead_repository() -> LeadRepository:
    return LeadRepository()


@lru_cache(maxsize=1)
def get_signal_repository() -> SignalRepository:
    return SignalRepository()


@lru_cache(maxsize=1)
def get_lead_scoring_rule_repository() -> LeadScoringRuleRepository:
    return LeadScoringRuleRepository()


@lru_cache(maxsize=1)
def get_field_permission_repository() -> FieldPermissionRepository:
    return FieldPermissionRepository()


@lru_cache(maxsize=1)
def get_org_wide_default_repository() -> OrgWideDefaultRepository:
    return OrgWideDefaultRepository()


@lru_cache(maxsize=1)
def get_record_share_repository() -> RecordShareRepository:
    return RecordShareRepository()


@lru_cache(maxsize=1)
def get_product_repository() -> ProductRepository:
    return ProductRepository()


@lru_cache(maxsize=1)
def get_cadence_template_repository() -> CadenceTemplateRepository:
    return CadenceTemplateRepository()


@lru_cache(maxsize=1)
def get_cadence_step_repository() -> CadenceStepRepository:
    return CadenceStepRepository()


@lru_cache(maxsize=1)
def get_lead_cadence_enrollment_repository() -> LeadCadenceEnrollmentRepository:
    return LeadCadenceEnrollmentRepository()


@lru_cache(maxsize=1)
def get_cadence_task_repository() -> CadenceTaskRepository:
    return CadenceTaskRepository()
