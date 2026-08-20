from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from annotation_cards import atomic_write_json, card_by_id, encoded_png, extraction_cards
from annotate_ground_truth import (
    DEFAULT_TARGET as DEFAULT_EXTRACTION_GT,
    _load_document as load_extraction_ground_truth,
)
from annotate_orientation import DEFAULT_TARGET as DEFAULT_ORIENTATION_GT, _load_document as load_orientation
from bcpickup import DEFAULT_INPUT_DIR
from evaluate_recognition import _artifact_map
from recognition_contract import CONTACT_FIELDS


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = BASE_DIR / "ocr_ground_truth.json"
SCHEMA_VERSION = 1
ANNOTATION_METHOD = "manual-ocr-and-contact"
LINE_SOURCES = {"printed", "handwritten", "mixed", "unknown"}
LEGIBILITY = {"readable", "partial", "unreadable"}
FIELD_STATES = {"present", "absent", "unreadable"}


def _new_document(dataset_role: str = "development") -> dict:
    return {"schema_version": 1, "annotation_method": ANNOTATION_METHOD, "dataset_role": dataset_role, "cards": {}}


def _load_document(path: Path) -> dict:
    if not path.exists(): return _new_document()
    document=json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or document.get("annotation_method") != ANNOTATION_METHOD or not isinstance(document.get("cards"),dict): raise ValueError("OCR Ground Truthの形式が不正です")
    return document


def initialize_dataset_role(target: Path, dataset_role: str) -> dict:
    if target.exists():
        document = _load_document(target)
        if document.get("dataset_role") != dataset_role:
            raise ValueError(f"既存GTはdataset_role={document.get('dataset_role')}です")
        return document
    document = _new_document(dataset_role); atomic_write_json(target, document); return document


def _validated_lines(raw: object) -> list[dict]:
    if not isinstance(raw, list): raise ValueError("linesは配列です")
    lines=[]
    for index,item in enumerate(raw,1):
        if not isinstance(item,dict): raise ValueError(f"行{index}がobjectではありません")
        text=item.get("text"); source=item.get("source"); legibility=item.get("legibility")
        if source not in LINE_SOURCES or legibility not in LEGIBILITY: raise ValueError(f"行{index}の種別が不正です")
        if text is not None and not isinstance(text,str): raise ValueError(f"行{index}のtextが不正です")
        text=text.strip() if isinstance(text,str) else None
        if legibility == "readable" and not text: raise ValueError(f"行{index}: readableにはtextが必要です")
        if not text: text=None
        lines.append({"ground_truth_line_id":f"gt-line-{index:03d}","text":text,"source":source,"legibility":legibility})
    return lines


def _validated_contact(raw: object) -> dict:
    if not isinstance(raw,dict) or set(raw) != set(CONTACT_FIELDS): raise ValueError("contactは14項目をすべて含めてください")
    result={}
    for name in CONTACT_FIELDS:
        item=raw[name]
        if not isinstance(item,dict) or item.get("state") not in FIELD_STATES: raise ValueError(f"{name}のstateが不正です")
        value=item.get("value")
        if value is not None and not isinstance(value,str): raise ValueError(f"{name}のvalueが不正です")
        value=value.strip() if isinstance(value,str) else None
        if item["state"] == "present" and not value: raise ValueError(f"{name}: presentにはvalueが必要です")
        if item["state"] == "absent": value=None
        result[name]={"state":item["state"],"value":value or None}
    return result


def save_ocr_annotation(target: Path,input_dir: Path,extraction_gt: Path,orientation_gt: Path,card_id: str,lines: object,contact: object) -> dict:
    card=card_by_id(extraction_cards(input_dir,extraction_gt),card_id)
    orientation=load_orientation(orientation_gt).get("cards",{}).get(card_id)
    correction=orientation.get("correction_rotation") if orientation else "unknown"
    saved={"ground_truth_card_id":card_id,"source":card["source"],"source_sha256":card["source_sha256"],"card_index":card["card_index"],"correction_rotation":correction,"lines":_validated_lines(lines),"contact":_validated_contact(contact),"annotated_at":datetime.now(timezone.utc).isoformat()}
    document=_load_document(target);document["cards"][card_id]=saved;document["updated_at"]=datetime.now(timezone.utc).isoformat();atomic_write_json(target,document);return saved


