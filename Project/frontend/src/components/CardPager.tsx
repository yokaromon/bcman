import { useEffect, useRef, useState, type TouchEvent } from 'react';
import { cardImageUrl, cardStatusLabel, deleteCard, isCardReady, type CardSummary } from '../api';
import { CardReviewBody, type ReviewMode } from './CardReviewBody';
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
  /** 'auto' は名刺ごとに切り替える。台帳のように確認済みと未確認が混ざる一覧で使う。 */
  mode?: ReviewMode | 'auto';
  onIndexChange: (next: number) => void;
  onConfirmed: (cardId: string) => void;
  onDeleted?: (cardId: string) => void;
  onFinish?: () => void;
  onCandidates?: () => void;
  onUpdated?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
};

export function CardPager({
  cards,
  index,
  failedCardIds,
  confirmLabel,
  mode = 'review',
  onIndexChange,
  onConfirmed,
  onDeleted,
  onFinish,
  onCandidates,
  onUpdated,
  onDirtyChange,
}: Props) {
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [previewRotation, setPreviewRotation] = useState(0);
  const [imageRevision, setImageRevision] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  // 未保存のまま移動しようとした行き先。破棄を選ぶまで移動しない。
  const [blockedIndex, setBlockedIndex] = useState<number | null>(null);
  const card = cards[index];
  const total = cards.length;

  useEffect(() => {
    setPreviewRotation(0);
    setImageRevision(card?.image_revision ?? '');
  }, [card?.id, card?.image_revision]);

  useEffect(() => {
    setBlockedIndex(null);
  }, [index]);

  const handleDirtyChange = (next: boolean) => {
    setDirty(next);
    onDirtyChange?.(next);
  };

  const rotatePreview = () => {
    setPreviewRotation((current) => (current + 90) % 360);
  };

  const goTo = (next: number) => {
    const clamped = Math.min(Math.max(next, 0), total - 1);
    if (clamped === index) {
      return;
    }
    // 台帳の修正は自動保存しない。黙って移動すると編集内容が消える
    if (dirty) {
      setBlockedIndex(clamped);
      return;
    }
    onIndexChange(clamped);
  };

  const discardAndGo = () => {
    const target = blockedIndex;
    setBlockedIndex(null);
    handleDirtyChange(false);
    if (target !== null) {
      onIndexChange(target);
    }
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
  const confirmed = card.status === 'confirmed';
  // 台帳は確認済みと未確認が混ざるので、開いた名刺に合わせて編集モードと操作名を変える。
  // 未確認を「保存」で閉じられると、登録したつもりのまま未確認で残る
  const reviewMode: ReviewMode = mode === 'auto' ? (confirmed ? 'edit' : 'review') : mode;
  const actionLabel = mode === 'auto' ? (confirmed ? '保存' : '登録') : confirmLabel;
  const deletionMessage = confirmed
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
        {!confirmed && <span className="card-image__badge">未確認</span>}
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
          className={previewRotation ? 'pager__arrow pager__arrow--active' : 'pager__arrow'}
          aria-label="画像を90度回転"
          disabled={busy}
          onClick={rotatePreview}
        >
          <RotateIcon />
        </button>
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

      {blockedIndex !== null && (
        <div className="alert alert--warn">
          <p>未保存の変更があります。先に「保存」を押すか、変更を破棄してください。</p>
          <div className="action-bar">
            <button type="button" className="button button--ghost" onClick={discardAndGo}>
              破棄して移動
            </button>
            <button type="button" className="button button--ghost" onClick={() => setBlockedIndex(null)}>
              編集を続ける
            </button>
          </div>
        </div>
      )}

      {showForm ? (
        <CardReviewBody
          key={card.id}
          cardId={card.id}
          failed={failed}
          confirmLabel={actionLabel}
          previewRotation={previewRotation}
          mode={reviewMode}
          onConfirmed={onConfirmed}
          onRotationChange={setPreviewRotation}
          onImageRevision={setImageRevision}
          onOrientationCommitted={onUpdated}
          onBusyChange={setBusy}
          onDirtyChange={handleDirtyChange}
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

function RotateIcon() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <polyline points="3 3 3 8 8 8" />
    </svg>
  );
}
