import { useCallback, useEffect, useState } from 'react';
import {
  cardStatusLabel,
  fetchCards,
  fetchPhotos,
  type CardSummary,
  type PhotoSummary,
  type User,
} from '../api';
import { CardReviewScreen } from './CardReviewScreen';

const PHOTO_STATUS_LABELS: Record<string, string> = {
  uploaded: 'アップロード済み',
  detecting: '検出中',
  detected: '検出済み',
  completed: '解析完了',
  failed: '失敗',
};

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function HistoryScreen({ user }: { user: User | null }) {
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [openPhoto, setOpenPhoto] = useState<PhotoSummary | null>(null);
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [openCardIndex, setOpenCardIndex] = useState(-1);
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const userId = user?.id ?? '';

  const loadPhotos = useCallback(async () => {
    if (!userId) {
      setPhotos([]);
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      setPhotos(await fetchPhotos(userId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '写真を読み込めませんでした');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    setOpenPhoto(null);
    setOpenCardIndex(-1);
    void loadPhotos();
  }, [loadPhotos]);

  const openPhotoCards = async (photo: PhotoSummary) => {
    setErrorMessage('');
    try {
      setCards(await fetchCards(userId, photo.id));
      setOpenPhoto(photo);
      setOpenCardIndex(-1);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を読み込めませんでした');
    }
  };

  if (openCardIndex >= 0 && cards[openCardIndex]) {
    const card = cards[openCardIndex];
    return (
      <div className="screen screen--form">
        <button type="button" className="back-link" onClick={() => setOpenCardIndex(-1)}>
          ← 名刺一覧へ
        </button>
        <CardReviewScreen
          key={card.id}
          userId={userId}
          cardId={card.id}
          position={openCardIndex + 1}
          total={cards.length}
          failed={false}
          onAdvance={() => setOpenCardIndex(-1)}
        />
      </div>
    );
  }

  if (openPhoto) {
    return (
      <div className="screen">
        <button type="button" className="back-link" onClick={() => setOpenPhoto(null)}>
          ← 写真一覧へ
        </button>
        <h2 className="screen__title">{openPhoto.filename}</h2>
        {cards.length === 0 && <p className="hint">この写真に名刺はありません。</p>}
        <ul className="status-list">
          {cards.map((card, index) => (
            <li key={card.id}>
              <button type="button" className="row-button" onClick={() => setOpenCardIndex(index)}>
                <span>名刺 {index + 1}</span>
                <span className="row-button__meta">{cardStatusLabel(card.status)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2 className="screen__title">履歴</h2>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {loading && <p className="hint">読み込んでいます…</p>}
      {!loading && photos.length === 0 && <p className="hint">まだ写真がありません。</p>}
      <ul className="status-list">
        {photos.map((photo) => (
          <li key={photo.id}>
            <button type="button" className="row-button" onClick={() => openPhotoCards(photo)}>
              <span>{formatDate(photo.created_at)}</span>
              <span className="row-button__meta">{PHOTO_STATUS_LABELS[photo.status] ?? photo.status}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