def load_pipeline_drafts(extraction_gt: Path, output_dir: Path | None) -> dict:
    """Load AI proposals without promoting them to human Ground Truth."""
    if output_dir is None or not output_dir.is_dir():
        return {}
    mapped, _problems = _artifact_map(load_extraction_ground_truth(extraction_gt), output_dir)
    drafts = {}
    for card_id, location in mapped.items():
        directory = location["directory"]
        prefix = location["prefix"]
        ocr_path = directory / f"{prefix}.ocr.ykr.json"
        contact_path = directory / f"{prefix}.contact.ykr.json"
        if not ocr_path.is_file():
            continue
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        if ocr.get("status") != "succeeded":
            continue
        lines = [
            {
                "text": line.get("text"),
                "source": line.get("source", "printed"),
                "legibility": line.get("legibility", "readable"),
            }
            for line in ocr.get("lines", [])
            if line.get("text")
        ]
        contact = {name: {"state": "absent", "value": None} for name in CONTACT_FIELDS}
        contact_status = "missing"
        if contact_path.is_file():
            contact_artifact = json.loads(contact_path.read_text(encoding="utf-8"))
            contact_status = contact_artifact.get("status", "unknown")
            if contact_status == "succeeded":
                for name in CONTACT_FIELDS:
                    field = contact_artifact.get("fields", {}).get(name, {})
                    value = field.get("display_value") or field.get("candidate_value")
                    if field.get("state") == "present" and value:
                        state = "present"
                    elif field.get("state") == "unreadable" or value:
                        state = "unreadable"
                    else:
                        state = "absent"
                    contact[name] = {"state": state, "value": value}
        drafts[card_id] = {
            "lines": lines,
            "contact": contact,
            "draft_engine": "ykr",
            "contact_status": contact_status,
        }
    return drafts


def _state(input_dir: Path,extraction_gt: Path,orientation_gt: Path,target: Path,drafts: dict | None = None) -> dict:
    ocr=_load_document(target)["cards"]; orientations=load_orientation(orientation_gt).get("cards",{}) if orientation_gt.exists() else {}
    drafts = drafts or {}
    result=[]
    for card in extraction_cards(input_dir,extraction_gt):
        card_id=card["ground_truth_card_id"]; saved=ocr.get(card_id); draft=drafts.get(card_id); proposal=saved or draft or {}; orientation=orientations.get(card_id,{}).get("correction_rotation","unknown")
        result.append({"ground_truth_card_id":card_id,"source":card["source"],"card_index":card["card_index"],"correction_rotation":orientation,"annotated":saved is not None,"draft":saved is None and draft is not None,"draft_engine":draft.get("draft_engine") if draft else None,"lines":proposal.get("lines",[]),"contact":proposal.get("contact",{})})
    return {"cards":result,"contact_fields":list(CONTACT_FIELDS)}


