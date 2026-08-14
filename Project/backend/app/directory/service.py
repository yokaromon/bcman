import re
import unicodedata
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from ..models import BusinessCard, Contact, Photo, User, now
from ..services import visible_photo_query
from .models import Company, CompanyContact, MergeCandidate, Person, PersonContact

# --- 正規化。「かな正規化一致」「websiteドメイン一致」の基準（docs/directory/CONTEXT.md 参照） ---

COMPANY_SUFFIXES = re.compile(r"(株式会社|有限会社|合同会社|一般社団法人|公益社団法人|Co\.,?\s*Ltd\.?|Inc\.?|Corporation|Corp\.?)")

def _normalize_text(value: str | None) -> str:
    if not value: return ""
    text = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", text).lower()

def normalize_person_key(person_name: str | None, company_name: str | None) -> str:
    return _normalize_text(person_name) + "|" + _normalize_text(company_name)

def normalize_company_key(company_name: str | None) -> str:
    without_suffix = COMPANY_SUFFIXES.sub("", company_name or "")
    return _normalize_text(without_suffix)

def website_domain(website: str | None) -> str:
    if not website: return ""
    candidate = website if "//" in website else f"//{website}"
    host = (urlparse(candidate).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host

# --- 可視範囲。visible_photo_query(Organization/Group/Sharing Mode)をContact経由に伸ばす ---

def visible_contact_query(db: Session, user: User):
    photo_id_subquery = visible_photo_query(db, user).with_entities(Photo.id).subquery()
    return db.query(Contact).join(BusinessCard, BusinessCard.id == Contact.card_id).filter(BusinessCard.photo_id.in_(photo_id_subquery))

def _person_id_for_contact(db: Session, contact_id: str) -> str | None:
    row = db.query(PersonContact).filter_by(contact_id=contact_id).first()
    return row.person_id if row else None

def _company_id_for_contact(db: Session, contact_id: str) -> str | None:
    row = db.query(CompanyContact).filter_by(contact_id=contact_id).first()
    return row.company_id if row else None

# --- Confirmed Contact登録時のフック ---

def register_confirmed_contact(contact_id: str, user: User, db: Session) -> None:
    contact = db.get(Contact, contact_id)
    person = Person(organization_id=user.organization_id); db.add(person); db.flush()
    db.add(PersonContact(person_id=person.id, contact_id=contact.id))
    _suggest_person_candidates(contact, user, db)

    if _normalize_text(contact.company_name):
        company = Company(organization_id=user.organization_id); db.add(company); db.flush()
        db.add(CompanyContact(company_id=company.id, contact_id=contact.id))
        _suggest_company_candidates(contact, user, db)
    db.flush()

def _suggest_person_candidates(contact: Contact, user: User, db: Session) -> None:
    visible = visible_contact_query(db, user).filter(Contact.id != contact.id)
    matched_person_ids: set[str] = set()
    if _normalize_text(contact.email):
        for other in visible.filter(Contact.email == contact.email):
            target_person_id = _person_id_for_contact(db, other.id)
            if target_person_id and target_person_id not in matched_person_ids:
                matched_person_ids.add(target_person_id)
                db.add(MergeCandidate(kind="person", contact_id=contact.id, target_person_id=target_person_id, signal="email_exact"))
    key = normalize_person_key(contact.person_name, contact.company_name)
    if key != "|":
        for other in visible:
            if normalize_person_key(other.person_name, other.company_name) != key: continue
            target_person_id = _person_id_for_contact(db, other.id)
            if target_person_id and target_person_id not in matched_person_ids:
                matched_person_ids.add(target_person_id)
                db.add(MergeCandidate(kind="person", contact_id=contact.id, target_person_id=target_person_id, signal="name_company_kana"))

def _suggest_company_candidates(contact: Contact, user: User, db: Session) -> None:
    visible = visible_contact_query(db, user).filter(Contact.id != contact.id)
    matched_company_ids: set[str] = set()
    domain = website_domain(contact.website)
    if domain:
        for other in visible:
            if website_domain(other.website) != domain: continue
            target_company_id = _company_id_for_contact(db, other.id)
            if target_company_id and target_company_id not in matched_company_ids:
                matched_company_ids.add(target_company_id)
                db.add(MergeCandidate(kind="company", contact_id=contact.id, target_company_id=target_company_id, signal="website_domain"))
    key = normalize_company_key(contact.company_name)
    for other in visible:
        if normalize_company_key(other.company_name) != key: continue
        target_company_id = _company_id_for_contact(db, other.id)
        if target_company_id and target_company_id not in matched_company_ids:
            matched_company_ids.add(target_company_id)
            db.add(MergeCandidate(kind="company", contact_id=contact.id, target_company_id=target_company_id, signal="company_kana"))

# --- 統合・Split ---

def accept_merge_candidate(candidate: MergeCandidate, user: User, db: Session) -> None:
    if candidate.kind == "person":
        source_id = _person_id_for_contact(db, candidate.contact_id)
        if source_id and source_id != candidate.target_person_id:
            db.query(PersonContact).filter_by(person_id=source_id).update({"person_id": candidate.target_person_id})
            # 消えるPersonを別の保留候補が指していると宙に浮くので、生き残る側へ向け直す
            db.query(MergeCandidate).filter_by(target_person_id=source_id, status="pending").update({"target_person_id": candidate.target_person_id})
            db.query(Person).filter_by(id=source_id).delete()
        others = db.query(MergeCandidate).filter(MergeCandidate.kind == "person", MergeCandidate.contact_id == candidate.contact_id, MergeCandidate.status == "pending", MergeCandidate.id != candidate.id)
    else:
        source_id = _company_id_for_contact(db, candidate.contact_id)
        if source_id and source_id != candidate.target_company_id:
            db.query(CompanyContact).filter_by(company_id=source_id).update({"company_id": candidate.target_company_id})
            db.query(MergeCandidate).filter_by(target_company_id=source_id, status="pending").update({"target_company_id": candidate.target_company_id})
            db.query(Company).filter_by(id=source_id).delete()
        others = db.query(MergeCandidate).filter(MergeCandidate.kind == "company", MergeCandidate.contact_id == candidate.contact_id, MergeCandidate.status == "pending", MergeCandidate.id != candidate.id)
    for other in others: other.status, other.resolved_at, other.resolved_by_user_id = "dismissed", now(), user.id
    candidate.status, candidate.resolved_at, candidate.resolved_by_user_id = "accepted", now(), user.id

def dismiss_merge_candidate(candidate: MergeCandidate, user: User, db: Session) -> None:
    candidate.status, candidate.resolved_at, candidate.resolved_by_user_id = "dismissed", now(), user.id

def split_person_contact(person_id: str, contact_id: str, db: Session) -> Person:
    link = db.query(PersonContact).filter_by(person_id=person_id, contact_id=contact_id).first()
    if not link: raise ValueError("この人物にこの名刺は含まれていません")
    remaining = db.query(PersonContact).filter_by(person_id=person_id).count()
    if remaining <= 1: raise ValueError("これ以上分離できません")
    new_person = Person(organization_id=db.get(Person, person_id).organization_id)
    db.add(new_person); db.flush()
    link.person_id = new_person.id
    return new_person

def split_company_contact(company_id: str, contact_id: str, db: Session) -> Company:
    link = db.query(CompanyContact).filter_by(company_id=company_id, contact_id=contact_id).first()
    if not link: raise ValueError("この企業にこの名刺は含まれていません")
    remaining = db.query(CompanyContact).filter_by(company_id=company_id).count()
    if remaining <= 1: raise ValueError("これ以上分離できません")
    new_company = Company(organization_id=db.get(Company, company_id).organization_id)
    db.add(new_company); db.flush()
    link.company_id = new_company.id
    return new_company

# --- 一覧・詳細の組み立て ---

SIGNAL_LABELS = {"email_exact": "メール一致", "name_company_kana": "氏名・会社名一致", "company_kana": "会社名一致", "website_domain": "Webサイト一致"}

def _touch_rows(db: Session, user: User, contact_ids: list[str]) -> list[dict]:
    if not contact_ids: return []
    rows = visible_contact_query(db, user).filter(Contact.id.in_(contact_ids)).order_by(Contact.exchanged_at.desc().nullslast()).all()
    owner_ids = {row.card_owner_user_id for row in rows if row.card_owner_user_id}
    owners = {u.id: u.name for u in db.query(User).filter(User.id.in_(owner_ids))} if owner_ids else {}
    return [{
        "contact_id": row.id, "person_name": row.person_name, "company_name": row.company_name,
        "department": row.department, "position": row.position, "exchanged_at": row.exchanged_at,
        "card_owner": {"id": row.card_owner_user_id, "name": owners.get(row.card_owner_user_id)} if row.card_owner_user_id else None,
    } for row in rows]

def list_persons(db: Session, user: User) -> list[dict]:
    visible_ids = {c.id for c in visible_contact_query(db, user).with_entities(Contact.id)}
    persons: dict[str, list[str]] = {}
    for link in db.query(PersonContact).filter(PersonContact.contact_id.in_(visible_ids)):
        persons.setdefault(link.person_id, []).append(link.contact_id)
    result = []
    for person_id, contact_ids in persons.items():
        touches = _touch_rows(db, user, contact_ids)
        headline = touches[0] if touches else None
        result.append({
            "id": person_id, "display_name": headline["person_name"] if headline else None,
            "display_company": headline["company_name"] if headline else None,
            "contact_count": len(touches), "latest_exchanged_at": headline["exchanged_at"] if headline else None,
        })
    return result

def person_detail(db: Session, user: User, person_id: str) -> dict | None:
    visible_ids = {c.id for c in visible_contact_query(db, user).with_entities(Contact.id)}
    contact_ids = [link.contact_id for link in db.query(PersonContact).filter_by(person_id=person_id) if link.contact_id in visible_ids]
    if not contact_ids: return None
    touches = _touch_rows(db, user, contact_ids)
    headline = touches[0]
    return {"id": person_id, "display_name": headline["person_name"], "display_company": headline["company_name"], "touch_history": touches}

def list_companies(db: Session, user: User) -> list[dict]:
    visible_ids = {c.id for c in visible_contact_query(db, user).with_entities(Contact.id)}
    companies: dict[str, list[str]] = {}
    for link in db.query(CompanyContact).filter(CompanyContact.contact_id.in_(visible_ids)):
        companies.setdefault(link.company_id, []).append(link.contact_id)
    result = []
    for company_id, contact_ids in companies.items():
        touches = _touch_rows(db, user, contact_ids)
        headline = touches[0] if touches else None
        people = {touch["person_name"] for touch in touches if touch["person_name"]}
        result.append({
            "id": company_id, "display_name": headline["company_name"] if headline else None,
            "person_count": len(people), "latest_exchanged_at": headline["exchanged_at"] if headline else None,
        })
    return result

def company_detail(db: Session, user: User, company_id: str) -> dict | None:
    visible_ids = {c.id for c in visible_contact_query(db, user).with_entities(Contact.id)}
    contact_ids = [link.contact_id for link in db.query(CompanyContact).filter_by(company_id=company_id) if link.contact_id in visible_ids]
    if not contact_ids: return None
    touches = _touch_rows(db, user, contact_ids)
    return {"id": company_id, "display_name": touches[0]["company_name"], "touch_history": touches}

def list_merge_candidates(db: Session, user: User) -> list[dict]:
    visible_ids = {c.id for c in visible_contact_query(db, user).with_entities(Contact.id)}
    candidates = db.query(MergeCandidate).filter(MergeCandidate.status == "pending", MergeCandidate.contact_id.in_(visible_ids)).order_by(MergeCandidate.created_at.desc()).all()
    contacts = {c.id: c for c in db.query(Contact).filter(Contact.id.in_([row.contact_id for row in candidates]))}
    result = []
    for row in candidates:
        contact = contacts.get(row.contact_id)
        target_detail = person_detail(db, user, row.target_person_id) if row.kind == "person" else company_detail(db, user, row.target_company_id)
        result.append({
            "id": row.id, "kind": row.kind, "signal": row.signal, "signal_label": SIGNAL_LABELS.get(row.signal, row.signal),
            "contact_id": row.contact_id, "contact_person_name": contact.person_name if contact else None,
            "contact_company_name": contact.company_name if contact else None,
            "target_id": row.target_person_id if row.kind == "person" else row.target_company_id,
            "target_display_name": target_detail["display_name"] if target_detail else None,
        })
    return result
