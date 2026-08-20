# BCMan Card Pickup / Recognition V2

本番を変更する前に、実写真で次のパイプラインを磨き、固定Ground Truthで評価する独立環境です。

1. 名刺の検出と台形補正
2. 棄権可能なローカル向き判定
3. ローカル文字領域検出とPaddleOCR診断
4. 管理対象 `app.ykr.ltd` による最終OCR
5. 根拠行付きContact構造化とローカル検証

実写真、出力、OCR本文、Contact値、新しい向き/OCR Ground Truth、モデル本体、APIキーはGit管理しません。

## ⚠️ Project/backend/app/recognition_v2/ との同期

`detector.py` / `orientation.py` / `alignment.py` / `text_regions.py` / `recognition_contract.py` /
`prompts/` / `schemas/` は本番 `Project/backend/app/recognition_v2/` へ移植済みで、**両側が
同一内容であることを前提にしている**。本番側だけ直して pickup へ戻し忘れると、pickup での
評価数値と本番の実際の挙動がずれる（2026-08-18に実際に発生：本番のSIGSEGV/std::exception対策を
先に本番側だけへ入れてしまっていた）。

```
python ../scripts/check_v2_parity.py
```

どちらかを直したら、コミット前に必ず実行して揃っているか確認すること。`git config core.hooksPath
scripts/hooks`（リポジトリルートで一度だけ）を設定していれば、該当ファイルを触るcommitで自動実行される。

## 環境構築

Windows版PaddleはAMD64 Pythonを使います。この環境はPython 3.11 AMD64、
PaddlePaddle 3.0.0、PaddleOCR/PaddleX 3.0.3に固定しています。

```powershell
cd C:\Projects\job\int\aoyagi\source\bcman\pickup
poetry env use C:\Users\kmoto\AppData\Local\Programs\Python\Python311\python.exe
poetry install
poetry run python provision_models.py
poetry run python provision_models.py --verify-only
```

`provision_models.py` は `model_manifest.json` の固定URLからモデルを取得し、archiveと
必須ファイルのSHA-256を検証します。通常起動では、完全検証済みmanifest SHA、期待SHA、
ファイルサイズ、更新時刻が一致するときだけ再ハッシュを省略します。runtime downloadや
`latest` aliasは使いません。モデルは `models/` へ置かれ、Gitには入りません。

## 実行モード

入力は `picture` 直下、出力は `output/<元画像stem>/` です。`--source` を省略すると
直下の全画像を処理します。画像単位の一時ディレクトリを完成させてから全置換するため、
途中失敗した半端な世代は公開されません。

### 抽出だけ

```powershell
poetry run python bcpickup.py --pipeline extraction
```

1画像あたり1〜12枚が保証範囲です。13枚以上の人手Ground Truthも保存できますが、検出は
best effortです。抽出はローカルCPUのみで、外部通信しません。

### 回転とローカルOCRまで（既定）

```powershell
poetry run python bcpickup.py
# 同義
poetry run python bcpickup.py --pipeline local
```

向き分類器を4回転へ一括適用し、元向きの推定が4/4で整合して閾値を満たすときだけ自動回転
します。矛盾時だけ4方向のOCR可読性を比較し、僅差なら `uncertain` のまま撮影方向でOCRを
続けます。アルファベット・数字の非対称字形は可読性スコアの5%以下の補助証拠です。

向きだけを全写真へ通す場合は、OCR成果物を作らない専用モードを使えます。

```powershell
poetry run python bcpickup.py --pipeline orientation --output-dir orientation_output
poetry run python evaluate_orientation_consistency.py --output-dir orientation_output --report orientation-consistency.json
```

人工4回転テストは相対方向の破綻を検出します。絶対に正立しているかは人手GTで別に測ります。

```powershell
poetry run python evaluate_orientation.py --output-dir orientation_output --dataset-role development --minimum-cards 1
```

### ykrの最終OCRとContact構造化まで

`pickup/.env.example` を `pickup/.env` へコピーして、固定モデル名とAPIキーを設定します。
接続先はコード上も `https://app.ykr.ltd` だけを許可します。

```powershell
poetry run python bcpickup.py --pipeline full
```

ykr OCRとContact構造化は独立した段階で、それぞれ初回＋1再試行までです。1カード最大4通信、
90秒timeoutです。成功済みOCRは構造化だけの再試行で再送しません。通常再実行は画像hash、
向き、モデル、prompt、schemaが同じ成功結果を再利用します。

明示的に再認識するときだけ次を使います。以前のykr成果物は
`recognition_history/` へ退避され、ユーザー編集値を上書きする用途には使いません。

```powershell
poetry run python bcpickup.py --pipeline full --force-recognition
```

APIの通常ログへ画像、request body、OCR本文、Contact値を出す実装はありません。構造・型・
根拠IDが不正な応答は登録せず、その段階の再試行を1回だけ消費します。一方、形式検証や
根拠テキスト不一致は値を残してReview Flagにします。

## 出力

各抽出カードは次の形で保存されます。`full` 以外でも全ファイル名を作り、未実行ykr段階は
`status: not_requested` とします。

```text
output/IMG_0001/
  card01.png
  card01.orientation.json
  card01.oriented.png
  card01.ocr.paddle.json
  card01.ocr.ykr.json
  card01.contact.paddle.json
  card01.contact.ykr.json
  recognition_history/       # 明示的な再認識をした場合
  overlay.jpg
  result.json
```

