import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cardThumbnailUrl,
  LEDGER_SEARCH_DEBOUNCE_MS,
  ledgerEntryToCard,
  searchContacts,
  type LedgerEntry,
  type LedgerStatus,
} from '../../api';
import { CardPager } from '../CardPager';

const STATUS_TABS: { value: LedgerStatus; label: string }[] = [
  { value: 'all', label: 'すべて' },
  { value: 'confirmed', label: '確認済み' },
  { value: 'unconfirmed', label: '未確認' },
];

function formatDate(value: string | null): string {
  if (!value) return '日付なし';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

function describeRole(entry: LedgerEntry): string {
  return [entry.department, entry.position].filter(Boolean).join(' / ');
}

/**
 * 撮影済み名刺の台帳。未確認も既定で出す。隠すと「登録したはずなのに出てこない」と
 * 受け取られ、確認の押し忘れに気づけない（2026-08-19、現場で頻発していた誤解）。
 */
export function ContactSearch() {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<LedgerStatus>('all');
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [unconfirmedTotal, setUnconfirmedTotal] = useState(0);
  const [openIndex, setOpenIndex] = useState(-1);
  const [dirty, setDirty] = useState(false);
  const [leaveBlocked, setLeaveBlocked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  // 遅れて届いた古い検索の応答で新しい結果を上書きしないための世代番号
  const requestId = useRef(0);

  const load = useCallback(async (text: string, offset: number, scope: LedgerStatus) => {
    const generation = ++requestId.current;
    setLoading(true);
    setErrorMessage('');
    try {
      const page = await searchContacts(text, offset, undefined, scope);
      if (generation !== requestId.current) {
        return;
      }
      setTotal(page.total);
      setEntries((current) => (offset === 0 ? page.items : [...current, ...page.items]));
    } catch (error) {
      if (generation !== requestId.current) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : '名刺を検索できませんでした');
    } finally {
      if (generation === requestId.current) {
        setLoading(false);
      }
    }
  }, []);

  // 未確認の総数は検索語に関係なく出す。溜まっていること自体に気づかせるための数字
  const loadUnconfirmedTotal = useCallback(async () => {
    try {
      setUnconfirmedTotal((await searchContacts('', 0, 1, 'unconfirmed')).total);
    } catch {
      // 件数バッジは補助情報。取れなくても一覧の邪魔をしない
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(query, 0, status), LEDGER_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, status, load]);

  useEffect(() => {
    void loadUnconfirmedTotal();
  }, [loadUnconfirmedTotal]);

  // 開いている間に一覧を取り直すと、件数や並び順が変わって開いている位置がずれる。
  // 変わったことだけ覚えておき、一覧へ戻るときにまとめて読み直す。
  const staleRef = useRef(false);

  const closeDetail = () => {
    setOpenIndex(-1);
    // 詳細を閉じると CardReviewBody は消えるので、未保存フラグを下ろす相手がいない。
    // 残したままだと次に開いた直後の「戻る」が誤って止められる。
    setDirty(false);
    if (staleRef.current) {
      staleRef.current = false;
      void load(query, 0, status);
      void loadUnconfirmedTotal();
    }
  };

  if (openIndex >= 0 && entries[openIndex]) {
    const leave = () => {
      if (dirty) {
        setLeaveBlocked(true);
        return;
      }
      closeDetail();
    };

    return (
      <div className="screen">
        <button type="button" className="back-link" onClick={leave}>
          ← 検索結果へ
        </button>
        {leaveBlocked && (
          <div className="alert alert--warn">
            <p>未保存の変更があります。先に「保存」を押すか、変更を破棄してください。</p>
            <div className="action-bar">
              <button
                type="button"
                className="button button--ghost"
                onClick={() => {
                  setLeaveBlocked(false);
                  setDirty(false);
                  closeDetail();
                }}
              >
                破棄して戻る
              </button>
              <button type="button" className="button button--ghost" onClick={() => setLeaveBlocked(false)}>
                編集を続ける
              </button>
            </div>
          </div>
        )}
        <CardPager
          cards={entries.map(ledgerEntryToCard)}
          index={openIndex}
          failedCardIds={new Set()}
          confirmLabel="保存"
          mode="auto"
          onIndexChange={setOpenIndex}
          onConfirmed={() => { staleRef.current = true; }}
          onUpdated={() => { staleRef.current = true; }}
          onDirtyChange={setDirty}
        />
      </div>
    );
  }

  const hasMore = entries.length < total;

  return (
    <div className="screen">
      <input
        className="field__input"
        type="search"
        value={query}
        placeholder="会社名・氏名・電話番号などで検索"
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="action-bar">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            className={status === tab.value ? 'button button--primary' : 'button button--ghost'}
            onClick={() => setStatus(tab.value)}
          >
            {tab.label}
            {tab.value === 'unconfirmed' && unconfirmedTotal > 0 && ` (${unconfirmedTotal})`}
          </button>
        ))}
      </div>

      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {!errorMessage && (
        <p className="hint">
          {total === 0 ? '該当する名刺がありません。' : `${total}件中 ${entries.length}件を表示`}
        </p>
      )}
      {!errorMessage && status !== 'unconfirmed' && unconfirmedTotal > 0 && (
        <p className="hint">
          未確認の名刺が{unconfirmedTotal}件あります。登録するまで名鑑には載りません。
        </p>
      )}

      <ul className="ledger-list">
        {entries.map((entry, index) => (
          <li key={entry.contact_id}>
            <button type="button" className="ledger-row" onClick={() => setOpenIndex(index)}>
              <img
                className="ledger-row__thumb"
                src={cardThumbnailUrl(entry.card_id, entry.image_revision)}
                alt=""
                loading="lazy"
              />
              <span className="ledger-row__body">
                <strong>
                  {entry.person_name ?? '（氏名未入力）'}
                  {!entry.confirmed && <span className="ledger-row__badge">未確認</span>}
                </strong>
                <span>{entry.company_name ?? '（会社名未入力）'}</span>
                {describeRole(entry) && <span className="ledger-row__role">{describeRole(entry)}</span>}
                <span className="ledger-row__meta">
                  {entry.confirmed
                    ? `${formatDate(entry.exchanged_at)} ・ 登録者: ${entry.card_owner?.name ?? '未設定'}`
                    : 'まだ登録されていません（開いて内容を確認してください）'}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      {loading && <p className="hint">読み込んでいます…</p>}
      {hasMore && !loading && (
        <button type="button" className="button button--ghost" onClick={() => void load(query, entries.length, status)}>
          もっと見る（残り {total - entries.length}件）
        </button>
      )}
    </div>
  );
}
