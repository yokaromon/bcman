import { useRef, type ChangeEvent } from 'react';

type Props = {
  canUpload: boolean;
  blockedReason: string;
  busyMessage: string;
  errorMessage: string;
  onPick: (file: File) => void;
};

export function CaptureScreen({ canUpload, blockedReason, busyMessage, errorMessage, onPick }: Props) {
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // 同じ写真を選び直しても change が発火するように値を消す
    event.target.value = '';
    if (!file) {
      return;
    }
    onPick(file);
  };

  if (busyMessage) {
    return (
      <div className="screen screen--center">
        <div className="spinner" />
        <p className="lead">{busyMessage}</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <div className="hero">
        <div className="hero__icon" aria-hidden="true">📇</div>
        <h2 className="hero__title">名刺を撮影</h2>
        <p className="hero__note">1枚の写真に複数の名刺が写っていても、まとめて読み取ります。</p>
      </div>

      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {!canUpload && <p className="alert alert--warn">{blockedReason}</p>}

      <input
        ref={cameraInput}
        className="hidden-input"
        type="file"
        accept="image/jpeg,image/png"
        capture="environment"
        onChange={handleChange}
      />
      <input
        ref={fileInput}
        className="hidden-input"
        type="file"
        accept="image/jpeg,image/png"
        onChange={handleChange}
      />

      <button
        type="button"
        className="button button--primary button--xl"
        disabled={!canUpload}
        onClick={() => cameraInput.current?.click()}
      >
        カメラで撮影
      </button>
      <button
        type="button"
        className="button button--ghost"
        disabled={!canUpload}
        onClick={() => fileInput.current?.click()}
      >
        写真を選ぶ
      </button>

      <p className="hint">JPEG / PNG・20MBまで</p>
    </div>
  );
}