HTML=r"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BCMan OCR GT</title><style>body{margin:0;background:#17191d;color:#eef2f7;font-family:system-ui,sans-serif}header{position:sticky;top:0;z-index:2;background:#252930;padding:8px;display:flex;gap:8px}button,select,input{font:inherit;padding:6px}main{display:grid;grid-template-columns:minmax(0,1fr) minmax(520px,1fr);gap:12px;padding:12px}#preview{position:sticky;top:65px;align-self:start;background:#0d0f12;text-align:center}img{max-width:100%;max-height:82vh}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #444;padding:4px}input[type=text]{box-sizing:border-box;width:100%}.ok{color:#72d39b}.warn{color:#ffb454}@media(max-width:1000px){main{grid-template-columns:1fr}#preview{position:static}}</style></head><body><header><button id="prev">←</button><select id="cards"></select><button id="next">→</button><button id="save">確認して保存</button><span id="status"></span></header><main><div id="preview"><img id="image"></div><div><h2>OCR行</h2><table><thead><tr><th>文字</th><th>種別</th><th>可読性</th><th></th></tr></thead><tbody id="lines"></tbody></table><button id="add">行追加</button><h2>連絡先</h2><table><thead><tr><th>項目</th><th>状態</th><th>正解表記</th></tr></thead><tbody id="contact"></tbody></table></div></main><script>const sel=document.querySelector('#cards'),linesEl=document.querySelector('#lines'),contactEl=document.querySelector('#contact'),statusEl=document.querySelector('#status');let state={cards:[],contact_fields:[]},index=0;function status(t,k=''){statusEl.textContent=t;statusEl.className=k}function lineRow(v={text:'',source:'printed',legibility:'readable'}){const tr=document.createElement('tr');tr.innerHTML=`<td><input class="text" type="text"></td><td><select class="source"><option>printed</option><option>handwritten</option><option>mixed</option><option>unknown</option></select></td><td><select class="legibility"><option>readable</option><option>partial</option><option>unreadable</option></select></td><td><button class="del">×</button></td>`;tr.querySelector('.text').value=v.text||'';tr.querySelector('.source').value=v.source||'printed';tr.querySelector('.legibility').value=v.legibility||'readable';tr.querySelector('.del').onclick=()=>tr.remove();linesEl.appendChild(tr)}function load(i){if(!state.cards.length)return;index=(i+state.cards.length)%state.cards.length;sel.value=index;const c=state.cards[index],r=Number.isInteger(c.correction_rotation)?c.correction_rotation:0;document.querySelector('#image').src='/card/'+encodeURIComponent(c.ground_truth_card_id)+'?v='+Date.now();linesEl.innerHTML='';(c.lines.length?c.lines:[{}]).forEach(lineRow);contactEl.innerHTML='';state.contact_fields.forEach(name=>{const v=c.contact[name]||{state:'absent',value:''},tr=document.createElement('tr');tr.dataset.name=name;tr.innerHTML=`<td>${name}</td><td><select class="state"><option>absent</option><option>present</option><option>unreadable</option></select></td><td><input class="value" type="text"></td>`;tr.querySelector('.state').value=v.state;tr.querySelector('.value').value=v.value||'';contactEl.appendChild(tr)});status(c.annotated?'保存済み':c.draft?'AI下書き（要確認）':'下書き未生成',c.annotated?'ok':'warn')}document.querySelector('#add').onclick=()=>lineRow();document.querySelector('#prev').onclick=()=>load(index-1);document.querySelector('#next').onclick=()=>load(index+1);sel.onchange=()=>load(Number(sel.value));document.querySelector('#save').onclick=async()=>{const c=state.cards[index],lines=[...linesEl.children].map(tr=>({text:tr.querySelector('.text').value||null,source:tr.querySelector('.source').value,legibility:tr.querySelector('.legibility').value})),contact=Object.fromEntries([...contactEl.children].map(tr=>[tr.dataset.name,{state:tr.querySelector('.state').value,value:tr.querySelector('.value').value||null}]));const r=await fetch('/api/ocr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ground_truth_card_id:c.ground_truth_card_id,lines,contact})}),body=await r.json();if(!r.ok){status(body.error||'保存失敗','warn');return}c.lines=body.lines;c.contact=body.contact;c.annotated=true;c.draft=false;status('保存済み','ok')};document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();document.querySelector('#save').click()}});fetch('/api/state').then(r=>r.json()).then(s=>{state=s;sel.innerHTML=s.cards.map((c,i)=>`<option value="${i}">${c.annotated?'✓ ':c.draft?'AI ':''}${c.source} #${c.card_index}</option>`).join('');load(0)}).catch(e=>status(String(e),'warn'));</script></body></html>"""


