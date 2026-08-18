import { useRef, type ChangeEvent } from 'react';
import type { Group } from '../api';

type Props = {
  canUpload: boolean;
  blockedReason: string;
  busyMessage: string;
  errorMessage: string;
  onPick: (file: File) => void;
  groups: Group[];
  groupId: string;
  onGroupChange: (groupId: string) => void;
  recognitionV2Available: boolean;
  useRecognitionV2: boolean;
  onRecognitionV2Change: (value: boolean) => void;
};

export function CaptureScreen({
  canUpload,
  blockedReason,
  busyMessage,
  errorMessage,
  onPick,
  groups,
  groupId,
  onGroupChange,
  recognitionV2Available,
  useRecognitionV2,
  onRecognitionV2Change,
}: Props) {
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

      {groups.length > 1 && (
        <label className="field">
          <span className="field__label">登録先グループ</span>
          <select
            className="field__input"
            value={groupId}
            onChange={(event) => onGroupChange(event.target.value)}
          >
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {recognitionV2Available && (
        <label className="check-row">
          <input
            type="checkbox"
            checked={useRecognitionV2}
            onChange={(event) => onRecognitionV2Change(event.target.checked)}
          />
          新しい読み取り(V2)を試す
        </label>
      )}

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
