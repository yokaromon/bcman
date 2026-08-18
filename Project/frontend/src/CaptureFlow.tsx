import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchCards,
  fetchPhotos,
  completeReview,
  isCardReady,
  reprocessCard,
  startProcessing,
  uploadPhoto,
  type CardSummary,
  type Me,
} from './api';
import { CaptureScreen } from './components/CaptureScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { CardPager } from './components/CardPager';
import { CandidateList } from './components/CandidateList';

const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

type Phase = 'idle' | 'uploading' | 'tracking' | 'done';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function describeError(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function CaptureFlow({ user }: { user: Me | null }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [photoId, setPhotoId] = useState('');
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [confirmedCardIds, setConfirmedCardIds] = useState<Set<string>>(new Set());
  const [failedCardIds, setFailedCardIds] = useState<Set<string>>(new Set());
  const [fatalMessage, setFatalMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [retainPhoto, setRetainPhoto] = useState(false);
  const [showCandidates, setShowCandidates] = useState(false);
  // 複数グループに所属する利用者は、撮影のたびにどのグループへ登録するか選ぶ
  const [groupId, setGroupId] = useState(user?.groups[0]?.id ?? '');

  // ポーリングのループ内から参照するため、再レンダリングに巻き込まれない実体を持つ
  const retriedRef = useRef<Set<string>>(new Set());
  const failedRef = useRef<Set<string>>(new Set());

  const canUpload = Boolean(user && groupId);
  const blockedReason = user ? '所属グループがありません。管理者にお問い合わせください。' : 'ログインしてください。';

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
    setRetainPhoto(false);
    setShowCandidates(false);
  }, []);

  const handlePick = async (file: File) => {
    setPhase('uploading');
    setErrorMessage('');
    try {
      const uploadedId = await uploadPhoto(groupId, file);
      await startProcessing(uploadedId);
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
          await reprocessCard(card.id);
        } catch {
          failedRef.current.add(card.id);
          syncFailed();
        }
      }
    };

    const pollOnce = async (): Promise<boolean> => {
      const photos = await fetchPhotos();
      const photo = photos.find((item) => item.id === photoId);
      const currentCards = await fetchCards(photoId);
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
  }, [phase, photoId]);

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

  // 誤検出を間引く。残りを詰めて同じ位置を見せ、最後の1枚なら手前へ。
  // 全部消えたら確認するものがないので完了扱いにする。
  const handleDeleted = (cardId: string) => {
    const remaining = cards.filter((card) => card.id !== cardId);
    setCards(remaining);
    failedRef.current.delete(cardId);
    setFailedCardIds(new Set(failedRef.current));
    if (remaining.length === 0) {
      setPhase('done');
      return;
    }
    setReviewIndex(Math.min(reviewIndex, remaining.length - 1));
  };

  if (phase === 'idle' || phase === 'uploading') {
    return (
      <CaptureScreen
        canUpload={canUpload}
        blockedReason={blockedReason}
        busyMessage={phase === 'uploading' ? '写真を送っています…' : ''}
        errorMessage={errorMessage}
        onPick={handlePick}
        groups={user?.groups ?? []}
        groupId={groupId}
        onGroupChange={setGroupId}
        recognitionV2Active={Boolean(user?.recognition_v2_active)}
      />
    );
  }

  if (phase === 'done') {
    return (
      <div className="screen screen--center">
        <div className="hero__icon" aria-hidden="true">✅</div>
        <h2 className="hero__title">確認が終わりました</h2>
        <label className="check-row">
          <input type="checkbox" checked={retainPhoto} onChange={(event) => setRetainPhoto(event.target.checked)} />
          撮影原本を保存する
        </label>
        <button
          type="button"
          className="button button--primary"
          onClick={() => void completeReview(photoId, retainPhoto).catch((error: unknown) => setErrorMessage(describeError(error, '確認を完了できませんでした')))}
        >
          確認を完了
        </button>
        {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
        <button type="button" className="button button--primary button--xl" onClick={restart}>
          続けて撮影
        </button>
      </div>
    );
  }

  if (fatalMessage || cards.length === 0) {
    return <ProcessingScreen fatalMessage={fatalMessage} onRestart={restart} />;
  }

  if (showCandidates) {
    return <CandidateList photoId={photoId} cards={cards} onOpen={(next) => { setReviewIndex(next); setShowCandidates(false); }} onUpdated={() => { void fetchCards(photoId).then(setCards); }} onBack={() => setShowCandidates(false)} />;
  }

  // index を末尾で止めるのは、削除とポーリングの更新が前後したときに
  // 範囲外を指して空白画面になるのを防ぐため。
  return (
    <CardPager
      cards={cards}
      index={Math.min(reviewIndex, cards.length - 1)}
      failedCardIds={failedCardIds}
      confirmLabel="登録して次へ"
      onIndexChange={setReviewIndex}
      onConfirmed={handleConfirmed}
      onDeleted={handleDeleted}
      onFinish={() => setPhase('done')}
      onCandidates={() => setShowCandidates(true)}
      onUpdated={() => { void fetchCards(photoId).then(setCards); }}
    />
  );
}