def _handler(input_dir:Path,extraction_gt:Path,orientation_gt:Path,target:Path,drafts:dict|None=None):
    class Handler(BaseHTTPRequestHandler):
        def send_value(self,status:int,body:bytes,content_type:str)->None:self.send_response(status);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
        def send_json(self,status:int,value:object)->None:self.send_value(status,json.dumps(value,ensure_ascii=False).encode(),"application/json; charset=utf-8")
        def do_GET(self)->None:
            parsed=urlsplit(self.path)
            try:
                if parsed.path=="/":return self.send_value(200,HTML.encode(),"text/html; charset=utf-8")
                if parsed.path=="/api/state":return self.send_json(200,_state(input_dir,extraction_gt,orientation_gt,target,drafts))
                if parsed.path.startswith("/card/"):
                    card_id=unquote(parsed.path[6:]);card=card_by_id(extraction_cards(input_dir,extraction_gt),card_id);orientation=load_orientation(orientation_gt).get("cards",{}).get(card_id,{}) if orientation_gt.exists() else {};rotation=orientation.get("correction_rotation",0);rotation=rotation if isinstance(rotation,int) else 0;return self.send_value(200,encoded_png(card,rotation),"image/png")
                self.send_json(404,{"error":"not found"})
            except Exception as exc:self.send_json(400,{"error":str(exc)})
        def do_POST(self)->None:
            if urlsplit(self.path).path!="/api/ocr":return self.send_json(404,{"error":"not found"})
            try:
                length=int(self.headers.get("Content-Length","0"));payload=json.loads(self.rfile.read(length));saved=save_ocr_annotation(target,input_dir,extraction_gt,orientation_gt,payload.get("ground_truth_card_id",""),payload.get("lines"),payload.get("contact"));self.send_json(200,saved)
            except Exception as exc:self.send_json(400,{"error":str(exc)})
        def log_message(self,format:str,*args:object)->None:return
    return Handler


def main()->int:
    parser=argparse.ArgumentParser(description="名刺ごとのOCR・連絡先Ground Truthを作成");parser.add_argument("--input-dir",type=Path,default=DEFAULT_INPUT_DIR);parser.add_argument("--extraction-ground-truth",type=Path,default=DEFAULT_EXTRACTION_GT);parser.add_argument("--orientation-ground-truth",type=Path,default=DEFAULT_ORIENTATION_GT);parser.add_argument("--target",type=Path,default=DEFAULT_TARGET);parser.add_argument("--draft-output-dir",type=Path,help="full pipeline成果物をAI下書きとして読み込む");parser.add_argument("--port",type=int,default=8767);parser.add_argument("--open-browser",action="store_true");parser.add_argument("--dataset-role",choices=("development","holdout"),default="development");args=parser.parse_args();cards=extraction_cards(args.input_dir.resolve(),args.extraction_ground_truth.resolve())
    if not cards:parser.error("四隅Ground Truthのカードがありません")
    extraction_role = load_extraction_ground_truth(args.extraction_ground_truth.resolve()).get("dataset_role"); orientation_role=load_orientation(args.orientation_ground_truth.resolve()).get("dataset_role") if args.orientation_ground_truth.resolve().exists() else None
    if extraction_role != args.dataset_role: parser.error(f"Extraction GTはdataset_role={extraction_role}です")
    if orientation_role not in {None,args.dataset_role}: parser.error(f"Orientation GTはdataset_role={orientation_role}です")
    initialize_dataset_role(args.target.resolve(),args.dataset_role);drafts=load_pipeline_drafts(args.extraction_ground_truth.resolve(),args.draft_output_dir.resolve() if args.draft_output_dir else None);server=ThreadingHTTPServer(("127.0.0.1",args.port),_handler(args.input_dir.resolve(),args.extraction_ground_truth.resolve(),args.orientation_ground_truth.resolve(),args.target.resolve(),drafts));url=f"http://127.0.0.1:{args.port}/";print(f"OCR Ground Truth editor: {url}");print(f"AI drafts: {len(drafts)}");print("終了: Ctrl+C")
    if args.open_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:print("\n終了しました")
    finally:server.server_close()
    return 0


if __name__=="__main__":raise SystemExit(main())
