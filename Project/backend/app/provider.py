"""運営者（Provider Operator）だけが使えるエンドポイント。

Organization と初期管理者の払い出し、および任意利用者への再招待だけを扱う。
名刺・連絡先へのアクセスは一切与えない。1ファイルに閉じてあるのは、
「新設したエンドポイントだけを守っている」ことをこのファイルを読むだけで
検証できるようにするため（docs/identity/adr/0002）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth
from .database import get_db
from .invitations import issue_invitation
from .models import Group, Organization, User, UserGroup
from .schemas import OrganizationCreateInput

router = APIRouter(prefix="/api/provider", tags=["provider"])


def require_provider_operator(user: User = Depends(auth.current_user)) -> User:
    """role とは直交する能力なので、require_admin を連鎖させない。"""
    if not user.is_provider_operator: raise HTTPException(403, "権限がありません")
    return user


@router.get("/organizations")
def list_organizations(db: Session = Depends(get_db), _: User = Depends(require_provider_operator)):
    organizations = db.query(Organization).order_by(Organization.created_at.desc()).all()
    counts = {org.id: db.query(User).filter_by(organization_id=org.id).count() for org in organizations}
    return [
        {"id": org.id, "name": org.name, "code": org.code, "sharing_mode": org.sharing_mode,
         "created_at": org.created_at, "user_count": counts[org.id]}
        for org in organizations
    ]


@router.post("/organizations")
def create_organization(body: OrganizationCreateInput, db: Session = Depends(get_db),
                        operator: User = Depends(require_provider_operator)):
    from .main import create_invited_user, record_audit  # 循環importを避けるため呼び出し時に解決する

    if db.query(Organization).filter_by(code=body.code).first():
        raise HTTPException(409, "その会社コードは既に使われています")
    if db.query(Organization).filter_by(name=body.name).first():
        raise HTTPException(409, "その会社名は既に登録されています")

    org = Organization(name=body.name, code=body.code, sharing_mode=body.sharing_mode)
    db.add(org); db.flush()
    group = Group(organization_id=org.id, name=body.group_name)
    db.add(group); db.flush()
    admin = create_invited_user(db, org.id, body.admin_username, body.admin_name, "admin", operator)
    db.add(UserGroup(user_id=admin.id, group_id=group.id))

    issued = issue_invitation(db, admin, operator)
    record_audit(db, operator, "provider_create_organization", "organization", org.id,
                 {"name": org.name, "code": org.code, "admin_username": admin.username})
    record_audit(db, operator, "provider_invite_user", "user", admin.id,
                 {"organization_id": org.id, "username": admin.username, "reissue": False})
    db.commit()
    return {"organization_id": org.id, "company_code": org.code, **issued}


@router.get("/organizations/{org_id}/users")
def list_organization_users(org_id: str, db: Session = Depends(get_db), _: User = Depends(require_provider_operator)):
    if not db.get(Organization, org_id): raise HTTPException(404, "会社が見つかりません")
    users = db.query(User).filter_by(organization_id=org_id).order_by(User.name).all()
    return [{"id": u.id, "username": u.username, "name": u.name, "role": u.role,
             "activated": u.activated_at is not None} for u in users]


@router.post("/organizations/{org_id}/users/{user_id}/invitations")
def reinvite(org_id: str, user_id: str, db: Session = Depends(get_db),
             operator: User = Depends(require_provider_operator)):
    """他社の管理者がロックアウトしたときの復旧経路。必ず監査ログに残す。"""
    from .main import record_audit

    target = db.get(User, user_id)
    if not target or target.organization_id != org_id: raise HTTPException(404, "利用者が見つかりません")
    issued = issue_invitation(db, target, operator)
    record_audit(db, operator, "provider_invite_user", "user", target.id,
                 {"organization_id": org_id, "username": target.username, "reissue": True})
    db.commit()
    return issued
