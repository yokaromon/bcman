from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import BusinessCard, Contact, Photo, User
from .normalize import normalize_for_search
from .services import card_image_revision, visible_contact_query

# 台帳検索。docs/CONTEXT.md の「台帳検索」参照。

# LIKE のワイルドカードを利用者の入力から無効化するためのエスケープ文字。
LIKE_ESCAPE = "\\"

# 台帳に出す範囲。既定は all（未確認も含む）。
LEDGER_STATUSES = ("all", "confirmed", "unconfirmed")
DEFAULT_LEDGER_STATUS = "all"

def search_terms(query: str | None) -> list[str]:
    """入力を空白区切りの検索語に分ける。正規化後に空になる語は捨てる。"""
    if not query: return []
    return [term for term in (normalize_for_search(word) for word in query.split()) if term]

def _like_pattern(term: str) -> str:
    escaped = term.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_")
    return f"%{escaped}%"

def visible_ledger_query(db: Session, user: User, query: str | None, status: str = DEFAULT_LEDGER_STATUS):
    """可視範囲の Contact を、検索語すべてを含むものに絞り込んだクエリを返す。

    未確認（未登録）も既定で含める。撮った名刺が台帳から引けないと「登録済みのはずなのに
    出てこない」と受け取られ、確認の押し忘れに気づく手がかりが無くなるため
    （2026-08-19、現場で頻発していた誤解）。確認済みかどうかは行ごとに示す。
    """
    result = visible_contact_query(db, user)
    if status == "confirmed":
        result = result.filter(Contact.confirmed.is_(True))
    elif status == "unconfirmed":
        result = result.filter(Contact.confirmed.is_(False))
    for term in search_terms(query):
        result = result.filter(Contact.search_text.like(_like_pattern(term), escape=LIKE_ESCAPE))
    return result

def search_contacts(db: Session, user: User, query: str | None, limit: int, offset: int, status: str = DEFAULT_LEDGER_STATUS) -> dict:
    base = visible_ledger_query(db, user, query, status)
    total = base.count()
    # 交換日は「実際に会った日」で、利用者が直せる値。台帳の既定順はこれに従う。
    # ただし交換日は確定時にしか入らないので、未確認は撮影日で代用する。これが無いと
    # 未確認が全件末尾へ沈み、台帳に出しても実質見えない。
    # 同日が並ぶので、決定的な順序になるよう登録時刻を第2キーに使う。
    recency = func.coalesce(Contact.exchanged_at, func.date(Photo.created_at))
    rows = (base.join(Photo, Photo.id == BusinessCard.photo_id)
            .order_by(recency.desc().nullslast(), Contact.created_at.desc())
            .offset(offset).limit(limit).all())

    cards = {card.id: card for card in db.query(BusinessCard).filter(BusinessCard.id.in_([row.card_id for row in rows]))} if rows else {}
    owner_ids = {row.card_owner_user_id for row in rows if row.card_owner_user_id}
    owners = {u.id: u.name for u in db.query(User).filter(User.id.in_(owner_ids))} if owner_ids else {}

    items = []
    for row in rows:
        card = cards.get(row.card_id)
        items.append({
            "contact_id": row.id,
            "card_id": row.card_id,
            "confirmed": bool(row.confirmed),
            "status": card.status if card else "confirmed",
            "image_revision": card_image_revision(card) if card else "",
            "person_name": row.person_name,
            "company_name": row.company_name,
            "department": row.department,
            "position": row.position,
            "exchanged_at": row.exchanged_at,
            "card_owner": {"id": row.card_owner_user_id, "name": owners.get(row.card_owner_user_id)} if row.card_owner_user_id else None,
        })
    return {"total": total, "items": items}
