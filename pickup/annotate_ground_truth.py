from __future__ import annotations

import argparse
import hashlib
import json
import os
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import cv2
import numpy as np

from bcpickup import DEFAULT_INPUT_DIR, _source_images
from detector import ordered_corners, read_image


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = BASE_DIR / "ground_truth.json"
SCHEMA_VERSION = 2
ANNOTATION_METHOD = "manual-four-corner"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _new_document() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "dataset_role": "development",
        "images": {},
    }


def _load_document(path: Path) -> dict:
    if not path.exists():
        return _new_document()
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("annotation_method") != ANNOTATION_METHOD
        or not isinstance(document.get("images"), dict)
    ):
        raise ValueError(
            "旧形式または不正なGround Truthです。検出結果由来のデータは"
            "人手アノテーションとして読み込めません"
        )
    return document


def _validated_cards(cards: object, width: int, height: int) -> list[dict]:
    if not isinstance(cards, list) or not cards:
        raise ValueError("名刺を1枚以上登録してください")
    validated = []
    for index, raw in enumerate(cards, 1):
        try:
            points = np.float32(raw).reshape(4, 2)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"名刺{index}の4隅が不正です") from exc
        if not np.isfinite(points).all():
            raise ValueError(f"名刺{index}の座標が有限値ではありません")
        if (
            np.any(points[:, 0] < 0)
            or np.any(points[:, 0] >= width)
            or np.any(points[:, 1] < 0)
            or np.any(points[:, 1] >= height)
        ):
            raise ValueError(f"名刺{index}の座標が画像外です")
        points = ordered_corners(points)
        if abs(float(cv2.contourArea(points))) < 100:
            raise ValueError(f"名刺{index}の領域が小さすぎます")
        if not cv2.isContourConvex(points):
            raise ValueError(f"名刺{index}の4隅が交差しています")
        validated.append(
            {
                "corners": [
                    [round(float(x), 2), round(float(y), 2)]
                    for x, y in points
                ]
            }
        )
    return validated


