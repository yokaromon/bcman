from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.contact_search import search_contacts
from app.database import Base
from app.models import BusinessCard, Contact, Group, Organization, Photo, User
from app.search_text import refresh_search_text


@pytest.fixture()
def db(tmp_path):
    # 実際に SQLite へ問い合わせて、LIKE のエスケープと nullslast が通ることまで確かめる
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session) -> User:
    org = Organization(name="テスト商事", sharing_mode="shared")
    db.add(org); db.flush()
    group = Group(organization_id=org.id, name="一般")
    db.add(group); db.flush()
    user = User(organization_id=org.id, username="admin", name="管理者", role="admin", password_hash="x", totp_secret="x")
    db.add(user); db.flush()
    return user


def _add_contact(db: Session, user: User, *, exchanged_at: date | None, confirmed=True, **fields) -> Contact:
    group = db.query(Group).filter_by(organization_id=user.organization_id).first()
    photo = Photo(organization_id=user.organization_id, group_id=group.id, original_filename="p.jpg", storage_path="")
    db.add(photo); db.flush()
    card = BusinessCard(photo_id=photo.id, detected_image_path="", corrected_image_path="", status="confirmed" if confirmed else "review_required")
    db.add(card); db.flush()
    contact = Contact(card_id=card.id, confirmed=confirmed, exchanged_at=exchanged_at, card_owner_user_id=user.id, **fields)
    refresh_search_text(contact)
    db.add(contact); db.flush()
    return contact


def test_finds_a_confirmed_contact_despite_spacing(db):
    user = _seed(db)
    _add_contact(db, user, exchanged_at=date(2026, 3, 14), person_name="青柳 太郎", company_name="株式会社BC Works")

    result = search_contacts(db, user, "青柳太郎", limit=50, offset=0)

    assert result["total"] == 1
    assert result["items"][0]["person_name"] == "青柳 太郎"
    assert result["items"][0]["card_owner"]["name"] == "管理者"


def test_unconfirmed_contacts_stay_out_of_the_ledger(db):
    user = _seed(db)
    _add_contact(db, user, exchanged_at=date(2026, 3, 14), person_name="未登録 花子", confirmed=False)

    assert search_contacts(db, user, "未登録", limit=50, offset=0)["total"] == 0


def test_empty_query_returns_everything_newest_exchange_first(db):
    user = _seed(db)
    _add_contact(db, user, exchanged_at=date(2025, 1, 1), person_name="古い")
    _add_contact(db, user, exchanged_at=date(2026, 6, 1), person_name="新しい")
    # 交換日が無い行が先頭に来てはいけない
    _add_contact(db, user, exchanged_at=None, person_name="日付なし")

    result = search_contacts(db, user, "", limit=50, offset=0)

    assert result["total"] == 3
    assert [item["person_name"] for item in result["items"]] == ["新しい", "古い", "日付なし"]


def test_paging_walks_the_whole_result(db):
    user = _seed(db)
    for day in range(1, 4):
        _add_contact(db, user, exchanged_at=date(2026, 1, day), person_name=f"担当{day}")

    first = search_contacts(db, user, "", limit=2, offset=0)
    second = search_contacts(db, user, "", limit=2, offset=2)

    assert first["total"] == 3 and second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1


def test_wildcards_in_the_query_are_not_treated_as_patterns(db):
    user = _seed(db)
    _add_contact(db, user, exchanged_at=date(2026, 1, 1), person_name="青柳")

    # "%" が任意文字列として効いてしまうと、無関係な検索語で全件が出てしまう
    assert search_contacts(db, user, "%", limit=50, offset=0)["total"] == 0
