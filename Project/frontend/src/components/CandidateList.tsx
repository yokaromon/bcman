import { useState } from 'react';
import { cardStatusLabel, cardThumbnailUrl, confirmCards, isCardReady, type CardSummary } from '../api';

type Props = { photoId: string; cards: CardSummary[]; onOpen: (index: number) => void; onUpdated: () => void; onBack: () => void };

/** まとめて撮った名刺の状態確認と一括登録専用の一覧。 */
export function CandidateList({ photoId, cards, onOpen, onUpdated, onBack }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const ready = cards.filter((card) => card.status === 'review_required');
  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next;
  });
  const confirm = async () => {
    setBusy(true);
    try { await confirmCards(photoId, [...selected]); setSelected(new Set()); onUpdated(); } finally { setBusy(false); }
  };
  return <div className="screen">
    <button type="button" className="back-link" onClick={onBack}>← 個別確認へ</button>
    <h2 className="screen__title">登録候補</h2>
    <p className="progress-note">{cards.filter((card) => isCardReady(card.status)).length} / {cards.length} 枚を認識済み</p>
    <ul className="candidate-list">{cards.map((card, index) => <li key={card.id} className="candidate">
      <input aria-label={`名刺 ${index + 1} を選択`} type="checkbox" disabled={card.status !== 'review_required'} checked={selected.has(card.id)} onChange={() => toggle(card.id)} />
      <button type="button" className="candidate__body" onClick={() => onOpen(index)}>
        <img src={cardThumbnailUrl(card.id)} alt={`名刺 ${index + 1}`} />
        <span>名刺 {index + 1}<small>{cardStatusLabel(card.status)}</small></span>
      </button>
    </li>)}</ul>
    <button type="button" className="button button--primary" disabled={!selected.size || busy || !ready.length} onClick={() => void confirm()}>
      {busy ? '登録しています…' : `選択した ${selected.size} 枚を登録`}
    </button>
  </div>;
}
