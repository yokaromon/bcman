/**
 * logger.ts — フロントエンド向けログモジュール（コア）
 *
 * 依存: ブラウザ標準 API のみ（fetch, sendBeacon, sessionStorage, crypto）
 * 他プロジェクトへの移植: このファイル単体をコピーして init() を呼ぶだけ
 */

interface LogRecord {
  timestamp: string;
  source: "frontend";
  client_id: string;
  seq_no: number;
  from_node: string | null;
  to_node: string | null;
  source_file: string;
  line_no: number;
  message: string;
}

export interface LoggerConfig {
  /** バックエンドの受信エンドポイント */
  endpoint: string;
  /** バッファのフラッシュ間隔 (ms) */
  flushInterval: number;
}

// --------------------------------------------------------- internal state ---

const SESSION_KEY = "__log_client_id";
const DEFAULT_CONFIG: LoggerConfig = {
  endpoint: "/api/log",
  flushInterval: 200,
};

// 送信失敗時はバッファに戻して再送する。上限に達して初めて諦め、欠損マーカーを残す。
const MAX_RETRY = 5;
const MAX_BUFFER = 1000;
const MAX_RETRY_DELAY = 5000;

let _config = { ...DEFAULT_CONFIG };
let _clientId = "";
let _seqNo = 0;
let _buffer: LogRecord[] = [];
let _timer: ReturnType<typeof setTimeout> | null = null;
let _retryCount = 0;
let _initialized = false;

// ------------------------------------------------------------------ public ---

/** アプリ起動時に一度だけ呼ぶ */
export function init(config: Partial<LoggerConfig> = {}): void {
  _config = { ...DEFAULT_CONFIG, ...config };
  _clientId = _getOrCreateClientId();
  _initialized = true;

  // ページ離脱時にバッファを同期送信（sendBeacon はページクローズ後も送信される）
  window.addEventListener("beforeunload", _flushSync);
}

/**
 * ログを1件記録する。呼び出し元のファイル名・行番号は自動取得する。
 *
 * log("メッセージ")
 * log("メッセージ", "FromNode", "ToNode")
 *
 * ※ 開発時（Vite dev server）は元ソースの行番号が取れる。
 *    本番ビルドではバンドル後の行番号になる（ベストエフォート）。
 */
export function log(
  message: string,
  from_node: string | null = null,
  to_node: string | null = null,
): void {
  if (!_initialized) {
    console.warn("[logger] not initialized. Call init() first.");
    return;
  }

  const { source_file, line_no } = _getCallerLocation();

  const record: LogRecord = {
    timestamp: new Date().toISOString(),
    source: "frontend",
    client_id: _clientId,
    seq_no: ++_seqNo,
    from_node,
    to_node,
    source_file,
    line_no,
    message,
  };

  _buffer.push(record);
  _scheduledFlush();
}

// ----------------------------------------------------------------- private ---

function _getOrCreateClientId(): string {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

/**
 * Error().stack から呼び出し元のファイル名と行番号を取得する。
 *
 * スタックの構造（V8/Chrome）:
 *   Error
 *     at _getCallerLocation (logger.ts:X)   ← [1]
 *     at log (logger.ts:Y)                  ← [2]
 *     at 呼び出し元 (SomePage.tsx:Z:C)      ← [3] ← ここが欲しい
 */
function _getCallerLocation(): { source_file: string; line_no: number } {
  const lines = (new Error().stack ?? "").split("\n");
  const callerLine = lines[3] ?? "";

  // "    at FuncName (path/to/file.tsx:42:10)"
  const withName = callerLine.match(/\((.+):(\d+):\d+\)/);
  if (withName) {
    return {
      source_file: withName[1].split("/").pop()?.split("?")[0] ?? "",
      line_no: Number(withName[2]),
    };
  }

  // "    at path/to/file.tsx:42:10"  （無名関数の場合）
  const withoutName = callerLine.match(/at (.+):(\d+):\d+/);
  if (withoutName) {
    return {
      source_file: withoutName[1].split("/").pop()?.split("?")[0] ?? "",
      line_no: Number(withoutName[2]),
    };
  }

  return { source_file: "", line_no: 0 };
}

function _scheduledFlush(): void {
  if (_timer !== null) clearTimeout(_timer);
  _timer = setTimeout(_flushAsync, _config.flushInterval);
}

async function _flushAsync(): Promise<void> {
  if (_buffer.length === 0) return;

  const toSend = _buffer.splice(0);

  try {
    const res = await fetch(_config.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toSend),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _retryCount = 0; // 成功したらリトライ回数をリセット
  } catch {
    // 送信失敗: 捨てずにバッファ先頭へ戻し、backend 復帰後に再送する(順序は維持)。
    _buffer.unshift(...toSend);
    _retryCount += 1;

    // リトライ上限に達したら最古のバッチだけ諦め、欠損マーカーを残す(無限滞留を防ぐ)。
    if (_retryCount >= MAX_RETRY) {
      const dropped = _buffer.splice(0, toSend.length);
      if (dropped.length > 0) {
        const first = dropped[0].seq_no;
        const last = dropped[dropped.length - 1].seq_no;
        _buffer.unshift({
          timestamp: new Date().toISOString(),
          source: "frontend",
          client_id: _clientId,
          seq_no: ++_seqNo,
          from_node: null,
          to_node: null,
          source_file: "logger.ts",
          line_no: 0,
          message: `[SEND_FAILED] seq_no=${first}~${last} (${dropped.length} records lost after ${MAX_RETRY} retries)`,
        });
      }
      _retryCount = 0;
    }

    // バッファが無限に膨らまないよう、上限超過分は古いものから切り捨てる。
    if (_buffer.length > MAX_BUFFER) {
      _buffer.splice(0, _buffer.length - MAX_BUFFER);
    }

    // 指数バックオフで再送をスケジュールする(新しい log() が来なくても再送する)。
    _scheduleRetry();
  }
}

// 送信失敗時、backend 復帰を待って再送するためのバックオフ付きタイマー。
function _scheduleRetry(): void {
  if (_timer !== null) clearTimeout(_timer);
  const delay = Math.min(_config.flushInterval * 2 ** _retryCount, MAX_RETRY_DELAY);
  _timer = setTimeout(_flushAsync, delay);
}

/** ページ離脱時の同期フラッシュ（sendBeacon 使用） */
function _flushSync(): void {
  if (_buffer.length === 0) return;
  const payload = JSON.stringify(_buffer.splice(0));
  navigator.sendBeacon(_config.endpoint, new Blob([payload], { type: "application/json" }));
}
