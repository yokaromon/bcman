from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import auth
from ..database import get_db
from ..models import User
from . import service
from .models import MergeCandidate

router = APIRouter(prefix="/api/directory", tags=["directory"])
current_user = auth.current_user

def _visible_candidate(candidate_id: str, db: Session, user: User) -> MergeCandidate:
    candidate = db.get(MergeCandidate, candidate_id)
    if not candidate or candidate.status != "pending": raise HTTPException(404, "統合候補が見つかりません")
    visible_ids = {c.id for c in service.visible_contact_query(db, user).with_entities(service.Contact.id)}
    if candidate.contact_id not in visible_ids: raise HTTPException(404, "統合候補が見つかりません")
    return candidate

@router.get("/persons")
def list_persons(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.list_persons(db, user)

@router.get("/persons/{person_id}")
def get_person(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    detail = service.person_detail(db, user, person_id)
    if not detail: raise HTTPException(404, "人物が見つかりません")
    return detail

@router.post("/persons/{person_id}/contacts/{contact_id}/split")
def split_person(person_id: str, contact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not service.person_detail(db, user, person_id): raise HTTPException(404, "人物が見つかりません")
    try: new_person = service.split_person_contact(person_id, contact_id, db)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    db.commit(); return {"new_person_id": new_person.id}

@router.get("/companies")
def list_companies(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.list_companies(db, user)

@router.get("/companies/{company_id}")
def get_company(company_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    detail = service.company_detail(db, user, company_id)
    if not detail: raise HTTPException(404, "企業が見つかりません")
    return detail

@router.post("/companies/{company_id}/contacts/{contact_id}/split")
def split_company(company_id: str, contact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not service.company_detail(db, user, company_id): raise HTTPException(404, "企業が見つかりません")
    try: new_company = service.split_company_contact(company_id, contact_id, db)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    db.commit(); return {"new_company_id": new_company.id}

@router.get("/merge-candidates")
def list_merge_candidates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.list_merge_candidates(db, user)

@router.post("/merge-candidates/{candidate_id}/accept")
def accept_merge_candidate(candidate_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    candidate = _visible_candidate(candidate_id, db, user)
    service.accept_merge_candidate(candidate, user, db); db.commit()
    return {"status": "accepted"}

@router.post("/merge-candidates/{candidate_id}/dismiss")
def dismiss_merge_candidate(candidate_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    candidate = _visible_candidate(candidate_id, db, user)
    service.dismiss_merge_candidate(candidate, user, db); db.commit()
    return {"status": "dismissed"}
