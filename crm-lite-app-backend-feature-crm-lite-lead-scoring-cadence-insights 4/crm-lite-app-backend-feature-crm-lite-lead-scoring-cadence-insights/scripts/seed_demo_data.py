"""Populate the local Postgres database with a realistic mock dataset spanning
all 8 CLM modules, for manual testing/demoing against the running app.

Goes through the repository layer (never raw SQL/session access), so every
row picks up audit columns and an audit_log trail exactly as a real write
would. Business logic/routes are still 501 stubs — this only exercises the
repository/model layer directly, it does not call any service.

Idempotent: skips entirely if the marker customer ("Northwind Traders")
already exists.

Run (after `docker compose up -d` and `uv run alembic upgrade head`):
    uv run python -m scripts.seed_demo_data
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.repositories.activity_repository import (
    get_communication_repository,
    get_notification_repository,
)
from src.repositories.admin_repository import (
    get_employee_repository,
    get_employee_role_repository,
    get_profile_repository,
    get_team_repository,
)
from src.repositories.contracts_repository import (
    get_agreement_clause_repository,
    get_agreement_document_repository,
    get_agreement_repository,
    get_agreement_review_repository,
    get_agreement_status_repository,
    get_agreement_type_repository,
)
from src.repositories.crm_repository import (
    get_contact_repository,
    get_contact_type_repository,
    get_customer_assignment_repository,
    get_customer_repository,
    get_customer_type_repository,
    get_opportunity_document_repository,
    get_opportunity_repository,
    get_opportunity_stage_repository,
)
from src.repositories.delivery_repository import (
    get_sow_budget_repository,
    get_sow_detail_repository,
    get_sow_milestone_repository,
    get_sow_rate_card_repository,
    get_sow_team_member_repository,
    get_sow_timesheet_repository,
)
from src.repositories.project_repository import get_project_repository, get_project_status_repository

SEEDED_BY = "seed-script"
MARKER_CUSTOMER_NAME = "Northwind Traders"
TODAY = date.today()


def _now(days_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _code_id(repo, code: str) -> int:
    rows = repo.list(code=code)
    if not rows:
        raise RuntimeError(f"lookup code {code!r} not found in {repo.model.__tablename__} "
                            "— run `uv run alembic upgrade head` first")
    return rows[0].id


def seed_employees_and_teams():
    employee_repo = get_employee_repository()
    role_repo = get_profile_repository()
    employee_role_repo = get_employee_role_repository()
    team_repo = get_team_repository()

    people = [
        ("priya.sharma@tachyontech.com", "Priya Sharma", "ADMIN"),
        ("david.okafor@tachyontech.com", "David Okafor", "LEADERSHIP"),
        ("jordan.lee@tachyontech.com", "Jordan Lee", "ACCOUNT_EXEC"),
        ("sofia.novak@tachyontech.com", "Sofia Novak", "ACCOUNT_EXEC"),
        ("amit.patel@tachyontech.com", "Amit Patel", "ACCOUNT_EXEC"),
        ("marcus.chen@tachyontech.com", "Marcus Chen", "SALES"),
        ("elena.rodriguez@tachyontech.com", "Elena Rodriguez", "SALES"),
        ("grace.kim@tachyontech.com", "Grace Kim", "SALES"),
    ]

    employees = {}
    for email, full_name, role_code in people:
        emp = employee_repo.create(
            email=email, full_name=full_name, is_active=True,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
        employee_role_repo.grant(emp.id, _code_id(role_repo, role_code), granted_by=SEEDED_BY)
        employees[full_name] = emp

    teams = {}
    for display_name, purpose, address in [
        ("Enterprise Sales", "New logo acquisition for enterprise accounts", "enterprise-sales@tachyontech.com"),
        ("Delivery - West", "SOW delivery and staffing for West region clients", "delivery-west@tachyontech.com"),
        ("Legal & Compliance", "Contract review and clause approval", "legal@tachyontech.com"),
    ]:
        teams[display_name] = team_repo.create(
            display_name=display_name, purpose=purpose, address=address,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

    return employees, teams


def seed_customers_contacts_assignments(employees, teams):
    customer_repo = get_customer_repository()
    customer_type_repo = get_customer_type_repository()
    contact_repo = get_contact_repository()
    contact_type_repo = get_contact_type_repository()
    assignment_repo = get_customer_assignment_repository()
    role_repo = get_profile_repository()

    customer_defs = [
        (MARKER_CUSTOMER_NAME, "CLIENT", "Logistics", "https://northwindtraders.example.com",
         "400 Freight Way, Seattle, WA", "Marcus Chen", 400),
        ("Contoso Manufacturing", "CLIENT", "Manufacturing", "https://contoso-mfg.example.com",
         "12 Industrial Pkwy, Detroit, MI", "Elena Rodriguez", 260),
        ("Fabrikam Retail Group", "PROSPECT", "Retail", "https://fabrikam-retail.example.com",
         "88 Market St, Chicago, IL", "Marcus Chen", 30),
        ("Globex Financial Services", "CLIENT", "Finance", "https://globex-fs.example.com",
         "1 Capital Plaza, New York, NY", "Grace Kim", 520),
        ("Initech Software", "VENDOR", "Technology", "https://initech.example.com",
         "500 Office Space Dr, Austin, TX", "Jordan Lee", 200),
        ("Umbrella Health Partners", "PARTNER", "Healthcare", "https://umbrella-health.example.com",
         "7 Wellness Ave, Boston, MA", "Sofia Novak", 150),
    ]

    customers = {}
    for legal_name, type_code, industry, website, address, owner_name, days_ago in customer_defs:
        owner = employees[owner_name]
        promoted_at = _now(days_ago - 20) if type_code in ("CLIENT", "PARTNER") else None
        customers[legal_name] = customer_repo.create(
            id=customer_repo.next_id(),
            legal_name=legal_name,
            customer_type_id=_code_id(customer_type_repo, type_code),
            industry=industry, website=website, address=address,
            owner_employee_id=owner.id,
            first_contact_at=_now(days_ago),
            promoted_to_client_at=promoted_at,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

    contact_defs = [
        (MARKER_CUSTOMER_NAME, "BUSINESS", "Alicia Ferreira", "alicia.ferreira@northwindtraders.example.com",
         "+1-206-555-0142", "VP Operations", True, False),
        (MARKER_CUSTOMER_NAME, "LEGAL", "Ben Whitfield", "ben.whitfield@northwindtraders.example.com",
         "+1-206-555-0187", "General Counsel", False, False),
        ("Contoso Manufacturing", "BUSINESS", "Carla Nguyen", "carla.nguyen@contoso-mfg.example.com",
         "+1-313-555-0110", "Director of Procurement", True, False),
        ("Contoso Manufacturing", "PROCUREMENT", "Procurement Distribution List",
         "procurement@contoso-mfg.example.com", None, None, False, True),
        ("Fabrikam Retail Group", "BUSINESS", "Derek Osei", "derek.osei@fabrikam-retail.example.com",
         "+1-312-555-0199", "Head of Store Ops", True, False),
        ("Globex Financial Services", "BUSINESS", "Fiona Marsh", "fiona.marsh@globex-fs.example.com",
         "+1-212-555-0133", "Chief of Staff", True, False),
        ("Globex Financial Services", "LEGAL", "Legal Distribution List", "legal@globex-fs.example.com",
         None, None, False, True),
        ("Initech Software", "PROCUREMENT", "Grant Michaels", "grant.michaels@initech.example.com",
         "+1-512-555-0166", "Vendor Manager", True, False),
        ("Umbrella Health Partners", "BUSINESS", "Helen Ito", "helen.ito@umbrella-health.example.com",
         "+1-617-555-0155", "Partnerships Lead", True, False),
    ]

    for customer_name, type_code, full_name, email, phone, title, is_primary, is_dl in contact_defs:
        contact_repo.create(
            customer_id=customers[customer_name].id,
            contact_type_id=_code_id(contact_type_repo, type_code),
            full_name=full_name, email=email, phone=phone, title=title,
            is_primary=is_primary, is_distribution_list=is_dl,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

    assignment_defs = [
        (MARKER_CUSTOMER_NAME, "Marcus Chen", None, "SALES"),
        (MARKER_CUSTOMER_NAME, "Jordan Lee", None, "ACCOUNT_EXEC"),
        ("Contoso Manufacturing", "Elena Rodriguez", None, "SALES"),
        ("Contoso Manufacturing", None, "Delivery - West", "ACCOUNT_EXEC"),
        ("Globex Financial Services", "Grace Kim", None, "SALES"),
        ("Globex Financial Services", "Sofia Novak", None, "ACCOUNT_EXEC"),
        ("Umbrella Health Partners", None, "Legal & Compliance", "LEADERSHIP"),
    ]
    for customer_name, employee_name, team_name, role_code in assignment_defs:
        assignment_repo.create(
            customer_id=customers[customer_name].id,
            employee_id=employees[employee_name].id if employee_name else None,
            team_id=teams[team_name].id if team_name else None,
            role_id=_code_id(role_repo, role_code),
            assigned_from=TODAY - timedelta(days=200),
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

    return customers


def seed_opportunities(customers, employees):
    opportunity_repo = get_opportunity_repository()
    stage_repo = get_opportunity_stage_repository()
    document_repo = get_opportunity_document_repository()

    opportunity_defs = [
        (MARKER_CUSTOMER_NAME, "Warehouse Automation Rollout", "WON", 480000, TODAY - timedelta(days=60),
         "Jordan Lee", None),
        (MARKER_CUSTOMER_NAME, "Cold Chain Monitoring Add-on", "PROPOSAL", 95000, TODAY + timedelta(days=45),
         "Jordan Lee", None),
        ("Contoso Manufacturing", "ERP Integration Phase 2", "WON", 610000, TODAY - timedelta(days=30),
         "Elena Rodriguez", None),
        ("Contoso Manufacturing", "Predictive Maintenance Pilot", "NEGOTIATION", 220000,
         TODAY + timedelta(days=20), "Elena Rodriguez", None),
        ("Fabrikam Retail Group", "POS Modernization", "QUALIFIED", 340000, TODAY + timedelta(days=90),
         "Marcus Chen", None),
        ("Globex Financial Services", "Compliance Reporting Platform", "WON", 750000,
         TODAY - timedelta(days=140), "Grace Kim", None),
        ("Globex Financial Services", "Fraud Detection Expansion", "LOST", 300000, TODAY - timedelta(days=10),
         "Grace Kim", "Budget reallocated to internal team for FY26"),
        ("Umbrella Health Partners", "Patient Portal Co-Development", "NEW", 180000,
         TODAY + timedelta(days=120), "Sofia Novak", None),
    ]

    opportunities = {}
    for customer_name, name, stage_code, value, close_date, owner_name, lost_reason in opportunity_defs:
        opp = opportunity_repo.create(
            id=opportunity_repo.next_id(),
            customer_id=customers[customer_name].id,
            name=name,
            opportunity_stage_id=_code_id(stage_repo, stage_code),
            estimated_value=value, currency="USD",
            expected_close_date=close_date,
            owner_employee_id=employees[owner_name].id,
            lost_reason=lost_reason,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
        opportunities[(customer_name, name)] = opp

        if stage_code == "WON":
            document_repo.create(
                opportunity_id=opp.id, version_number=1, doc_type="PROPOSAL", status="FINAL",
                sharepoint_item_id=f"sp-opp-{opp.id.lower()}", filename=f"{name.replace(' ', '_')}_Proposal.pdf",
                sharepoint_url=f"https://tachyontech.sharepoint.com/sites/clm/opportunities/{opp.id}/proposal.pdf",
                uploaded_at=_now(65), created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )

    return opportunities


def seed_agreements(customers, employees):
    agreement_repo = get_agreement_repository()
    type_repo = get_agreement_type_repository()
    status_repo = get_agreement_status_repository()
    document_repo = get_agreement_document_repository()
    clause_repo = get_agreement_clause_repository()
    review_repo = get_agreement_review_repository()

    # (customer, title, type_code, status_code, signed_days_ago, signer)
    agreement_defs = [
        (MARKER_CUSTOMER_NAME, "Northwind Traders Mutual NDA", "NDA", "SIGNED", 150, "Jordan Lee"),
        (MARKER_CUSTOMER_NAME, "Northwind Traders Master Services Agreement", "MSA", "SIGNED", 130, "Jordan Lee"),
        (MARKER_CUSTOMER_NAME, "Warehouse Automation SOW", "SOW", "SIGNED", 58, "Jordan Lee"),
        ("Contoso Manufacturing", "Contoso Mutual NDA", "NDA", "SIGNED", 90, "Elena Rodriguez"),
        ("Contoso Manufacturing", "Contoso Master Services Agreement", "MSA", "SIGNED", 70, "Elena Rodriguez"),
        ("Contoso Manufacturing", "ERP Integration Phase 2 SOW", "SOW", "SIGNED", 28, "Elena Rodriguez"),
        ("Globex Financial Services", "Globex Mutual NDA", "NDA", "SIGNED", 200, "Grace Kim"),
        ("Globex Financial Services", "Globex Master Services Agreement", "MSA", "SENT", None, None),
        ("Fabrikam Retail Group", "Fabrikam Mutual NDA", "NDA", "DRAFT", None, None),
        ("Initech Software", "Initech Vendor MSA", "VENDOR_MSA", "SIGNED", 300, "Sofia Novak"),
        ("Initech Software", "Initech PO #1 - Support Renewal", "PURCHASE_ORDER", "SIGNED", 45, "Sofia Novak"),
        ("Umbrella Health Partners", "Umbrella Partnership MSA", "MSA", "REVIEW", None, None),
    ]

    agreements = {}
    for customer_name, title, type_code, status_code, signed_days_ago, signer_name in agreement_defs:
        signed_at = _now(signed_days_ago) if signed_days_ago is not None else None
        agr = agreement_repo.create(
            id=agreement_repo.next_id(),
            customer_id=customers[customer_name].id,
            agreement_type_id=_code_id(type_repo, type_code),
            agreement_status_id=_code_id(status_repo, status_code),
            title=title,
            initiated_by_employee_id=employees[signer_name].id if signer_name else employees["Jordan Lee"].id,
            effective_date=(signed_at.date() if signed_at else None),
            expiry_date=(signed_at.date() + timedelta(days=730) if signed_at else None),
            signed_at=signed_at,
            signed_by_employee_id=employees[signer_name].id if signer_name else None,
            sla_due_at=_now(-3) if status_code in ("REVIEW", "SENT", "DRAFT") else None,
            sharepoint_folder_url=f"https://tachyontech.sharepoint.com/sites/clm/agreements/{title.replace(' ', '_')}",
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
        agreements[(customer_name, title)] = agr

        if status_code == "SIGNED":
            document_repo.create(
                agreement_id=agr.id, version_number=1,
                sharepoint_item_id=f"sp-agr-{agr.id.lower()}",
                filename=f"{title.replace(' ', '_')}_Executed.pdf",
                sharepoint_url=f"https://tachyontech.sharepoint.com/sites/clm/agreements/{agr.id}/executed.pdf",
                content_type="application/pdf", size_bytes=482_133,
                uploaded_by_source="SHAREPOINT", uploaded_at=signed_at,
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )
            review_repo.create(
                agreement_id=agr.id, reviewer_type="HUMAN",
                reviewer_employee_id=employees["Priya Sharma"].id,
                summary=f"Standard terms reviewed and approved for {title}.",
                outcome="APPROVED", reviewed_at=signed_at - timedelta(days=5),
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )

        if type_code in ("MSA", "SOW", "VENDOR_MSA"):
            clause_repo.create(
                agreement_id=agr.id, section_ref="§4.2", clause_text="Limitation of liability capped at 12 months of fees paid.",
                is_flagged=False, policy_ref="POLICY-LOL-01",
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )
            clause_repo.create(
                agreement_id=agr.id, section_ref="§7.1",
                clause_text="Non-standard indemnification language proposed by counterparty.",
                is_flagged=(status_code != "SIGNED"),
                flag_reason="Deviates from standard indemnification template" if status_code != "SIGNED" else None,
                policy_ref="POLICY-INDEM-03",
                resolution_status="RESOLVED" if status_code == "SIGNED" else "OPEN",
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )

    return agreements


def seed_projects(customers, opportunities, employees):
    project_repo = get_project_repository()
    status_repo = get_project_status_repository()

    project_defs = [
        (MARKER_CUSTOMER_NAME, "Warehouse Automation Rollout",
         (MARKER_CUSTOMER_NAME, "Warehouse Automation Rollout"), "ACTIVE",
         "Jordan Lee", 55, None, None),
        ("Contoso Manufacturing", "ERP Integration Phase 2",
         ("Contoso Manufacturing", "ERP Integration Phase 2"), "PLANNING",
         "Elena Rodriguez", 20, 200, None),
        ("Globex Financial Services", "Compliance Reporting Platform",
         ("Globex Financial Services", "Compliance Reporting Platform"), "CLOSED",
         "Grace Kim", 130, 30, 25),
    ]

    projects = {}
    for customer_name, name, opp_key, status_code, ae_name, start_days_ago, target_days_out, actual_days_ago in project_defs:
        projects[name] = project_repo.create(
            id=project_repo.next_id(),
            customer_id=customers[customer_name].id,
            opportunity_id=opportunities[opp_key].id if opp_key in opportunities else None,
            name=name, description=f"Delivery engagement tracking work for {name}.",
            project_status_id=_code_id(status_repo, status_code),
            account_executive_employee_id=employees[ae_name].id,
            start_date=TODAY - timedelta(days=start_days_ago),
            target_end_date=(TODAY + timedelta(days=target_days_out)) if target_days_out else None,
            actual_end_date=(TODAY - timedelta(days=actual_days_ago)) if actual_days_ago else None,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
    return projects


def seed_sow_delivery(agreements, projects, employees):
    detail_repo = get_sow_detail_repository()
    budget_repo = get_sow_budget_repository()
    rate_card_repo = get_sow_rate_card_repository()
    team_member_repo = get_sow_team_member_repository()
    milestone_repo = get_sow_milestone_repository()
    timesheet_repo = get_sow_timesheet_repository()

    sow_defs = [
        (MARKER_CUSTOMER_NAME, "Warehouse Automation SOW", "Northwind Traders Master Services Agreement",
         "Warehouse Automation Rollout", 480000, 6, "Jordan Lee"),
        ("Contoso Manufacturing", "ERP Integration Phase 2 SOW", "Contoso Master Services Agreement",
         "ERP Integration Phase 2", 610000, 8, "Elena Rodriguez"),
    ]

    for customer_name, sow_title, msa_title, project_name, total_value, headcount, ae_name in sow_defs:
        sow_agreement = agreements[(customer_name, sow_title)]
        msa_agreement = agreements[(customer_name, msa_title)]
        project = projects[project_name]

        detail_repo.create(
            agreement_id=sow_agreement.id, project_id=project.id,
            governing_msa_id=msa_agreement.id, billing_model="TIME_AND_MATERIALS",
            total_value=total_value, currency="USD", headcount=headcount,
            invoicing_frequency="MONTHLY", created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

        budget_repo.create(
            agreement_id=sow_agreement.id, amount=total_value, currency="USD",
            alert_threshold_percents="70,85,95", effective_from=sow_agreement.effective_date,
            is_current=True, created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

        rate_cards = {}
        for role_label, rate in [
            ("Senior Engineer", 145.00), ("Project Manager", 165.00), ("QA Analyst", 95.00),
        ]:
            rate_cards[role_label] = rate_card_repo.create(
                agreement_id=sow_agreement.id, role_label=role_label, rate_per_hour=rate,
                currency="USD", effective_from=sow_agreement.effective_date,
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            )

        team_members = [
            team_member_repo.create(
                agreement_id=sow_agreement.id, employee_id=employees[ae_name].id,
                rate_card_id=rate_cards["Project Manager"].id,
                assigned_from=sow_agreement.effective_date,
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            ),
            team_member_repo.create(
                agreement_id=sow_agreement.id, external_name="Rachel Kimura (Contractor)",
                rate_card_id=rate_cards["Senior Engineer"].id,
                override_rate_per_hour=155.00,
                assigned_from=sow_agreement.effective_date,
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            ),
            team_member_repo.create(
                agreement_id=sow_agreement.id, external_name="Owen Bradshaw (Contractor)",
                rate_card_id=rate_cards["QA Analyst"].id,
                assigned_from=sow_agreement.effective_date,
                created_by=SEEDED_BY, updated_by=SEEDED_BY,
            ),
        ]

        milestone_repo.create(
            agreement_id=sow_agreement.id, milestone_name="Kickoff & Discovery",
            planned_date=sow_agreement.effective_date + timedelta(days=14),
            actual_date=sow_agreement.effective_date + timedelta(days=14),
            amount=round(total_value * 0.2, 2), status="INVOICED",
            invoiced_at=_now(30), invoice_ref=f"INV-{sow_agreement.id}-01",
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
        milestone_repo.create(
            agreement_id=sow_agreement.id, milestone_name="Phase 1 Delivery",
            planned_date=sow_agreement.effective_date + timedelta(days=60),
            amount=round(total_value * 0.4, 2), status="PENDING",
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )
        milestone_repo.create(
            agreement_id=sow_agreement.id, milestone_name="Final Delivery & Sign-off",
            planned_date=sow_agreement.effective_date + timedelta(days=120),
            amount=round(total_value * 0.4, 2), status="PENDING",
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

        for week_offset in (3, 2, 1):
            week_start = TODAY - timedelta(days=TODAY.weekday() + 7 * week_offset)
            for member in team_members:
                is_approved = week_offset != 1
                timesheet_repo.create(
                    sow_team_member_id=member.id, agreement_id=sow_agreement.id,
                    week_start_date=week_start, hours=38.5,
                    status="APPROVED" if is_approved else "SUBMITTED",
                    submitted_by_employee_id=employees[ae_name].id,
                    approved_by_employee_id=employees["Priya Sharma"].id if is_approved else None,
                    approved_at=_now(week_offset * 7 - 2) if is_approved else None,
                    created_by=SEEDED_BY, updated_by=SEEDED_BY,
                )


def seed_activity(customers, agreements, employees, teams):
    communication_repo = get_communication_repository()
    notification_repo = get_notification_repository()

    communication_defs = [
        (MARKER_CUSTOMER_NAME, "Northwind Traders Master Services Agreement", "OUTBOUND", "EMAIL",
         "MSA redline sent for review", "jordan.lee@tachyontech.com", 132, "Jordan Lee"),
        (MARKER_CUSTOMER_NAME, "Warehouse Automation SOW", "INBOUND", "EMAIL",
         "Re: SOW signature confirmation", "alicia.ferreira@northwindtraders.example.com", 58, "Jordan Lee"),
        ("Contoso Manufacturing", "Contoso Master Services Agreement", "OUTBOUND", "MEETING",
         "MSA negotiation call", None, 72, "Elena Rodriguez"),
        ("Globex Financial Services", "Globex Master Services Agreement", "INBOUND", "EMAIL",
         "Requested changes to payment terms", "fiona.marsh@globex-fs.example.com", 4, "Grace Kim"),
        ("Fabrikam Retail Group", None, "OUTBOUND", "PHONE",
         "Intro call re: NDA + POS Modernization opportunity", None, 25, "Marcus Chen"),
        ("Umbrella Health Partners", "Umbrella Partnership MSA", "OUTBOUND", "EMAIL",
         "Sent partnership MSA for legal review", "helen.ito@umbrella-health.example.com", 6, "Sofia Novak"),
    ]

    for customer_name, agreement_key, direction, channel, subject, from_address, days_ago, employee_name in communication_defs:
        communication_repo.create(
            customer_id=customers[customer_name].id if customer_name else None,
            agreement_id=agreements[(customer_name, agreement_key)].id if agreement_key else None,
            received_via_team_id=None,
            direction=direction, channel=channel, subject=subject,
            from_address=from_address, occurred_at=_now(days_ago), source="MANUAL",
            logged_by_employee_id=employees[employee_name].id,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )

    notification_defs = [
        (MARKER_CUSTOMER_NAME, "Warehouse Automation SOW", "BUDGET_THRESHOLD", "WARNING", 5, True, None, None),
        ("Contoso Manufacturing", "Contoso Master Services Agreement", "SLA_AT_RISK", "WARNING", 2, False,
         None, None),
        ("Globex Financial Services", "Globex Master Services Agreement", "AGREEMENT_PENDING_SIGNATURE",
         "INFO", 4, False, "David Okafor", "Jordan Lee sent the MSA for Globex Financial Services for signature."),
        ("Fabrikam Retail Group", None, "OPPORTUNITY_STALE", "INFO", 10, True, None, None),
        ("Umbrella Health Partners", "Umbrella Partnership MSA", "REVIEW_OVERDUE", "CRITICAL", 1, False,
         None, None),
    ]
    for (customer_name, agreement_key, notification_type, severity, days_ago, acknowledged,
        recipient_name, message) in notification_defs:
        notification_repo.create(
            agreement_id=agreements[(customer_name, agreement_key)].id if agreement_key else None,
            customer_id=customers[customer_name].id if customer_name else None,
            recipient_employee_id=employees[recipient_name].id if recipient_name else None,
            notification_type=notification_type, severity=severity, message=message,
            sent_at=_now(days_ago), acknowledged=acknowledged,
            created_by=SEEDED_BY, updated_by=SEEDED_BY,
        )


def seed() -> None:
    customer_repo = get_customer_repository()
    if customer_repo.list(legal_name=MARKER_CUSTOMER_NAME):
        print(f"Seed data already present (found {MARKER_CUSTOMER_NAME!r}) — skipping.")
        return

    print("Seeding employees, roles, and teams...")
    employees, teams = seed_employees_and_teams()

    print("Seeding customers, contacts, and assignments...")
    customers = seed_customers_contacts_assignments(employees, teams)

    print("Seeding opportunities...")
    opportunities = seed_opportunities(customers, employees)

    print("Seeding agreements, documents, clauses, and reviews...")
    agreements = seed_agreements(customers, employees)

    print("Seeding projects...")
    projects = seed_projects(customers, opportunities, employees)

    print("Seeding SOW delivery data (budgets, rate cards, team, milestones, timesheets)...")
    seed_sow_delivery(agreements, projects, employees)

    print("Seeding communications and notifications...")
    seed_activity(customers, agreements, employees, teams)

    print("Done. Seeded 8 employees, 3 teams, 6 customers, 8 opportunities, "
          "12 agreements, 3 projects, 2 SOW delivery sets, communications, and notifications.")


if __name__ == "__main__":
    seed()
