from .normalize import normalize_for_search
from .schemas import CONTACT_FIELDS

# Contact.search_text の組み立て。services（構造化のたびに更新する）と
# contact_search（同じ規則で検索語を作る）の両方から使うため、依存の無い所に置く。

# 項目をまたいだ偶然の一致（会社名の末尾＋部署の先頭など）を作らないための区切り。
# 検索語は正規化で空白が落ちるので、この文字が語に混ざることはない。
FIELD_SEPARATOR = "\n"

def build_search_text(contact) -> str:
    """Contact の全項目を正規化して連結した、検索専用の文字列を返す。"""
    return FIELD_SEPARATOR.join(normalize_for_search(getattr(contact, field)) for field in CONTACT_FIELDS)

def refresh_search_text(contact) -> None:
    contact.search_text = build_search_text(contact)
