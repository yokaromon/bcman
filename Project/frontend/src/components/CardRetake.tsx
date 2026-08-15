import { useRef, useState, type ChangeEvent } from 'react';
import {
  applyCardReplacement,
  cancelCardReplacement,
  cardReplacementPreviewUrl,
  startCardReplacement,
  type ReplacementDraft,
} from '../api';

type Props = {
  cardId: string;
  disabled: boolean;
  /** 差し替えが確定したとき。画像と（読み直した場合は）項目を読み込み直す。 */
  onReplaced: (reread: boolean) => void;
  onBusyChange: (busy: boolean) => void;
};

/**
 * 名刺画像の撮り直し。撮影 → 切り出し結果を確認 → 採用、の3段階で進む。
 * 採用するまで既存の画像には触れない（docs/adr/0013 参照）。
 */
export function CardRetake({ cardId, disabled, onReplaced, onBusyChange }: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<ReplacementDraft | null>(null);
  const [busy, setBusy] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const run = async (message: string, task: () => Promise<void>) => {
    setBusy(message);
    onBusyChange(true);
    setErrorMessage('');
    try {
      await task();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '撮り直しに失敗しました');
    } finally {
      setBusy('');
      onBusyChange(false);
    }
  };

  const pickFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // 同じファイルを選び直しても change が起きるようにリセットしておく
    event.target.value = '';
    if (!file) {
      return;
    }
    void run('切り出しています…', async () => {
      setDraft(await startCardReplacement(cardId, file));
    });
  };

  const cancel = () => {
    const pending = draft;
    if (!pending) {
      return;
    }
    setDraft(null);
    // 破棄は下見画像の後始末でしかないので、失敗しても利用者の操作は止めない
    void cancelCardReplacement(cardId, pending.token).catch(() => {});
  };

  const apply = (reread: boolean) => {
    const pending = draft;
    if (!pending) {
      return;
    }
    void run(reread ? '差し替えて読み直しています…' : '差し替えています…', async () => {
      await applyCardReplacement(cardId, pending.token, reread);
      setDraft(null);
      onReplaced(reread);
    });
  };

  if (draft) {
    return (
      <div className="retake retake--preview">
        <p className="retake__title">この切り出しで差し替えますか？</p>
        {!draft.detected && (
          <p className="alert alert--warn">名刺の外形を検出できませんでした。写真全体をそのまま使います。</p>
        )}
        <img className="retake__preview" src={cardReplacementPreviewUrl(cardId, draft.token)} alt="撮り直した名刺の切り出し結果" />
        {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
        <div className="retake__actions">
          <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={() => apply(false)}>
            {busy || '画像だけ差し替える'}
          </button>
          <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={() => apply(true)}>
            差し替えて読み直す
          </button>
          <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={cancel}>
            やめる
          </button>
        </div>
        <p className="hint">「読み直す」を選ぶと、入力済みの項目は読み取り結果で上書きされます。</p>
      </div>
    );
  }

  return (
    <div className="retake">
      <input
        ref={fileInput}
        className="retake__input"
        type="file"
        accept="image/jpeg,image/png"
        capture="environment"
        onChange={pickFile}
      />
      <button
        type="button"
        className="button button--ghost"
        disabled={disabled || Boolean(busy)}
        onClick={() => fileInput.current?.click()}
      >
        {busy || 'この名刺を撮り直す'}
      </button>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
    </div>
  );
}
