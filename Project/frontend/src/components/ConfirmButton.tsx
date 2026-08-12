import { useState } from 'react';

type Props = {
  label: string;
  message: string;
  confirmLabel: string;
  disabled?: boolean;
  onConfirm: () => Promise<void>;
};

/**
 * 押すとその場で確認に切り替わるボタン。window.confirm を使わないのは、
 * iOS のネイティブダイアログが画面上部に出てボタンから視線が飛ぶうえ、
 * 見た目をアプリ側で揃えられないため。
 */
export function ConfirmButton({ label, message, confirmLabel, disabled, onConfirm }: Props) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        className="button button--danger"
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    );
  }

  const run = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      // 成功時はこの要素ごと消えることが多いが、失敗して残る場合に押せないままにしない
      setBusy(false);
      setAsking(false);
    }
  };

  return (
    <div className="confirm">
      <p className="confirm__message">{message}</p>
      <div className="confirm__actions">
        <button type="button" className="button button--ghost" disabled={busy} onClick={() => setAsking(false)}>
          やめる
        </button>
        <button type="button" className="button button--danger" disabled={busy} onClick={() => void run()}>
          {busy ? '削除しています…' : confirmLabel}
        </button>
      </div>
    </div>
  );
}
