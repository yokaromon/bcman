import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import {
  detectCardRectangles,
  type CardDetectionResult,
} from '../api';

const RESULT_MAX_EDGE = 1600;

type ImageCaptureLike = {
  takePhoto: () => Promise<Blob>;
};

type ImageCaptureConstructor = new (track: MediaStreamTrack) => ImageCaptureLike;

function canvasBlob(canvas: HTMLCanvasElement, quality = 0.94): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('画像をJPEG化できません'))),
      'image/jpeg',
      quality,
    );
  });
}

async function blobImage(blob: Blob): Promise<ImageBitmap | HTMLImageElement> {
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(blob, { imageOrientation: 'from-image' });
    } catch {
      return await createImageBitmap(blob);
    }
  }
  const url = URL.createObjectURL(blob);
  const image = new Image();
  image.src = url;
  try {
    await image.decode();
    return image;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function imageDimensions(image: ImageBitmap | HTMLImageElement): { width: number; height: number } {
  if (image instanceof HTMLImageElement) {
    return { width: image.naturalWidth, height: image.naturalHeight };
  }
  return { width: image.width, height: image.height };
}

function closeBitmap(image: ImageBitmap | HTMLImageElement): void {
  if ('close' in image && typeof image.close === 'function') {
    image.close();
  }
}

async function renderResult(
  canvas: HTMLCanvasElement,
  blob: Blob,
  result: CardDetectionResult,
): Promise<void> {
  const image = await blobImage(blob);
  const source = imageDimensions(image);
  const scale = Math.min(1, RESULT_MAX_EDGE / Math.max(source.width, source.height));
  canvas.width = Math.max(1, Math.round(source.width * scale));
  canvas.height = Math.max(1, Math.round(source.height * scale));
  const context = canvas.getContext('2d');
  if (!context) {
    closeBitmap(image);
    throw new Error('結果表示用Canvasを作成できません');
  }
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  closeBitmap(image);

  const coordinateScaleX = canvas.width / result.source_size.width;
  const coordinateScaleY = canvas.height / result.source_size.height;
  const lineWidth = Math.max(3, Math.round(Math.max(canvas.width, canvas.height) / 420));
  context.lineJoin = 'round';
  context.font = `bold ${Math.max(20, lineWidth * 6)}px system-ui`;
  for (const card of result.cards) {
    const points = card.corners.map(([x, y]) => [x * coordinateScaleX, y * coordinateScaleY] as const);
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    for (const [x, y] of points.slice(1)) {
      context.lineTo(x, y);
    }
    context.closePath();
    context.strokeStyle = '#21c77a';
    context.lineWidth = lineWidth;
    context.stroke();
    context.fillStyle = '#d51f5d';
    context.fillText(String(card.index), points[0][0], Math.max(24, points[0][1] - 8));
  }
}

export function MobileScanLab({ onClose }: { onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const resultCanvasRef = useRef<HTMLCanvasElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraActive, setCameraActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('ライブカメラを開始し、名刺が見える状態で抽出してください。');
  const [errorMessage, setErrorMessage] = useState('');
  const [result, setResult] = useState<CardDetectionResult | null>(null);
  const [captureSource, setCaptureSource] = useState('');

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
  }, []);

  useEffect(() => {
    window.addEventListener('pagehide', stopCamera);
    return () => {
      window.removeEventListener('pagehide', stopCamera);
      stopCamera();
    };
  }, [stopCamera]);

  const startCamera = async () => {
    setErrorMessage('');
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('ライブカメラにはHTTPS接続が必要です。');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 3840 },
          height: { ideal: 2160 },
        },
      });
      streamRef.current = stream;
      if (!videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setCameraActive(true);
      setMessage('名刺が画面内に収まったら「この状態を高解像度で抽出」を押してください。');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'カメラを開始できません');
    }
  };

  const videoFrame = async (): Promise<Blob> => {
    const video = videoRef.current;
    if (!video?.videoWidth || !video.videoHeight) {
      throw new Error('カメラ映像の準備中です');
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    if (!context) {
      throw new Error('カメラ画像を取得できません');
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvasBlob(canvas);
  };

  const analyze = async (blob: Blob, source: string) => {
    setBusy(true);
    setErrorMessage('');
    setResult(null);
    setMessage('高解像度画像をBCMan WebAPIで検出しています…');
    try {
      if (!['image/jpeg', 'image/png'].includes(blob.type)) {
        throw new Error('JPEGまたはPNG画像を取得できませんでした');
      }
      const document = await detectCardRectangles(blob, true);
      const canvas = resultCanvasRef.current;
      if (!canvas) {
        throw new Error('結果表示領域を作成できません');
      }
      await renderResult(canvas, blob, document);
      setResult(document);
      setCaptureSource(source);
      const usedFallback = document.cards.some((card) => card.strategy === 'full_frame_fallback');
      setMessage(
        document.card_count === 0
          ? document.candidate_count > 0
            ? `幾何候補${document.candidate_count}件は、名刺全体ではないと判定されました（${document.elapsed_ms.toFixed(0)}ms）。`
            : `幾何候補を検出できませんでした（${document.elapsed_ms.toFixed(0)}ms）。`
          : usedFallback
          ? `輪郭を検出できなかったため、画像全体を仮の1枚として表示しました（${document.elapsed_ms.toFixed(0)}ms）。`
          : `${document.card_count}枚を${document.elapsed_ms.toFixed(0)}msで検出しました。`,
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '矩形検出に失敗しました');
      setMessage('検出できませんでした。');
    } finally {
      setBusy(false);
    }
  };

  const captureHighResolution = async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) {
      setErrorMessage('先にライブカメラを開始してください。');
      return;
    }
    try {
      const ImageCaptureApi = (window as Window & { ImageCapture?: ImageCaptureConstructor }).ImageCapture;
      if (ImageCaptureApi) {
        try {
          await analyze(await new ImageCaptureApi(track).takePhoto(), 'カメラ静止画');
          return;
        } catch (error) {
          if (!streamRef.current) {
            throw error;
          }
        }
      }
      await analyze(await videoFrame(), '動画フレーム（静止画API非対応）');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '静止画を取得できません');
    }
  };

  const handlePhoto = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) {
      void analyze(file, '写真撮影・ファイル選択');
    }
  };

  const usedFallback = result?.cards.some((card) => card.strategy === 'full_frame_fallback') ?? false;

  return (
    <div className="screen mobile-lab">
      <div className="mobile-lab__heading">
        <button type="button" className="button button--ghost" onClick={onClose}>撮影画面へ戻る</button>
        <span className="mobile-lab__badge">非保存テスト</span>
      </div>

      <div className="hero">
        <div className="hero__icon" aria-hidden="true">🎥</div>
        <h2 className="hero__title">動画から矩形検出</h2>
        <p className="hero__note">ボタンを押した瞬間の1枚だけをWebAPIへ送り、輪郭と名刺らしさの両方を判定します。画像や切り抜きは保存しません。</p>
      </div>

      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      <p className="mobile-lab__status" aria-live="polite">{message}</p>

      <div className="mobile-lab__video-stage">
        <video ref={videoRef} autoPlay muted playsInline />
        <div className="mobile-lab__guide" aria-hidden="true" />
        {!cameraActive && <span className="mobile-lab__video-placeholder">カメラ停止中</span>}
      </div>

      <div className="mobile-lab__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={cameraActive || busy}
          onClick={() => void startCamera()}
        >
          ライブカメラを開始
        </button>
        <button
          type="button"
          className="button button--ghost"
          disabled={!cameraActive || busy}
          onClick={stopCamera}
        >
          停止
        </button>
      </div>

      <button
        type="button"
        className="button button--primary button--xl"
        disabled={!cameraActive || busy}
        onClick={() => void captureHighResolution()}
      >
        {busy ? 'WebAPIで検出中…' : 'この状態を高解像度で抽出'}
      </button>

      <input
        ref={cameraInputRef}
        className="hidden-input"
        type="file"
        accept="image/jpeg,image/png"
        capture="environment"
        onChange={handlePhoto}
      />
      <button
        type="button"
        className="button button--ghost"
        disabled={busy}
        onClick={() => cameraInputRef.current?.click()}
      >
        高解像度の写真だけで試す
      </button>

      <p className="hint">
        Android Chromeでは静止画APIを優先します。非対応端末は動画解像度になるため、結果の取得元とサイズを確認してください。
      </p>

      <section className="mobile-lab__result">
        <div className="mobile-lab__result-title">
          <h3>検出結果</h3>
          <span className={result && result.card_count > 0 && !usedFallback ? 'mobile-lab__badge mobile-lab__badge--ready' : 'mobile-lab__badge'}>
            {result ? (usedFallback ? '仮矩形' : `${result.card_count}枚`) : '未実行'}
          </span>
        </div>
        <canvas ref={resultCanvasRef} className="mobile-lab__result-canvas" hidden={!result} />
        {result && (
          <>
            <p className="hint">
              {captureSource}・{result.source_size.width}×{result.source_size.height}px・候補{result.candidate_count}件
              {result.semantic_model ? `・${result.semantic_model}` : ''}
            </p>
            <ul className="mobile-lab__detections">
              {result.cards.map((card) => (
                <li key={card.index}>
                  #{card.index} {card.strategy}・geometry {card.confidence.toFixed(3)}
                  {card.semantic_confidence !== undefined ? `・cardness ${card.semantic_confidence.toFixed(3)}` : ''}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
