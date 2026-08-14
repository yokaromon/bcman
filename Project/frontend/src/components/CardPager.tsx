import { useEffect, useRef, useState, type TouchEvent } from 'react';
import { cardImageUrl, cardStatusLabel, deleteCard, isCardReady, type CardSummary } from '../api';
import { CardReviewBody } from './CardReviewBody';
import { ConfirmButton } from './ConfirmButton';

/** 縦スクロールを横めくりと取り違えないための閾値。 */
const SWIPE_MIN_PX = 50;
const SWIPE_HORIZONTAL_RATIO = 1.5;
/** これを超えるとドットが潰れて数えられないので、枚数表示だけにする。 */
const MAX_DOTS = 8;

type Props = {
  cards: CardSummary[];
  index: number;
  failedCardIds: Set<string>;
  confirmLabel: string;
  onIndexChange: (next: number) => void;
  onConfirmed: (cardId: string) => void;
  onDeleted?: (cardId: string) => void;
  onFinish?: () => void;
  onCandidates?: () => void;
};

export function CardPager({
  cards,
  index,
  failedCardIds,
  confirmLabel,
  onIndexChange,
  onConfirmed,
  onDeleted,
  onFinish,
  onCandidates,
}: Props) {
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [previewRotation, setPreviewRotation] = useState(0);
  const [imageRevision, setImageRevision] = useState('');
  const card = cards[index];
  const total = cards.length;

  useEffect(() => {
    setPreviewRotation(0);
    setImageRevision(card?.image_revision ?? '');
  }, [card?.id, card?.image_revision]);

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
  const deletionMessage =
    card.status === 'confirmed'
      ? 'この名刺は登録済みです。削除すると連絡先も消えます。元に戻せません。'
      : 'この名刺と読み取り結果を削除します。元に戻せません。';

  const remove = async () => {
    setErrorMessage('');
    try {
      await deleteCard(card.id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を削除できませんでした');
      return;
    }
    onDeleted?.(card.id);
  };

  return (
    <div className="screen screen--form">
      {/* 入力欄でのカーソル移動と競合しないよう、スワイプは画像の上だけで拾う */}
      <div className="card-image" onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
        <img key={`${card.id}-${imageRevision}`} className={previewRotation ? 'card-image__rotated' : ''} style={{ transform: `rotate(${previewRotation}deg)` }} src={cardImageUrl(card.id, imageRevision || card.image_revision)} alt={`名刺 ${index + 1} の画像`} />
        {total > 1 && <span className="card-image__hint">← 画像を左右にスワイプで切り替え →</span>}
      </div>

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

      {showForm ? (
        <CardReviewBody
          key={card.id}
          cardId={card.id}
          failed={failed}
          confirmLabel={confirmLabel}
          onConfirmed={onConfirmed}
          onPreviewRotation={setPreviewRotation}
          onImageRevision={setImageRevision}
        />
      ) : (
        <div className="waiting">
          <div className="spinner" />
          <p className="lead">{cardStatusLabel(card.status)}…</p>
        </div>
      )}

      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}

      {onDeleted && (
        <ConfirmButton
          label="この名刺を削除"
          message={deletionMessage}
          confirmLabel="削除する"
          onConfirm={remove}
        />
      )}

      {onFinish && (
        <div className="action-bar">
          {onCandidates && <button type="button" className="button button--ghost" onClick={onCandidates}>候補一覧・一括登録</button>}
          <button type="button" className="button button--ghost" onClick={onFinish}>確認を完了</button>
        </div>
      )}
    </div>
  );
}
