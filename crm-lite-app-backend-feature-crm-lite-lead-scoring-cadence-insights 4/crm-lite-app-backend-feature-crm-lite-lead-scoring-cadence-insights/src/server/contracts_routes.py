"""Contracts module routes (§1/§8 of the API spec) — 15 endpoints: Agreements
(incl. send-for-signature), clauses, documents, reviews.

IMPLEMENTED — see services/contracts_service.py. (SOW-specific sub-resources
live in delivery_routes.py; agreement-linked communications live in
activity_routes.py.)
"""
from uuid import UUID

from fastapi import APIRouter, Body, Depends

from src.models import contracts_models
from src.repositories.contracts_repository import (
    get_agreement_clause_repository,
    get_agreement_document_repository,
    get_agreement_note_repository,
    get_agreement_repository,
    get_agreement_review_repository,
)
from src.repositories.crm_repository import get_account_repository
from src.services import contracts_service
from src.utils.permissions import requires
from src.utils.security import CurrentUser

router = APIRouter(tags=["Contracts"])


# ---- Agreements ----
@router.get("/agreements", response_model=list[contracts_models.AgreementOut])
def list_agreements(u: CurrentUser = Depends(requires("platform.read")),
                    account_repo=Depends(get_account_repository),
                    repo=Depends(get_agreement_repository)):
    return contracts_service.list_agreements(u, account_repo, repo)


@router.post("/agreements", status_code=201, response_model=contracts_models.AgreementOut)
def create_agreement(payload: contracts_models.AgreementCreate,
                     u: CurrentUser = Depends(requires("agreements.write")),
                     account_repo=Depends(get_account_repository),
                     repo=Depends(get_agreement_repository)):
    return contracts_service.create_agreement(u, account_repo, repo, payload)


@router.get("/agreements/{agreement_id}", response_model=contracts_models.AgreementOut)
def get_agreement(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                  account_repo=Depends(get_account_repository),
                  repo=Depends(get_agreement_repository)):
    return contracts_service.get_agreement(u, account_repo, repo, agreement_id)


@router.patch("/agreements/{agreement_id}", response_model=contracts_models.AgreementOut)
def update_agreement(agreement_id: str, payload: contracts_models.AgreementUpdate,
                     u: CurrentUser = Depends(requires("agreements.write")),
                     repo=Depends(get_agreement_repository)):
    return contracts_service.update_agreement(u, repo, agreement_id, payload)


@router.delete("/agreements/{agreement_id}", status_code=204)
def delete_agreement(agreement_id: str, u: CurrentUser = Depends(requires("admin")),
                     repo=Depends(get_agreement_repository)):
    contracts_service.delete_agreement(repo, agreement_id)


@router.post("/agreements/{agreement_id}/send-for-signature", response_model=contracts_models.AgreementOut)
def send_for_signature(agreement_id: str, u: CurrentUser = Depends(requires("agreements.write")),
                       account_repo=Depends(get_account_repository),
                       repo=Depends(get_agreement_repository)):
    return contracts_service.send_for_signature(u, account_repo, repo, agreement_id)


@router.post("/agreements/{agreement_id}/sign", response_model=contracts_models.AgreementOut)
def sign_agreement(agreement_id: str, u: CurrentUser = Depends(requires("agreements.sign")),
                   account_repo=Depends(get_account_repository),
                   repo=Depends(get_agreement_repository)):
    return contracts_service.sign_agreement(u, account_repo, repo, agreement_id)


@router.post("/agreements/{agreement_id}/supersede", status_code=201,
            response_model=contracts_models.AgreementOut)
def supersede_agreement(agreement_id: str,
                        # Body(default=None) rather than a single shared
                        # AgreementSupersedeRequest() instance as the default
                        # value — that instance would be constructed once at
                        # import time and reused across every bodyless call.
                        payload: contracts_models.AgreementSupersedeRequest | None = Body(default=None),
                        u: CurrentUser = Depends(requires("agreements.write")),
                        repo=Depends(get_agreement_repository)):
    return contracts_service.supersede_agreement(
        u, repo, agreement_id, payload or contracts_models.AgreementSupersedeRequest())


