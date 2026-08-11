import { useRef, type TouchEvent } from 'react';
import { cardImageUrl, cardStatusLabel, isCardReady, type CardSummary } from '../api';
import { CardReviewBody } from './CardReviewBody';

/** 縦スクロールを横めくりと取り違えないための閾値。 */
const SWIPE_MIN_PX = 50;
const SWIPE_HORIZONTAL_RATIO = 1.5;
/** これを超えるとドットが潰れて数えられないので、枚数表示だけにする。 */
const MAX_DOTS = 8;

type Props = {
  userId: string;
  cards: CardSummary[];
  index: number;
  failedCardIds: Set<string>;
  confirmLabel: string;
  onIndexChange: (next: number) => void;
  onConfirmed: (cardId: string) => void;
  onFinish?: () => void;
};

export function CardPager({
  userId,
  cards,
  index,
  failedCardIds,
  confirmLabel,
  onIndexChange,
  onConfirmed,
  onFinish,
}: Props) {
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const card = cards[index];
  const total = cards.length;

  const goTo = (next: number) => {
    const clamped = Math.min(Math.max(next, 0), total - 1);
    if (clamped === index) {
      return;
    }
    onIndexChange(clamped);
  };

  const handleTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    touchStart.current = { x: touch.clientX, y: touch.clientY };
  };

  const handleTouchEnd = (event: TouchEvent<HTMLDivElement>) => {
    const start = touchStart.current;
    touchStart.current = null;
    if (!start) {
      return;
    }

    const touch = event.changedTouches[0];
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    const isHorizontalSwipe =
      Math.abs(deltaX) > SWIPE_MIN_PX && Math.abs(deltaX) > Math.abs(deltaY) * SWIPE_HORIZONTAL_RATIO;
    if (!isHorizontalSwipe) {
      return;
    }
    goTo(index + (deltaX < 0 ? 1 : -1));
  };

  if (!card) {
    return null;
  }

  const failed = failedCardIds.has(card.id);
  const showForm = failed || isCardReady(card.status);

  return (
    <div className="screen screen--form">
      <div className="pager">
        <button
          type="button"
          className="pager__arrow"
          aria-label="前の名刺"
          disabled={index === 0}
          onClick={() => goTo(index - 1)}
        >
          ‹
        </button>
        <div className="pager__center">
          <span className="pager__count">
            名刺 {index + 1} / {total}
          </span>
          {total > 1 && total <= MAX_DOTS && (
            <span className="pager__dots">
              {cards.map((item, dotIndex) => (
                <span
                  key={item.id}
                  className={dotIndex === index ? 'pager__dot pager__dot--active' : 'pager__dot'}
                />
              ))}
            </span>
          )}
        </div>
        <button
          type="button"
          className="pager__arrow"
          aria-label="次の名刺"
          disabled={index === total - 1}
          onClick={() => goTo(index + 1)}
        >
          ›
        </button>
      </div>

      {/* 入力欄でのカーソル移動と競合しないよう、スワイプは画像の上だけで拾う */}
      <div className="card-image" onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
        <img src={cardImageUrl(card.id)} alt={`名刺 ${index + 1} の画像`} />
        {total > 1 && <span className="card-image__hint">← 画像を左右にスワイプで切り替え →</span>}
      </div>

      {showForm ? (
        <CardReviewBody
          key={card.id}
          userId={userId}
          cardId={card.id}
          failed={failed}
          confirmLabel={confirmLabel}
          onConfirmed={onConfirmed}
        />
      ) : (
        <div className="waiting">
          <div className="spinner" />
          <p className="lead">{cardStatusLabel(card.status)}…</p>
        </div>
      )}

      {onFinish && (
        <button type="button" className="button button--ghost" onClick={onFinish}>
          終了
        </button>
      )}
    </div>
  );
}