def save_annotation(
    target: Path,
    input_dir: Path,
    source_name: str,
    cards: object,
) -> dict:
    sources = {path.name: path for path in _source_images(input_dir)}
    if source_name not in sources:
        raise ValueError("picture直下の対象画像ではありません")
    source = sources[source_name]
    image = read_image(source)
    height, width = image.shape[:2]
    validated = _validated_cards(cards, width, height)
    document = _load_document(target)
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    document["images"][source.name] = {
        "source_sha256": _sha256(source),
        "source_size": {"width": width, "height": height},
        "annotation_method": ANNOTATION_METHOD,
        "annotated_at": datetime.now(timezone.utc).isoformat(),
        "cards": validated,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return document["images"][source.name]


def _state(input_dir: Path, target: Path) -> dict:
    document = _load_document(target)
    images = []
    for source in _source_images(input_dir):
        image = read_image(source)
        height, width = image.shape[:2]
        annotation = document["images"].get(source.name)
        current_hash = _sha256(source)
        stale = bool(
            annotation and annotation.get("source_sha256") != current_hash
        )
        images.append(
            {
                "name": source.name,
                "width": width,
                "height": height,
                "annotated": bool(annotation) and not stale,
                "stale": stale,
                "cards": (
                    [
                        card["corners"]
                        for card in annotation.get("cards", [])
                    ]
                    if annotation and not stale
                    else []
                ),
            }
        )
    return {"images": images}


HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BCMan Ground Truth</title>
<style>
body{margin:0;background:#17191d;color:#f1f3f5;font-family:system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:#252930;padding:10px 16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,select{font:inherit;padding:7px 11px}
button.primary{background:#3b82f6;color:white;border:0;border-radius:4px}
#status{margin-left:auto;color:#b8c0cc}
main{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:14px;padding:14px}
#stage{min-width:0;text-align:center;background:#0d0f12;padding:8px}
canvas{display:block;max-width:100%;max-height:calc(100vh - 100px);margin:auto;cursor:crosshair}
aside{line-height:1.55}
.warn{color:#ffb454}.ok{color:#72d39b}kbd{background:#333;padding:2px 5px;border-radius:3px}
@media(max-width:800px){main{grid-template-columns:1fr}canvas{max-height:70vh}}
</style>
</head>
<body>
<header>
  <button id="prev">← 前</button><select id="files"></select><button id="next">次 →</button>
  <button id="undo">1点戻す</button><button id="remove">最後の名刺を削除</button>
  <button id="clear">全消去</button><button class="primary" id="save">保存</button>
  <span id="status">読込中</span>
</header>
<main>
  <div id="stage"><canvas id="canvas"></canvas></div>
  <aside>
    <h3>人手Ground Truth</h3>
    <p>各名刺について、見た目の左上から時計回りに
    <strong>左上 → 右上 → 右下 → 左下</strong>の4隅をクリックします。</p>
    <p>4点で1枚が確定します。画面内に4隅がある名刺をすべて登録し、
    枚数を確認して保存してください。</p>
    <p>正解入力の枚数に上限はありません。自動検出の上限12枚を超える写真でも、
    人が確認できた名刺をすべて登録できます。</p>
    <p>検出結果は意図的に表示しません。正解が検出器に引っ張られるのを防ぐためです。</p>
    <p id="count"></p>
    <p><kbd>Ctrl+Z</kbd>: 1点戻す</p>
  </aside>
</main>
<script>
const canvas=document.querySelector("#canvas"),ctx=canvas.getContext("2d");
const files=document.querySelector("#files"),statusEl=document.querySelector("#status"),countEl=document.querySelector("#count");
let state={images:[]},index=0,image=new Image(),cards=[],current=[];
const colors=["#00ff7b","#00d9ff","#ffdf33","#ff6b9a","#b28dff","#ff9433","#8fff33","#ef5350","#26c6da","#ffee58"];
function setStatus(text,kind=""){statusEl.textContent=text;statusEl.className=kind}
function redraw(){
  if(!image.complete||!image.naturalWidth)return;
  ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);
  const width=Math.max(4,Math.max(canvas.width,canvas.height)/700);
  [...cards,current].forEach((points,i)=>{
    if(!points.length)return;ctx.strokeStyle=colors[i%colors.length];ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=width;
    ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);points.slice(1).forEach(p=>ctx.lineTo(p[0],p[1]));
    if(points.length===4)ctx.closePath();ctx.stroke();
    points.forEach((p,j)=>{ctx.beginPath();ctx.arc(p[0],p[1],width*2.2,0,Math.PI*2);ctx.fill();
      ctx.font=(width*5)+"px sans-serif";ctx.fillText(String(j+1),p[0]+width*2,p[1]-width*2)});
  });
  countEl.textContent="確定 "+cards.length+"枚 / 入力中 "+current.length+"点";
}
function load(i){
  if(!state.images.length)return;index=(i+state.images.length)%state.images.length;
  const item=state.images[index];files.value=String(index);cards=JSON.parse(JSON.stringify(item.cards||[]));current=[];
  setStatus(item.stale?"原画像変更あり・再登録が必要":item.annotated?"登録済み":"未登録",item.annotated?"ok":"warn");
  image.onload=()=>{canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;redraw()};
  image.src="/image/"+encodeURIComponent(item.name)+"?v="+Date.now();
}
canvas.addEventListener("click",event=>{
  const rect=canvas.getBoundingClientRect();
  current.push([(event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height]);
  if(current.length===4){cards.push(current);current=[]}redraw();setStatus("未保存","warn");
});
document.querySelector("#undo").onclick=()=>{if(current.length)current.pop();else if(cards.length)current=cards.pop();redraw();setStatus("未保存","warn")};
document.querySelector("#remove").onclick=()=>{current=[];cards.pop();redraw();setStatus("未保存","warn")};
document.querySelector("#clear").onclick=()=>{if(confirm("この画像の入力をすべて消去しますか？")){cards=[];current=[];redraw();setStatus("未保存","warn")}};
document.querySelector("#prev").onclick=()=>load(index-1);document.querySelector("#next").onclick=()=>load(index+1);
files.onchange=()=>load(Number(files.value));
document.querySelector("#save").onclick=async()=>{
  if(current.length){alert("入力途中の点があります。4隅を完成するか戻してください");return}
  if(cards.length<1){alert("名刺を1枚以上登録してください");return}
  setStatus("保存中");
  const response=await fetch("/api/annotation",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({source:state.images[index].name,cards})});
  const body=await response.json();if(!response.ok){setStatus(body.error||"保存失敗","warn");return}
  state.images[index].cards=body.cards.map(card=>card.corners);state.images[index].annotated=true;state.images[index].stale=false;
  cards=JSON.parse(JSON.stringify(state.images[index].cards));redraw();setStatus("保存済み","ok")
};
document.addEventListener("keydown",event=>{if(event.ctrlKey&&event.key.toLowerCase()==="z"){event.preventDefault();document.querySelector("#undo").click()}});
fetch("/api/state").then(r=>r.json()).then(data=>{state=data;files.innerHTML=state.images.map((item,i)=>`<option value="${i}">${item.annotated?"✓ ":""}${item.name}</option>`).join("");load(0)}).catch(error=>setStatus(String(error),"warn"));
</script>
</body>
</html>"""


def _handler(input_dir: Path, target: Path):
    sources = {path.name: path for path in _source_images(input_dir)}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, value: object) -> None:
            self._send(
                status,
                json.dumps(value, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                try:
                    self._send_json(200, _state(input_dir, target))
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                return
            if parsed.path.startswith("/image/"):
                name = unquote(parsed.path[len("/image/"):])
                source = sources.get(name)
                if source is None:
                    self._send_json(404, {"error": "画像がありません"})
                    return
                mime = "image/png" if source.suffix.lower() == ".png" else "image/jpeg"
                self._send(200, source.read_bytes(), mime)
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/annotation":
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1024 * 1024:
                    raise ValueError("リクエストサイズが不正です")
                payload = json.loads(self.rfile.read(length))
                saved = save_annotation(
                    target, input_dir, payload.get("source", ""), payload.get("cards")
                )
                self._send_json(200, saved)
            except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="原画像へ4隅をクリックして独立Ground Truthを作成"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    input_dir = args.input_dir.resolve()
    target = args.target.resolve()
    if not _source_images(input_dir):
        parser.error(f"対象画像がありません: {input_dir}")
    _load_document(target)
    address = ("127.0.0.1", args.port)
    server = ThreadingHTTPServer(address, _handler(input_dir, target))
    url = f"http://{address[0]}:{address[1]}/"
    print(f"Ground Truth editor: {url}")
    print("終了: Ctrl+C")
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
