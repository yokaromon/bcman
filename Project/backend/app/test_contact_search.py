from types import SimpleNamespace

from app.contact_search import search_terms
from app.search_text import FIELD_SEPARATOR, build_search_text


def _contact(**values):
    return SimpleNamespace(**{
        "company_name": None, "company_name_kana": None, "department": None, "position": None,
        "person_name": None, "person_name_kana": None, "postal_code": None, "address": None,
        "telephone": None, "fax": None, "mobile": None, "email": None, "website": None, "notes": None,
        **values,
    })


def _matches(contact, query):
    """検索が行うのと同じ判定。全ての語が search_text に含まれるか。"""
    text = build_search_text(contact)
    return all(term in text for term in search_terms(query))


def test_space_in_the_stored_name_does_not_hide_it():
    # OCR は「青柳 太郎」と空けて読むことがある。詰めて探しても出る必要がある
    assert _matches(_contact(person_name="青柳 太郎"), "青柳太郎")


def test_full_width_and_half_width_are_the_same_word():
    assert _matches(_contact(company_name="ＢＣ Ｗｏｒｋｓ"), "bc works")


def test_half_width_kana_matches_full_width_kana():
    assert _matches(_contact(person_name_kana="ｱｵﾔｷﾞ"), "アオヤギ")


def test_phone_number_matches_with_and_without_hyphens():
    assert _matches(_contact(telephone="03-1234-5678"), "0312345678")
    assert _matches(_contact(telephone="0312345678"), "03-1234-5678")


def test_words_are_combined_with_and():
    contact = _contact(person_name="青柳 太郎", company_name="株式会社BC Works")
    assert _matches(contact, "青柳 BC")
    assert not _matches(contact, "青柳 存在しない会社")


def test_a_word_never_matches_across_two_fields():
    # 会社名の末尾と部署の先頭がつながって偶然一致することがあってはならない
    contact = _contact(company_name="山田工業", department="営業部")
    assert not _matches(contact, "工業営業")
    assert FIELD_SEPARATOR in build_search_text(contact)


def test_empty_query_has_no_terms():
    assert search_terms("") == []
    assert search_terms("   ") == []
