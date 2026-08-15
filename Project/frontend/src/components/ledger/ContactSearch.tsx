import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cardThumbnailUrl,
  LEDGER_SEARCH_DEBOUNCE_MS,
  ledgerEntryToCard,
  searchContacts,
  type LedgerEntry,
} from '../../api';
import { CardPager } from '../CardPager';

function formatDate(value: string | null): string {
  if (!value) return '日付なし';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

function describeRole(entry: LedgerEntry): string {
  return [entry.department, entry.position].filter(Boolean).join(' / ');
}

/** 登録済み名刺の台帳。検索語が空のときは全件を交換日の新しい順に出す。 */
export function ContactSearch() {
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [openIndex, setOpenIndex] = useState(-1);
  const [dirty, setDirty] = useState(false);
  const [leaveBlocked, setLeaveBlocked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  // 遅れて届いた古い検索の応答で新しい結果を上書きしないための世代番号
  const requestId = useRef(0);

  const load = useCallback(async (text: string, offset: number) => {
    const generation = ++requestId.current;
    setLoading(true);
    setErrorMessage('');
    try {
      const page = await searchContacts(text, offset);
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

  useEffect(() => {
    const timer = setTimeout(() => void load(query, 0), LEDGER_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, load]);

  // 開いている間に一覧を取り直すと、件数や並び順が変わって開いている位置がずれる。
  // 変わったことだけ覚えておき、一覧へ戻るときにまとめて読み直す。
  const staleRef = useRef(false);

  const closeDetail = () => {
    setOpenIndex(-1);
    if (staleRef.current) {
      staleRef.current = false;
      void load(query, 0);
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
          mode="edit"
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
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {!errorMessage && (
        <p className="hint">
          {total === 0 ? '該当する名刺がありません。' : `${total}件中 ${entries.length}件を表示`}
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
                <strong>{entry.person_name ?? '（氏名未入力）'}</strong>
                <span>{entry.company_name ?? '（会社名未入力）'}</span>
                {describeRole(entry) && <span className="ledger-row__role">{describeRole(entry)}</span>}
                <span className="ledger-row__meta">
                  {formatDate(entry.exchanged_at)} ・ 登録者: {entry.card_owner?.name ?? '未設定'}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      {loading && <p className="hint">読み込んでいます…</p>}
      {hasMore && !loading && (
        <button type="button" className="button button--ghost" onClick={() => void load(query, entries.length)}>
          もっと見る（残り {total - entries.length}件）
        </button>
      )}
    </div>
  );
}
