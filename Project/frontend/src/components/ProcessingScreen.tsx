import { cardStatusLabel, isCardReady, type CardSummary } from '../api';

type Props = {
  cards: CardSummary[];
  failedCardIds: Set<string>;
  retryingCardIds: Set<string>;
  fatalMessage: string;
  onRestart: () => void;
};

export function ProcessingScreen({ cards, failedCardIds, retryingCardIds, fatalMessage, onRestart }: Props) {
  if (fatalMessage) {
    return (
      <div className="screen screen--center">
        <p className="alert alert--error">{fatalMessage}</p>
        <button type="button" className="button button--primary button--xl" onClick={onRestart}>
          撮り直す
        </button>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="screen screen--center">
        <div className="spinner" />
        <p className="lead">名刺を探しています…</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2 className="screen__title">{cards.length}枚の名刺を読み取り中</h2>
      <ul className="status-list">
        {cards.map((card, index) => (
          <li key={card.id} className="status-list__row">
            <span className="status-list__name">名刺 {index + 1}</span>
            <CardStatusBadge
              card={card}
              failed={failedCardIds.has(card.id)}
              retrying={retryingCardIds.has(card.id)}
            />
          </li>
        ))}
      </ul>
      <p className="hint">読み取りが終わった名刺から順に確認できます。</p>
    </div>
  );
}

function CardStatusBadge({ card, failed, retrying }: { card: CardSummary; failed: boolean; retrying: boolean }) {
  if (failed) {
    return <span className="badge badge--error">失敗</span>;
  }
  if (retrying) {
    return <span className="badge badge--busy">再試行中…</span>;
  }
  if (isCardReady(card.status)) {
    return <span className="badge badge--ok">{cardStatusLabel(card.status)}</span>;
  }
  return <span className="badge badge--busy">{cardStatusLabel(card.status)}</span>;
}
