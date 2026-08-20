from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from annotation_cards import (
    atomic_write_json,
    card_by_id,
    encoded_png,
    extraction_cards,
)
from annotate_ground_truth import (
    DEFAULT_TARGET as DEFAULT_EXTRACTION_GT,
    _load_document as load_extraction_ground_truth,
)
from bcpickup import DEFAULT_INPUT_DIR


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = BASE_DIR / "orientation_ground_truth.json"
SCHEMA_VERSION = 1
ANNOTATION_METHOD = "manual-card-orientation"
ROTATIONS = {0, 90, 180, 270}


def _new_document(dataset_role: str = "development") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "dataset_role": dataset_role,
        "cards": {},
    }


def _load_document(path: Path) -> dict:
    if not path.exists():
        return _new_document()
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("annotation_method") != ANNOTATION_METHOD
        or not isinstance(document.get("cards"), dict)
    ):
        raise ValueError("向きGround Truthの形式が不正です")
    return document


def initialize_dataset_role(target: Path, dataset_role: str) -> dict:
    if target.exists():
        document = _load_document(target)
        if document.get("dataset_role") != dataset_role:
            raise ValueError(
                f"既存GTはdataset_role={document.get('dataset_role')}です"
            )
        return document
    document = _new_document(dataset_role)
    atomic_write_json(target, document)
    return document


def save_orientation(
    target: Path,
    input_dir: Path,
    extraction_gt: Path,
    card_id: str,
    correction_rotation: object,
) -> dict:
    cards = extraction_cards(input_dir, extraction_gt)
    card = card_by_id(cards, card_id)
    if correction_rotation == "unknown":
        correction: int | str = "unknown"
    else:
        try:
            correction = int(correction_rotation)
        except (TypeError, ValueError) as exc:
            raise ValueError("向きは0/90/180/270/unknownです") from exc
        if correction not in ROTATIONS:
            raise ValueError("向きは0/90/180/270/unknownです")
    document = _load_document(target)
    saved = {
        "ground_truth_card_id": card_id,
        "source": card["source"],
        "source_sha256": card["source_sha256"],
        "card_index": card["card_index"],
        "correction_rotation": correction,
        "annotated_at": datetime.now(timezone.utc).isoformat(),
    }
    document["cards"][card_id] = saved
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(target, document)
    return saved


def _state(input_dir: Path, extraction_gt: Path, target: Path) -> dict:
    saved = _load_document(target)["cards"]
    cards = []
    for item in extraction_cards(input_dir, extraction_gt):
        annotation = saved.get(item["ground_truth_card_id"])
        cards.append(
            {
                "ground_truth_card_id": item["ground_truth_card_id"],
                "source": item["source"],
                "card_index": item["card_index"],
                "annotated": annotation is not None,
                "correction_rotation": (
                    annotation["correction_rotation"] if annotation else None
                ),
            }
        )
    return {"cards": cards}


HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BCMan 向きGT</title>
<style>body{margin:0;background:#17191d;color:#eef2f7;font-family:system-ui,sans-serif}header{position:sticky;top:0;background:#252930;padding:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}button,select{font:inherit;padding:8px 12px}.selected{outline:3px solid #52a8ff;background:#dbeafe}main{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:16px;padding:16px}#imagebox{background:#0d0f12;display:grid;place-items:center;min-height:70vh}img{max-width:100%;max-height:75vh}.ok{color:#72d39b}.warn{color:#ffb454}@media(max-width:800px){main{grid-template-columns:1fr}}</style></head><body>
<header><button id="prev">← 前</button><select id="cards"></select><button id="next">次 →</button><span id="status"></span></header>
<main><div id="imagebox"><img id="image"></div><aside><h2>正しい向き</h2><p>画像が正立するために必要な時計回り回転を選び、保存します。不明を許可します。</p>
<p id="label"></p><div id="choices"><button data-v="0">そのまま 0°</button><button data-v="90">右90°</button><button data-v="180">180°</button><button data-v="270">左90°</button><button data-v="unknown">不明</button></div>
<p><button id="save">保存して次へ</button></p><p>キー: 0/1/2/3/U、Enterで保存</p></aside></main>
<script>const sel=document.querySelector('#cards'),img=document.querySelector('#image'),statusEl=document.querySelector('#status'),label=document.querySelector('#label');let state={cards:[]},index=0,value=null;
function status(t,k=''){statusEl.textContent=t;statusEl.className=k}function load(i){if(!state.cards.length)return;index=(i+state.cards.length)%state.cards.length;sel.value=index;const c=state.cards[index];value=c.correction_rotation;label.textContent=`${c.source} / card ${c.card_index}`;img.src='/card/'+encodeURIComponent(c.ground_truth_card_id)+'?r='+(value==='unknown'||value===null?0:value)+'&v='+Date.now();document.querySelectorAll('[data-v]').forEach(b=>b.classList.toggle('selected',String(value)===b.dataset.v));status(c.annotated?'保存済み':'未登録',c.annotated?'ok':'warn')}
document.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>{value=b.dataset.v==='unknown'?'unknown':Number(b.dataset.v);document.querySelectorAll('[data-v]').forEach(x=>x.classList.toggle('selected',x===b));const c=state.cards[index];img.src='/card/'+encodeURIComponent(c.ground_truth_card_id)+'?r='+(value==='unknown'?0:value)+'&v='+Date.now();status('未保存','warn')});
async function save(){if(value===null){alert('向きか不明を選んでください');return}const c=state.cards[index],r=await fetch('/api/orientation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ground_truth_card_id:c.ground_truth_card_id,correction_rotation:value})}),body=await r.json();if(!r.ok){status(body.error||'保存失敗','warn');return}c.annotated=true;c.correction_rotation=body.correction_rotation;load(index+1)}
document.querySelector('#save').onclick=save;document.querySelector('#prev').onclick=()=>load(index-1);document.querySelector('#next').onclick=()=>load(index+1);sel.onchange=()=>load(Number(sel.value));document.addEventListener('keydown',e=>{const m={'0':'0','1':'90','2':'180','3':'270','u':'unknown'},key=e.key.toLowerCase();if(key in m)document.querySelector(`[data-v="${m[key]}"]`).click();if(e.key==='Enter')save()});fetch('/api/state').then(r=>r.json()).then(s=>{state=s;sel.innerHTML=s.cards.map((c,i)=>`<option value="${i}">${c.annotated?'✓ ':''}${c.source} #${c.card_index}</option>`).join('');load(0)}).catch(e=>status(String(e),'warn'));</script></body></html>"""


def _handler(input_dir: Path, extraction_gt: Path, target: Path):
    class Handler(BaseHTTPRequestHandler):
        def send_value(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status); self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def send_json(self, status: int, value: object) -> None:
            self.send_value(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            try:
                if parsed.path == "/": return self.send_value(200, HTML.encode(), "text/html; charset=utf-8")
                if parsed.path == "/api/state": return self.send_json(200, _state(input_dir, extraction_gt, target))
                if parsed.path.startswith("/card/"):
                    card = card_by_id(extraction_cards(input_dir, extraction_gt), unquote(parsed.path[6:]))
                    rotation = int(parse_qs(parsed.query).get("r", ["0"])[0])
                    if rotation not in ROTATIONS: raise ValueError("不正な回転です")
                    return self.send_value(200, encoded_png(card, rotation), "image/png")
                self.send_json(404, {"error": "not found"})
            except Exception as exc: self.send_json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/orientation": return self.send_json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length))
                saved = save_orientation(target, input_dir, extraction_gt, payload.get("ground_truth_card_id", ""), payload.get("correction_rotation"))
                self.send_json(200, saved)
            except Exception as exc: self.send_json(400, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None: return
    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="名刺ごとの正しい向きGround Truthを作成")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--extraction-ground-truth", type=Path, default=DEFAULT_EXTRACTION_GT)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--port", type=int, default=8766); parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--dataset-role", choices=("development", "holdout"), default="development")
    args = parser.parse_args(); cards = extraction_cards(args.input_dir.resolve(), args.extraction_ground_truth.resolve())
    if not cards: parser.error("四隅Ground Truthのカードがありません")
    extraction_role = load_extraction_ground_truth(args.extraction_ground_truth.resolve()).get("dataset_role")
    if extraction_role != args.dataset_role: parser.error(f"Extraction GTはdataset_role={extraction_role}です")
    initialize_dataset_role(args.target.resolve(), args.dataset_role); server = ThreadingHTTPServer(("127.0.0.1", args.port), _handler(args.input_dir.resolve(), args.extraction_ground_truth.resolve(), args.target.resolve()))
    url=f"http://127.0.0.1:{args.port}/"; print(f"Orientation Ground Truth editor: {url}"); print("終了: Ctrl+C")
    if args.open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n終了しました")
    finally: server.server_close()
    return 0


if __name__ == "__main__": raise SystemExit(main())
