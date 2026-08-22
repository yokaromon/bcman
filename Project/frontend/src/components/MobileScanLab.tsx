import { useCallback, useEffect, useRef, useState } from 'react';
import {
  captureGuidedCard,
  type GuidedCardCapture,
} from '../api';

const SAMPLE_WIDTH = 160;
const SAMPLE_HEIGHT = 97;
const ANALYZE_INTERVAL_MS = 250;
const STABLE_FRAME_COUNT = 4;
const STABLE_DIFF_MAX = 4.5;
const RELEASE_DIFF_MIN = 10;
const DETAIL_MIN = 4.5;
const CAPTURE_MAX_EDGE = 2400;
const DUPLICATE_DISTANCE_MAX = 5;

type ScanPhase =
  | 'stopped'
  | 'searching'
  | 'holding'
  | 'verifying'
  | 'release'
  | 'finished';

type FrameSample = {
  pixels: Uint8Array;
  detail: number;
  brightness: number;
  glareRatio: number;
};

type CapturedCard = GuidedCardCapture & {
  id: string;
};

type SourceRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const PHASE_LABELS: Record<ScanPhase, string> = {
  stopped: '停止中',
  searching: '名刺を探しています',
  holding: '静止判定中',
  verifying: 'サーバ確認中',
  release: '次の名刺を待っています',
  finished: '撮影終了',
};

function canvasBlob(canvas: HTMLCanvasElement, quality = 0.92): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('画像をJPEG化できません'))),
      'image/jpeg',
      quality,
    );
  });
}

function frameDifference(first: Uint8Array, second: Uint8Array): number {
  if (first.length !== second.length) {
    return Number.POSITIVE_INFINITY;
  }
  let total = 0;
  for (let index = 0; index < first.length; index += 1) {
    total += Math.abs(first[index] - second[index]);
  }
  return total / first.length;
}

function fingerprintDistance(first: string, second: string): number {
  if (first.length !== second.length) {
    return Number.POSITIVE_INFINITY;
  }
  let distance = 0;
  for (let index = 0; index < first.length; index += 1) {
    let value = Number.parseInt(first[index], 16) ^ Number.parseInt(second[index], 16);
    while (value) {
      distance += value & 1;
      value >>= 1;
    }
  }
  return distance;
}

function guideSourceRect(video: HTMLVideoElement, guide: HTMLDivElement): SourceRect {
  if (!video.videoWidth || !video.videoHeight) {
    throw new Error('カメラ映像の準備中です');
  }
  const videoBounds = video.getBoundingClientRect();
  const guideBounds = guide.getBoundingClientRect();
  const scale = Math.min(
    videoBounds.width / video.videoWidth,
    videoBounds.height / video.videoHeight,
  );
  const renderedWidth = video.videoWidth * scale;
  const renderedHeight = video.videoHeight * scale;
  const renderedLeft = videoBounds.left + (videoBounds.width - renderedWidth) / 2;
  const renderedTop = videoBounds.top + (videoBounds.height - renderedHeight) / 2;
  const left = Math.max(renderedLeft, guideBounds.left);
  const top = Math.max(renderedTop, guideBounds.top);
  const right = Math.min(renderedLeft + renderedWidth, guideBounds.right);
  const bottom = Math.min(renderedTop + renderedHeight, guideBounds.bottom);
  if (right <= left || bottom <= top) {
    throw new Error('ガイド範囲をカメラ画像へ対応付けできません');
  }
  return {
    x: (left - renderedLeft) / scale,
    y: (top - renderedTop) / scale,
    width: (right - left) / scale,
    height: (bottom - top) / scale,
  };
}

function drawGuideFrame(
  video: HTMLVideoElement,
  guide: HTMLDivElement,
  canvas: HTMLCanvasElement,
  maxEdge: number,
): void {
  const source = guideSourceRect(video, guide);
  const outputScale = Math.min(1, maxEdge / Math.max(source.width, source.height));
  canvas.width = Math.max(1, Math.round(source.width * outputScale));
  canvas.height = Math.max(1, Math.round(source.height * outputScale));
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) {
    throw new Error('カメラ画像を取得できません');
  }
  context.drawImage(
    video,
    source.x,
    source.y,
    source.width,
    source.height,
    0,
    0,
    canvas.width,
    canvas.height,
  );
}

