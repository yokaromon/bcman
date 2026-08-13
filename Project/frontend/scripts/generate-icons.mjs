// PWAアイコン(SVG/PNG)とmanifest.jsonをpublic/へ生成する。
// 外部の画像ライブラリを使わず、Node標準のzlibだけでPNGを組み立てる
// (GeoShare側のPython実装と同じ方針)。デザインを変えたら再実行する。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { deflateSync } from 'node:zlib';

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');
const BASE_PATH = '/bcman';

const BG = [0x17, 0x69, 0xc2]; // #1769c2 (index.htmlのtheme-colorと同じ)
const WHITE = [255, 255, 255];
const INK = [0x17, 0x69, 0xc2];
const SOFT = [0x8f, 0xb8, 0xe3];

function inRoundedRect(x, y, rx, ry, w, h, r) {
  const x0 = rx, y0 = ry, x1 = rx + w, y1 = ry + h;
  if (x < x0 || x >= x1 || y < y0 || y >= y1) return false;
  const inCornerX = x < x0 + r || x >= x1 - r;
  const inCornerY = y < y0 + r || y >= y1 - r;
  if (inCornerX && inCornerY) {
    const cx = x < x0 + r ? x0 + r : x1 - r;
    const cy = y < y0 + r ? y0 + r : y1 - r;
    const dx = x - cx, dy = y - cy;
    return dx * dx + dy * dy <= r * r;
  }
  return true;
}

// 名刺(白いカード) + 似顔絵の丸 + テキスト行2本、というモチーフ。
function pixelAt(x, y, size) {
  const s = size / 192;
  const card = [28 * s, 54 * s, 136 * s, 84 * s, 10 * s];
  const avatar = [62 * s, 88 * s, 16 * s];
  const bar1 = [92 * s, 76 * s, 56 * s, 8 * s, 4 * s];
  const bar2 = [92 * s, 96 * s, 40 * s, 6 * s, 3 * s];

  if (!inRoundedRect(x, y, ...card)) return BG;

  const dx = x - avatar[0], dy = y - avatar[1];
  if (dx * dx + dy * dy <= avatar[2] * avatar[2]) return INK;
  if (inRoundedRect(x, y, ...bar1)) return INK;
  if (inRoundedRect(x, y, ...bar2)) return SOFT;
  return WHITE;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(tag, data) {
  const tagBuf = Buffer.from(tag, 'ascii');
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([tagBuf, data])));
  return Buffer.concat([len, tagBuf, data, crc]);
}

function makeIconPng(size) {
  const rows = [];
  for (let y = 0; y < size; y++) {
    const row = [0];
    for (let x = 0; x < size; x++) {
      row.push(...pixelAt(x, y, size));
    }
    rows.push(Buffer.from(row));
  }
  const raw = Buffer.concat(rows);
  const compressed = deflateSync(raw, { level: 6 });

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr.writeUInt8(8, 8); // bit depth
  ihdr.writeUInt8(2, 9); // color type: truecolor (アルファ不要のためGeoShareと同じ選択)

  return Buffer.concat([
    Buffer.from('\x89PNG\r\n\x1a\n', 'binary'),
    chunk('IHDR', ihdr),
    chunk('IDAT', compressed),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function buildIconSvg() {
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">' +
    '<rect width="192" height="192" fill="#1769c2"/>' +
    '<rect x="28" y="54" width="136" height="84" rx="10" fill="white"/>' +
    '<circle cx="62" cy="88" r="16" fill="#1769c2"/>' +
    '<rect x="92" y="76" width="56" height="8" rx="4" fill="#1769c2"/>' +
    '<rect x="92" y="96" width="40" height="6" rx="3" fill="#8fb8e3"/>' +
    '</svg>'
  );
}

function buildManifestJson() {
  const manifest = {
    name: 'BCMan 名刺管理',
    short_name: 'BCMan',
    description: '名刺OCR・連絡先管理',
    start_url: `${BASE_PATH}/`,
    scope: `${BASE_PATH}/`,
    display: 'standalone',
    background_color: '#f5f5f5',
    theme_color: '#1769c2',
    orientation: 'any',
    lang: 'ja',
    icons: [
      { src: `${BASE_PATH}/icon.svg`, sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
      { src: `${BASE_PATH}/icon-192.png`, sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
      { src: `${BASE_PATH}/icon-512.png`, sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
    ],
  };
  return JSON.stringify(manifest, null, 2) + '\n';
}

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(join(OUT_DIR, 'icon.svg'), buildIconSvg());
writeFileSync(join(OUT_DIR, 'icon-192.png'), makeIconPng(192));
writeFileSync(join(OUT_DIR, 'icon-512.png'), makeIconPng(512));
writeFileSync(join(OUT_DIR, 'manifest.json'), buildManifestJson());

console.log(`generated icon.svg / icon-192.png / icon-512.png / manifest.json into ${OUT_DIR}`);