ローカルPaddleのpolygonとykr行は強制的に混ぜません。一致行は関連付け、ykrだけの行は
`region_id: null`、ローカルだけの領域は `text: null` として `alignment_status: unmatched`
で残します。Contactは `present / absent / unreadable`、表示値、候補値、根拠行、ローカル
正規化値、Review Flagを分離します。メールアドレスがないカードは正常な `absent` です。

## 人手Ground Truth

四隅、向き、OCR/Contactを別々に登録します。四隅GTの各カードには検出順と独立した
`ground_truth_card_id` が付き、角を微修正してもIoUで同じIDを維持します。

```powershell
# 原画像上の全名刺の四隅。正解入力数に上限なし
poetry run python annotate_ground_truth.py --open-browser

# そのまま/右90/180/左90/不明
poetry run python annotate_orientation.py --open-browser

# 行文字、印刷/手書き、可読性、14 Contact項目の状態と正解表記
poetry run python annotate_ocr.py --open-browser
```

AIのfull pipeline成果物を修正用の下書きとして読み込む場合は、次のように起動します。
下書きは未確認のままではGround Truthや評価対象にならず、人が「確認して保存」したカードだけが
正解データへ昇格します。

```powershell
poetry run python annotate_ocr.py --draft-output-dir recognition_output --open-browser
```

固定holdoutは開発GTとは別ファイルへ作り、3画面すべてへ同じroleを明示します。

```powershell
poetry run python annotate_ground_truth.py --input-dir holdout_picture --target holdout_extraction_ground_truth.json --dataset-role holdout --open-browser
poetry run python annotate_orientation.py --input-dir holdout_picture --extraction-ground-truth holdout_extraction_ground_truth.json --target holdout_orientation_ground_truth.json --dataset-role holdout --open-browser
poetry run python annotate_ocr.py --input-dir holdout_picture --extraction-ground-truth holdout_extraction_ground_truth.json --orientation-ground-truth holdout_orientation_ground_truth.json --target holdout_ocr_ground_truth.json --dataset-role holdout --open-browser
```

新しい画像を追加した場合、起動中画面を再読み込みすると現在の `picture` を再走査します。
向き不明を許可し、不明でもOCR Ground Truthと実行結果を登録できます。

## 評価

抽出評価は、全写真の枚数完全一致、全カードIoU 0.90以上、各写真20秒以内を要求します。

```powershell
poetry run python evaluate.py
poetry run python evaluate.py --annotated-only  # 開発途中だけ
```

向き・OCR・Contactの本番promotion評価は、調整に使わない固定holdout 300ユニークカード以上を
要求します。回転コピーを別カードには数えません。

```powershell
poetry run python evaluate_recognition.py --engine paddle
poetry run python evaluate_recognition.py --engine ykr --report recognition-report.json
```

既定は `--dataset-role holdout` です。開発途中の診断だけは
`--dataset-role development --minimum-cards 0` を明示します。

向きは自動確定accuracyとuncertain率、OCRはstrict/正規化CER、Contactは状態accuracyとpresent値の
正規化完全一致を別々に報告します。各段階が `CONTEXT.md` のAcceptanceを満たすまで
`Project/backend` へ移植しません。追加学習は固定pretrained baselineの失敗分析後だけ行い、
holdoutを学習・prompt・閾値調整・モデル選択へ使いません。

## 現在地（2026-08-18）

- 抽出→向きの全件再実行: 開発57画像、256カードを生成
- 抽出評価: 56/57画像が枚数・IoU・時間gateを通過。`IMG_6630.png` は1枚検出だがIoU 0.713で失敗
  （既知の例外として保留。holdoutでも同種の失敗が出た場合のみ再調査する）
- 向きの人工4回転整合性: 256/256カード合格（1,024変種、`uncertain` 0）
- 向きGround Truth（人手）: 256/256カード登録完了。`evaluate_orientation.py --dataset-role
  development`でauto_accuracy 100%（255/255、`IMG_6630.png`の1カードのみ抽出未達で対象外）、
  uncertainty 0%、p95 78.32ms。development setの範囲でOrientation Acceptance基準（精度99%
  以上・uncertain 15%以下・6秒/card以下）を満たした
- 安定 `ground_truth_card_id`: 256/256一意
- 実full smoke: 57画像中19画像分をykr本実行済み（`recognition_output/`、ocr.ykr.json 134件成功）
- OCR/Contact Ground Truth: 3カードのみ登録済み。`evaluate_recognition.py`側の比較バグ
  （正解値をハイフン等除去前の生表記のまま予測側の`normalized_value`と比較していた）を修正し、
  修正後は3カード全項目で state_accuracy 1.0 / present_value_accuracy 1.0 を確認。
  ただしn=3では判断材料として不十分
- 自動テスト: 66件合格（評価スクリプト修正後の11件再実行含め合格）

development setでの向き判定はAcceptance基準をクリアしたと判断。次のpromotion blockerは、
development 256カードとは別の未見300カード固定holdoutへの四隅・向き・OCR/Contact人手登録と
Acceptance評価です（現在着手中）。
本番統合はADR 0019どおりfeature flagを既定OFFで行い、既存カードを再処理せず、V1をrollback
経路として残します。
