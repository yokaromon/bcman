from datetime import datetime
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base
from ..models import now, uid

# docs/directory/CONTEXT.md 参照。Contact自体には列を足さず、ここの紐付けテーブルで
# ID参照する（Directory → Business Card Management には書き戻さない）。

class Person(Base):
    __tablename__ = "directory_persons"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

class Company(Base):
    __tablename__ = "directory_companies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

class PersonContact(Base):
    """あるConfirmed ContactがどのPersonに属するか。1 Contactは常にちょうど1件持つ
    （単独でも「1人だけのPerson」として作られるため）。"""
    __tablename__ = "directory_person_contacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    person_id: Mapped[str] = mapped_column(ForeignKey("directory_persons.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

class CompanyContact(Base):
    __tablename__ = "directory_company_contacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("directory_companies.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

class MergeCandidate(Base):
    """Confirmed Contact作成時に1回だけ生成される統合候補。定期再スキャンはしない
    （docs/directory/CONTEXT.md の Merge Candidate 参照）。"""
    __tablename__ = "directory_merge_candidates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String)  # "person" | "company"
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    target_person_id: Mapped[str | None] = mapped_column(ForeignKey("directory_persons.id"), nullable=True)
    target_company_id: Mapped[str | None] = mapped_column(ForeignKey("directory_companies.id"), nullable=True)
    signal: Mapped[str] = mapped_column(String)  # "email_exact" | "name_company_kana" | "company_kana" | "website_domain"
    status: Mapped[str] = mapped_column(String, default="pending")  # "pending" | "accepted" | "dismissed"
    created_at: Mapped[datetime] = mapped_column(default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
