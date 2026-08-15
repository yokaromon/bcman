import re
import unicodedata

# 名寄せ(directory)と台帳検索(contact_search)の両方が使う表記ゆれの吸収。
# どちらか一方だけ基準が変わると「統合候補には出るのに検索では出ない」が起きるため、
# 文脈をまたぐ共通の土台としてここに置く。

# NFKC のあとに残るダッシュ類（ハイフン・各種ダッシュ・マイナス記号）。
# 長音符 ー(U+30FC) は「コーヒー」の一部なので含めない。
_DASHES = re.compile(r"[-‐-―−]")

def normalize_text(value: str | None) -> str:
    """NFKC で全半角を揃え、空白を落として小文字化する。名寄せの一致基準。"""
    if not value: return ""
    text = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", text).lower()

def normalize_for_search(value: str | None) -> str:
    """検索用。normalize_text に加えてダッシュ類も落とす。
    OCR結果の電話番号は 03-1234-5678 と 0312345678 が混在するため。"""
    return _DASHES.sub("", normalize_text(value))
