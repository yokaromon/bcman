import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchCards,
  fetchPhotos,
  isCardReady,
  reprocessCard,
  startProcessing,
  uploadPhoto,
  type CardSummary,
  type User,
} from './api';
import { CaptureScreen } from './components/CaptureScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { CardPager } from './components/CardPager';

const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

type Phase = 'idle' | 'uploading' | 'tracking' | 'done';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function describeError(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function CaptureFlow({ user }: { user: User | null }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [photoId, setPhotoId] = useState('');
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [confirmedCardIds, setConfirmedCardIds] = useState<Set<string>>(new Set());
  const [failedCardIds, setFailedCardIds] = useState<Set<string>>(new Set());
  const [fatalMessage, setFatalMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  // ポーリングのループ内から参照するため、再レンダリングに巻き込まれない実体を持つ
  const retriedRef = useRef<Set<string>>(new Set());
  const failedRef = useRef<Set<string>>(new Set());

  const userId = user?.id ?? '';
  const canUpload = Boolean(user && user.organization_id && user.group_id);
  const blockedReason = user
    ? '組織とグループに所属している利用者を選んでください。'
    : '利用者を選んでください。';

  const restart = useCallback(() => {
    retriedRef.current = new Set();
    failedRef.current = new Set();
    setPhase('idle');
    setPhotoId('');
    setCards([]);
    setReviewIndex(0);
    setConfirmedCardIds(new Set());
    setFailedCardIds(new Set());
    setFatalMessage('');
    setErrorMessage('');
  }, []);

  const handlePick = async (file: File) => {
    setPhase('uploading');
    setErrorMessage('');
    try {
      const uploadedId = await uploadPhoto(userId, file);
      await startProcessing(userId, uploadedId);
      setPhotoId(uploadedId);
      setPhase('tracking');
    } catch (error) {
      setErrorMessage(describeError(error, 'アップロードに失敗しました'));
      setPhase('idle');
    }
  };

  useEffect(() => {
    const shouldPoll = phase === 'tracking' && Boolean(photoId);
    if (!shouldPoll) {
      return;
    }

    let cancelled = false;

    const syncFailed = () => {
      setFailedCardIds(new Set(failedRef.current));
    };

    // 失敗した写真の未完了カードを1枚ずつ再解析する。失敗はカード単位で確定させ、
    // 他のカードの確認作業は止めない。
    const retryOnce = async (targets: CardSummary[]) => {
      for (const card of targets) {
        if (cancelled) {
          return;
        }
        retriedRef.current.add(card.id);
        try {
          await reprocessCard(userId, card.id);
        } catch {
          failedRef.current.add(card.id);
          syncFailed();
        }
      }
    };

    const pollOnce = async (): Promise<boolean> => {
      const photos = await fetchPhotos(userId);
      const photo = photos.find((item) => item.id === photoId);
      const currentCards = await fetchCards(userId, photoId);
      setCards(currentCards);

      const photoFailed = photo?.status === 'failed';
      if (photoFailed && currentCards.length === 0) {
        setFatalMessage('写真から名刺を読み取れませんでした。明るい場所で撮り直してください。');
        return true;
      }

      const unfinished = currentCards.filter(
        (card) => !isCardReady(card.status) && !failedRef.current.has(card.id),
      );
      if (unfinished.length === 0) {
        return true;
      }
      if (!photoFailed) {
        return false;
      }

      const notRetried = unfinished.filter((card) => !retriedRef.current.has(card.id));
      if (notRetried.length > 0) {
        await retryOnce(notRetried);
        return false;
      }

      for (const card of unfinished) {
        failedRef.current.add(card.id);
      }
      syncFailed();
      return true;
    };

    const run = async () => {
      const startedAt = Date.now();
      while (!cancelled) {
        try {
          const settled = await pollOnce();
          if (cancelled || settled) {
            return;
          }
        } catch (error) {
          setFatalMessage(describeError(error, '解析状況を取得できませんでした'));
          return;
        }
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          setFatalMessage('解析に時間がかかりすぎています。しばらくしてから履歴を確認してください。');
          return;
        }
        await sleep(POLL_INTERVAL_MS);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [phase, photoId, userId]);

  // 登録し終えたら残りの未登録へ送る。最後のページかどうかではなく、
  // 未登録が尽きたことをもって完了とする。
  const handleConfirmed = (cardId: string) => {
    const confirmed = new Set(confirmedCardIds).add(cardId);
    setConfirmedCardIds(confirmed);

    const isConfirmed = (card: CardSummary) => card.status === 'confirmed' || confirmed.has(card.id);
    if (cards.every(isConfirmed)) {
      setPhase('done');
      return;
    }

    const ahead = cards.findIndex((card, position) => position > reviewIndex && !isConfirmed(card));
    setReviewIndex(ahead >= 0 ? ahead : cards.findIndex((card) => !isConfirmed(card)));
  };

  if (phase === 'idle' || phase === 'uploading') {
    return (
      <CaptureScreen
        canUpload={canUpload}
        blockedReason={blockedReason}
        busyMessage={phase === 'uploading' ? '写真を送っています…' : ''}
        errorMessage={errorMessage}
        onPick={handlePick}
      />
    );
  }

  if (phase === 'done') {
    return (
      <div className="screen screen--center">
        <div className="hero__icon" aria-hidden="true">✅</div>
        <h2 className="hero__title">確認が終わりました</h2>
        <button type="button" className="button button--primary button--xl" onClick={restart}>
          続けて撮影
        </button>
      </div>
    );
  }

  if (fatalMessage || cards.length === 0) {
    return <ProcessingScreen fatalMessage={fatalMessage} onRestart={restart} />;
  }

  return (
    <CardPager
      userId={userId}
      cards={cards}
      index={reviewIndex}
      failedCardIds={failedCardIds}
      confirmLabel="登録して次へ"
      onIndexChange={setReviewIndex}
      onConfirmed={handleConfirmed}
      onFinish={() => setPhase('done')}
    />
  );
}
