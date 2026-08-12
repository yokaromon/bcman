import { useState, type ReactNode } from 'react';

type Props = {
  src: string;
  alt: string;
  title: string;
  meta: ReactNode;
  onClick: () => void;
};

/**
 * 一覧の1件分。画像を帯で見せ、その下に見出しと状態を置く。
 * 元画像が消えている古いデータでもサムネイルが 404 になるだけなので、
 * 画像の読み込み失敗は行ごと壊さずプレースホルダに差し替える。
 */
export function MediaCard({ src, alt, title, meta, onClick }: Props) {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <button type="button" className="media-card" onClick={onClick}>
      {imageFailed ? (
        <span className="media-card__image media-card__image--missing">画像がありません</span>
      ) : (
        <img
          className="media-card__image"
          src={src}
          alt={alt}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      )}
      <span className="media-card__body">
        <span className="media-card__title">{title}</span>
        <span className="media-card__meta">{meta}</span>
      </span>
    </button>
  );
}