# ---- Clauses ----
@router.get("/agreements/{agreement_id}/clauses", response_model=list[contracts_models.AgreementClauseOut])
def list_clauses(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                 account_repo=Depends(get_account_repository),
                 agreement_repo=Depends(get_agreement_repository),
                 clause_repo=Depends(get_agreement_clause_repository)):
    return contracts_service.list_clauses(u, account_repo, agreement_repo, clause_repo, agreement_id)


@router.post("/agreements/{agreement_id}/clauses", status_code=201,
            response_model=contracts_models.AgreementClauseOut)
def add_clause(agreement_id: str, payload: contracts_models.AgreementClauseCreate,
               u: CurrentUser = Depends(requires("agreements.write")),
               account_repo=Depends(get_account_repository),
               agreement_repo=Depends(get_agreement_repository),
               clause_repo=Depends(get_agreement_clause_repository)):
    return contracts_service.add_clause(u, account_repo, agreement_repo, clause_repo, agreement_id, payload)


@router.patch("/clauses/{clause_id}", response_model=contracts_models.AgreementClauseOut)
def update_clause(clause_id: UUID, payload: contracts_models.AgreementClauseUpdate,
                  u: CurrentUser = Depends(requires("agreements.write")),
                  account_repo=Depends(get_account_repository),
                  agreement_repo=Depends(get_agreement_repository),
                  clause_repo=Depends(get_agreement_clause_repository)):
    return contracts_service.update_clause(u, account_repo, agreement_repo, clause_repo, clause_id, payload)


# ---- Documents ----
@router.get("/agreements/{agreement_id}/documents",
           response_model=list[contracts_models.AgreementDocumentOut])
def list_agreement_documents(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                             account_repo=Depends(get_account_repository),
                             agreement_repo=Depends(get_agreement_repository),
                             document_repo=Depends(get_agreement_document_repository)):
    return contracts_service.list_agreement_documents(u, account_repo, agreement_repo,
                                                       document_repo, agreement_id)


@router.post("/agreements/{agreement_id}/documents", status_code=201,
            response_model=contracts_models.AgreementDocumentOut)
def add_agreement_document(agreement_id: str, payload: contracts_models.AgreementDocumentCreate,
                          u: CurrentUser = Depends(requires("agreements.write")),
                          account_repo=Depends(get_account_repository),
                          agreement_repo=Depends(get_agreement_repository),
                          document_repo=Depends(get_agreement_document_repository)):
    return contracts_service.add_agreement_document(u, account_repo, agreement_repo, document_repo,
                                                     agreement_id, payload)


# ---- Reviews ----
@router.get("/agreements/{agreement_id}/reviews", response_model=list[contracts_models.AgreementReviewOut])
def list_reviews(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
                 account_repo=Depends(get_account_repository),
                 agreement_repo=Depends(get_agreement_repository),
                 review_repo=Depends(get_agreement_review_repository)):
    return contracts_service.list_reviews(u, account_repo, agreement_repo, review_repo, agreement_id)


@router.post("/agreements/{agreement_id}/reviews", status_code=201,
            response_model=contracts_models.AgreementReviewOut)
def add_review(agreement_id: str, payload: contracts_models.AgreementReviewCreate,
               u: CurrentUser = Depends(requires("agreements.write")),
               account_repo=Depends(get_account_repository),
               agreement_repo=Depends(get_agreement_repository),
               review_repo=Depends(get_agreement_review_repository)):
    return contracts_service.add_review(u, account_repo, agreement_repo, review_repo, agreement_id, payload)


# ---- Notes ----
@router.get("/agreements/{agreement_id}/notes", response_model=list[contracts_models.AgreementNoteOut])
def list_notes(agreement_id: str, u: CurrentUser = Depends(requires("platform.read")),
              account_repo=Depends(get_account_repository),
              agreement_repo=Depends(get_agreement_repository),
              note_repo=Depends(get_agreement_note_repository)):
    return contracts_service.list_notes(u, account_repo, agreement_repo, note_repo, agreement_id)


@router.post("/agreements/{agreement_id}/notes", status_code=201,
            response_model=contracts_models.AgreementNoteOut)
def add_note(agreement_id: str, payload: contracts_models.AgreementNoteCreate,
            u: CurrentUser = Depends(requires("agreements.write")),
            account_repo=Depends(get_account_repository),
            agreement_repo=Depends(get_agreement_repository),
            note_repo=Depends(get_agreement_note_repository)):
    return contracts_service.add_note(u, account_repo, agreement_repo, note_repo, agreement_id, payload)
