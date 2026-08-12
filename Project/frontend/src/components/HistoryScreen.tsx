import { useCallback, useEffect, useState } from 'react';
import {
  cardStatusLabel,
  cardThumbnailUrl,
  deletePhoto,
  fetchCards,
  fetchPhotos,
  photoThumbnailUrl,
  type CardSummary,
  type Me,
  type PhotoSummary,
} from '../api';
import { CardPager } from './CardPager';
import { ConfirmButton } from './ConfirmButton';
import { MediaCard } from './MediaCard';

/** 履歴では解析はすでに終わっているので、失敗マークは付けない。 */
const NO_FAILURES: Set<string> = new Set();

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

function describeCounts(photo: PhotoSummary): string {
  if (photo.card_count === 0) {
    return '名刺なし';
  }
  return `名刺 ${photo.card_count}枚 / 登録済み ${photo.confirmed_count}`;
}

function describePhotoDeletion(cards: CardSummary[]): string {
  if (cards.length === 0) {
    return 'この写真を削除します。元に戻せません。';
  }
  const confirmed = cards.filter((card) => card.status === 'confirmed').length;
  const registered = confirmed > 0 ? `うち登録済み ${confirmed}件` : '登録済みはなし';
  return `名刺 ${cards.length}枚（${registered}）も一緒に削除します。元に戻せません。`;
}

export function HistoryScreen({ user }: { user: Me | null }) {
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [openPhoto, setOpenPhoto] = useState<PhotoSummary | null>(null);
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [openCardIndex, setOpenCardIndex] = useState(-1);
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const loadPhotos = useCallback(async () => {
    if (!user) {
      setPhotos([]);
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      setPhotos(await fetchPhotos());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '写真を読み込めませんでした');
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    setOpenPhoto(null);
    setOpenCardIndex(-1);
    void loadPhotos();
  }, [loadPhotos]);

  const openPhotoCards = async (photo: PhotoSummary) => {
    setErrorMessage('');
    try {
      setCards(await fetchCards(photo.id));
      setOpenPhoto(photo);
      setOpenCardIndex(-1);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を読み込めませんでした');
    }
  };

  const reloadCards = async (photoId: string) => {
    try {
      setCards(await fetchCards(photoId));
    } catch {
      // 一覧の状態表示が古いままになるだけなので、閲覧は続けられる
    }
  };

  const removePhoto = async (photo: PhotoSummary) => {
    setErrorMessage('');
    try {
      await deletePhoto(photo.id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '写真を削除できませんでした');
      return;
    }
    setOpenPhoto(null);
    setOpenCardIndex(-1);
    setCards([]);
    await loadPhotos();
  };

  // 消した名刺の位置に残りを詰める。末尾を消したときだけ手前へ戻り、
  // 空になったら見る対象がないので名刺一覧へ抜ける。
  const handleCardDeleted = (cardId: string) => {
    const remaining = cards.filter((card) => card.id !== cardId);
    setCards(remaining);
    setOpenCardIndex(remaining.length === 0 ? -1 : Math.min(openCardIndex, remaining.length - 1));
    void loadPhotos();
  };

  if (openCardIndex >= 0 && cards[openCardIndex] && openPhoto) {
    return (
      <div className="screen">
        <button type="button" className="back-link" onClick={() => setOpenCardIndex(-1)}>
          ← 名刺一覧へ
        </button>
        <CardPager
          cards={cards}
          index={openCardIndex}
          failedCardIds={NO_FAILURES}
          confirmLabel="登録"
          onIndexChange={setOpenCardIndex}
          onConfirmed={() => void reloadCards(openPhoto.id)}
          onDeleted={handleCardDeleted}
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
        <h2 className="screen__title">{formatDate(openPhoto.created_at)} の写真</h2>
        {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
        {cards.length === 0 && <p className="hint">この写真に名刺はありません。</p>}
        <ul className="media-list">
          {cards.map((card, index) => (
            <li key={card.id}>
              <MediaCard
                src={cardThumbnailUrl(card.id)}
                alt={`名刺 ${index + 1}`}
                title={`名刺 ${index + 1}`}
                meta={cardStatusLabel(card.status)}
                onClick={() => setOpenCardIndex(index)}
              />
            </li>
          ))}
        </ul>
        <ConfirmButton
          label="この写真を削除"
          message={describePhotoDeletion(cards)}
          confirmLabel="削除する"
          onConfirm={() => removePhoto(openPhoto)}
        />
      </div>
    );
  }

  return (
    <div className="screen">
      <h2 className="screen__title">履歴</h2>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {loading && <p className="hint">読み込んでいます…</p>}
      {!loading && !errorMessage && photos.length === 0 && <p className="hint">まだ写真がありません。</p>}
      <ul className="media-list">
        {photos.map((photo) => (
          <li key={photo.id}>
            <MediaCard
              src={photoThumbnailUrl(photo.id)}
              alt={`${formatDate(photo.created_at)} の写真`}
              title={formatDate(photo.created_at)}
              meta={
                <>
                  <span>{describeCounts(photo)}</span>
                  <span>{PHOTO_STATUS_LABELS[photo.status] ?? photo.status}</span>
                </>
              }
              onClick={() => void openPhotoCards(photo)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