function readFrameSample(canvas: HTMLCanvasElement): FrameSample {
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) {
    throw new Error('フレーム品質を確認できません');
  }
  const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const pixels = new Uint8Array(canvas.width * canvas.height);
  let brightness = 0;
  let glareCount = 0;
  for (let pixel = 0; pixel < pixels.length; pixel += 1) {
    const offset = pixel * 4;
    const gray = Math.round(
      rgba[offset] * 0.299 + rgba[offset + 1] * 0.587 + rgba[offset + 2] * 0.114,
    );
    pixels[pixel] = gray;
    brightness += gray;
    if (gray >= 248) {
      glareCount += 1;
    }
  }
  let detail = 0;
  let comparisons = 0;
  for (let y = 1; y < canvas.height; y += 1) {
    for (let x = 1; x < canvas.width; x += 1) {
      const index = y * canvas.width + x;
      detail += Math.abs(pixels[index] - pixels[index - 1]);
      detail += Math.abs(pixels[index] - pixels[index - canvas.width]);
      comparisons += 2;
    }
  }
  return {
    pixels,
    detail: detail / Math.max(1, comparisons),
    brightness: brightness / pixels.length,
    glareRatio: glareCount / pixels.length,
  };
}

export function MobileScanLab({ onClose }: { onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sampleCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const phaseRef = useRef<ScanPhase>('stopped');
  const busyRef = useRef(false);
  const lastSampleRef = useRef<Uint8Array | null>(null);
  const releaseSampleRef = useRef<Uint8Array | null>(null);
  const stableFramesRef = useRef(0);
  const changedFramesRef = useRef(0);
  const capturesRef = useRef<CapturedCard[]>([]);
  const mountedRef = useRef(true);
  const [cameraActive, setCameraActive] = useState(false);
  const [phase, setPhaseState] = useState<ScanPhase>('stopped');
  const [message, setMessage] = useState('ライブカメラを開始してください。');
  const [errorMessage, setErrorMessage] = useState('');
  const [quality, setQuality] = useState<FrameSample | null>(null);
  const [cameraSize, setCameraSize] = useState('未取得');
  const [captures, setCaptures] = useState<CapturedCard[]>([]);
  const [lastModel, setLastModel] = useState('');

  const setPhase = useCallback((next: ScanPhase) => {
    phaseRef.current = next;
    setPhaseState(next);
  }, []);

  const replaceCaptures = useCallback((next: CapturedCard[]) => {
    capturesRef.current = next;
    setCaptures(next);
  }, []);

  const resetFrameState = useCallback(() => {
    lastSampleRef.current = null;
    releaseSampleRef.current = null;
    stableFramesRef.current = 0;
    changedFramesRef.current = 0;
    setQuality(null);
  }, []);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
  }, []);

  const stopCamera = useCallback(() => {
    stopTracks();
    resetFrameState();
    if (phaseRef.current !== 'finished') {
      setPhase('stopped');
      setMessage('カメラを停止しました。取得済みの名刺は画面内に残っています。');
    }
  }, [resetFrameState, setPhase, stopTracks]);

  useEffect(() => {
    mountedRef.current = true;
    window.addEventListener('pagehide', stopCamera);
    return () => {
      mountedRef.current = false;
      window.removeEventListener('pagehide', stopCamera);
      stopTracks();
    };
  }, [stopCamera, stopTracks]);

  const startCamera = async () => {
    setErrorMessage('');
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('ライブカメラにはHTTPS接続が必要です。');
      return;
    }
    try {
      stopTracks();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 3840 },
          height: { ideal: 2160 },
        },
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      video.srcObject = stream;
      await video.play();
      const settings = stream.getVideoTracks()[0]?.getSettings();
      setCameraSize(`${settings?.width ?? video.videoWidth}×${settings?.height ?? video.videoHeight}`);
      resetFrameState();
      setCameraActive(true);
      setPhase('searching');
      setMessage('名刺1枚の外周をガイド枠へ合わせ、そのまま静止してください。');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'カメラを開始できません');
    }
  };

  const captureSample = useCallback((): FrameSample => {
    const video = videoRef.current;
    const guide = guideRef.current;
    if (!video || !guide) {
      throw new Error('カメラガイドを取得できません');
    }
    const canvas = sampleCanvasRef.current ?? document.createElement('canvas');
    sampleCanvasRef.current = canvas;
    canvas.width = SAMPLE_WIDTH;
    canvas.height = SAMPLE_HEIGHT;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) {
      throw new Error('フレーム品質を確認できません');
    }
    const source = guideSourceRect(video, guide);
    context.drawImage(
      video,
      source.x,
      source.y,
      source.width,
      source.height,
      0,
      0,
      SAMPLE_WIDTH,
      SAMPLE_HEIGHT,
    );
    return readFrameSample(canvas);
  }, []);

  const captureGuideBlob = useCallback(async (): Promise<Blob> => {
    const video = videoRef.current;
    const guide = guideRef.current;
    if (!video || !guide) {
      throw new Error('カメラガイドを取得できません');
    }
    const canvas = document.createElement('canvas');
    drawGuideFrame(video, guide, canvas, CAPTURE_MAX_EDGE);
    return canvasBlob(canvas);
  }, []);

  const submitGuidedCapture = useCallback(async () => {
    if (busyRef.current || !streamRef.current) {
      return;
    }
    busyRef.current = true;
    setErrorMessage('');
    setPhase('verifying');
    setMessage('ガイド内の1枚をサーバで確認し、四隅を補正しています…');
    let baseline: FrameSample | null = null;
    try {
      baseline = captureSample();
      const result = await captureGuidedCard(await captureGuideBlob());
      if (!mountedRef.current) {
        return;
      }
      setLastModel(result.semantic_model);
      if (!result.accepted || !result.card) {
        setMessage('名刺1枚と確認できませんでした。いったん枠から外して合わせ直してください。');
      } else {
        const duplicate = capturesRef.current.some(
          (item) => fingerprintDistance(item.fingerprint, result.card!.fingerprint) <= DUPLICATE_DISTANCE_MAX,
        );
        if (duplicate) {
          setMessage('同じ名刺がすでにピックアップされています。次の名刺へ移ってください。');
        } else {
          const next = [
            ...capturesRef.current,
            { ...result.card, id: `${Date.now()}-${result.card.fingerprint}` },
          ];
          replaceCaptures(next);
          navigator.vibrate?.(80);
          setMessage(`${next.length}枚目をピックアップしました。名刺を枠から外してください。`);
        }
      }
      releaseSampleRef.current = baseline.pixels;
      lastSampleRef.current = null;
      stableFramesRef.current = 0;
      changedFramesRef.current = 0;
      setPhase('release');
    } catch (error) {
      if (mountedRef.current) {
        setErrorMessage(error instanceof Error ? error.message : '名刺を確認できませんでした');
        setMessage('通信または画像取得に失敗しました。静止してもう一度お試しください。');
        setPhase('searching');
      }
    } finally {
      busyRef.current = false;
    }
  }, [captureGuideBlob, captureSample, replaceCaptures, setPhase]);

  useEffect(() => {
    if (!cameraActive) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (busyRef.current || phaseRef.current === 'finished' || phaseRef.current === 'stopped') {
        return;
      }
      try {
        const sample = captureSample();
        setQuality(sample);
        if (phaseRef.current === 'release') {
          const baseline = releaseSampleRef.current;
          if (baseline && frameDifference(baseline, sample.pixels) >= RELEASE_DIFF_MIN) {
            changedFramesRef.current += 1;
          } else {
            changedFramesRef.current = 0;
          }
          if (changedFramesRef.current >= 2) {
            resetFrameState();
            setPhase('searching');
            setMessage('次の名刺をガイド枠へ合わせて静止してください。');
          }
          return;
        }

        const qualityProblem =
          sample.brightness < 35
            ? '暗すぎます。照明を明るくしてください。'
            : sample.brightness > 245
              ? '明るすぎます。反射を避けてください。'
              : sample.glareRatio > 0.42
                ? '白飛びが多いため、カメラの角度を少し変えてください。'
                : sample.detail < DETAIL_MIN
                  ? '名刺を枠いっぱいに合わせ、ピントが合うまで待ってください。'
                  : '';
        if (qualityProblem) {
          stableFramesRef.current = 0;
          lastSampleRef.current = sample.pixels;
          setPhase('searching');
          setMessage(qualityProblem);
          return;
        }

        const previous = lastSampleRef.current;
        const difference = previous
          ? frameDifference(previous, sample.pixels)
          : Number.POSITIVE_INFINITY;
        lastSampleRef.current = sample.pixels;
        if (difference <= STABLE_DIFF_MAX) {
          stableFramesRef.current += 1;
          setPhase('holding');
          setMessage(`静止判定中… ${Math.min(stableFramesRef.current, STABLE_FRAME_COUNT)}/${STABLE_FRAME_COUNT}`);
        } else {
          stableFramesRef.current = 0;
          setPhase('searching');
          setMessage('名刺1枚の外周をガイド枠へ合わせ、そのまま静止してください。');
        }
        if (stableFramesRef.current >= STABLE_FRAME_COUNT) {
          void submitGuidedCapture();
        }
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : '動画フレームを解析できません');
      }
    }, ANALYZE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [cameraActive, captureSample, resetFrameState, setPhase, submitGuidedCapture]);

  const finishCapture = () => {
    stopTracks();
    resetFrameState();
    setPhase('finished');
    setMessage(`${capturesRef.current.length}枚で撮影を終了しました。補正済み画像を確認してください。`);
  };

  const removeCapture = (id: string) => {
    replaceCaptures(capturesRef.current.filter((item) => item.id !== id));
  };

  const clearCaptures = () => {
    replaceCaptures([]);
    setMessage(cameraActive ? '一覧をクリアしました。次の名刺を合わせてください。' : '一覧をクリアしました。');
  };

  return (
    <div className="screen mobile-lab">
      <div className="mobile-lab__heading">
        <button type="button" className="button button--ghost" onClick={onClose}>撮影画面へ戻る</button>
        <span className="mobile-lab__badge">非保存・1枚ずつ</span>
      </div>

      <div className="hero">
        <div className="hero__icon" aria-hidden="true">🎥</div>
        <h2 className="hero__title">名刺を1枚ずつピックアップ</h2>
        <p className="hero__note">中央の枠へ1枚ずつ合わせると自動撮影します。補正済み画像はこの画面を閉じるまでだけ保持します。</p>
      </div>

      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      <p className={`mobile-lab__status mobile-lab__status--${phase}`} aria-live="polite">
        <strong>{PHASE_LABELS[phase]}</strong><br />{message}
      </p>

      <div className="mobile-lab__video-stage">
        <video ref={videoRef} autoPlay muted playsInline />
        <div ref={guideRef} className={`mobile-lab__guide mobile-lab__guide--${phase}`} aria-hidden="true">
          <span>名刺1枚を枠いっぱいに</span>
        </div>
        {!cameraActive && <span className="mobile-lab__video-placeholder">カメラ停止中</span>}
      </div>

      <div className="mobile-lab__telemetry" aria-label="撮影状態">
        <span>カメラ {cameraSize}</span>
        <span>鮮明度 {quality ? quality.detail.toFixed(1) : '-'}</span>
        <span>取得 {captures.length}枚</span>
      </div>

      <div className="mobile-lab__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={cameraActive || phase === 'verifying'}
          onClick={() => void startCamera()}
        >
          {phase === 'finished' ? '撮影を再開' : 'ライブカメラを開始'}
        </button>
        <button
          type="button"
          className="button button--ghost"
          disabled={!cameraActive || phase === 'verifying'}
          onClick={stopCamera}
        >
          カメラ停止
        </button>
      </div>

      <button
        type="button"
        className="button button--primary button--xl"
        disabled={!cameraActive || phase === 'verifying' || phase === 'release'}
        onClick={() => void submitGuidedCapture()}
      >
        {phase === 'verifying' ? 'サーバで確認中…' : '今すぐ1枚を判定'}
      </button>

      <button
        type="button"
        className="button button--ghost"
        disabled={phase === 'verifying' || captures.length === 0}
        onClick={finishCapture}
      >
        撮影終了（{captures.length}枚）
      </button>

      <p className="hint">
        自動撮影後は、同じ名刺の連続取得を防ぐため一度ガイド枠から外してください。
        {lastModel ? ` 判定モデル: ${lastModel}` : ''}
      </p>

      <section className="mobile-lab__result">
        <div className="mobile-lab__result-title">
          <h3>ピックアップ済み</h3>
          <div className="mobile-lab__result-actions">
            <span className={`mobile-lab__badge ${captures.length ? 'mobile-lab__badge--ready' : ''}`}>{captures.length}枚</span>
            {captures.length > 0 && (
              <button type="button" className="button button--ghost button--small" onClick={clearCaptures}>クリア</button>
            )}
          </div>
        </div>
        {captures.length === 0 ? (
          <p className="hint">まだ名刺を取得していません。</p>
        ) : (
          <ol className="mobile-lab__gallery">
            {captures.map((card, index) => (
              <li key={card.id} className="mobile-lab__gallery-card">
                <img src={card.crop_data_url} alt={`ピックアップした名刺 ${index + 1}`} />
                <div>
                  <strong>#{index + 1}</strong>
                  <span>cardness {card.semantic_confidence.toFixed(3)}</span>
                  <span>{card.crop_size.width}×{card.crop_size.height}px</span>
                </div>
                <button type="button" className="button button--ghost button--small" onClick={() => removeCapture(card.id)}>削除</button>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
