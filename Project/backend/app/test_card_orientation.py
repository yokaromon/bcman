from app.services import ORIENTATION_ACCEPT_SIGNALS, ocr_text_score, orientation_order

UPRIGHT_CARD_TEXT = """株式会社ヨカロモン
営業部 部長
青柳 太郎
〒150-0002
東京都渋谷区渋谷1-2-3
TEL 03-1234-5678
FAX 03-1234-5679
taro.aoyagi@example.co.jp
https://www.example.co.jp
"""


def test_upright_card_text_clears_the_acceptance_threshold():
    """正しい向きで読めた名刺は、打ち切り閾値を余裕をもって超える。"""
    assert ocr_text_score(UPRIGHT_CARD_TEXT) >= ORIENTATION_ACCEPT_SIGNALS


def test_sparse_card_text_stays_below_the_threshold():
    """会社名と氏名しか読めていない結果では打ち切らず、他の向きも試させる。"""
    assert ocr_text_score("株式会社ヨカロモン\n青柳 太郎") < ORIENTATION_ACCEPT_SIGNALS


def test_fragmented_reading_scores_zero():
    """向きを間違えたときに返る短い断片は候補にしない。"""
    assert ocr_text_score("木 一 ノ") == 0
    assert ocr_text_score("") == 0
    assert ocr_text_score(None) == 0


def test_refusal_scores_zero_even_when_it_is_long():
    """「読み取れません」と説明されただけの応答は、長くても0点にする。"""
    refusal = "この画像は不鮮明なため、文字を読み取れませんでした。別の画像をお試しください。"
    assert ocr_text_score(refusal) == 0
    assert ocr_text_score("I'm sorry, I cannot read the text in this image reliably.") == 0


def test_english_only_card_is_still_recognised():
    """英字のみの名刺でも、法人格・メール・URLで閾値に届く。"""
    english = "Yokaromon Inc.\nTaro Aoyagi\ntaro@example.com\nhttps://example.com"
    assert ocr_text_score(english) >= ORIENTATION_ACCEPT_SIGNALS


def test_landscape_crop_tries_upright_orientations_first():
    """横長の切り抜きは横型名刺が素直に写っている可能性が高い。"""
    assert orientation_order(800, 500) == [0, 180, 90, 270]


def test_portrait_crop_suspects_a_sideways_landscape_card_first():
    """縦長の切り抜きは、縦型名刺の正立より横型名刺の横倒しのほうが起きやすい。"""
    assert orientation_order(500, 800) == [90, 270, 0, 180]


def test_square_crop_falls_back_to_the_landscape_order():
    assert orientation_order(600, 600) == [0, 180, 90, 270]
