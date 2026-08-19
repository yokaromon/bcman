import { useState } from 'react';
import { type IssuedInvitation } from '../api';

function formatExpiry(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/**
 * 発行した招待を相手へ渡すための表示。
 * このリンクは24時間、そのアカウントを受け取れてしまうので、対面で読ませるのが前提。
 */
export function InvitationHandover({ invitation, onDismiss }: { invitation: IssuedInvitation; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(invitation.invitation_url);
      setCopied(true);
    } catch {
      // クリップボードが使えない環境ではURLを直接読んでもらう
    }
  };

  return (
    <div className="alert alert--warn">
      <p>
        <strong>{invitation.name}</strong>（ID: {invitation.username}）の招待です。
        本人にこのQRを読んでもらうと、その場でパスワードと認証アプリを設定できます。
      </p>
      <img className="invitation__qr" src={invitation.qr_data_url} alt="招待用QRコード" />
      <p className="hint">
        {formatExpiry(invitation.expires_at)} まで有効。一度使うと無効になります。
        このリンクを持っている人は誰でもこのアカウントを受け取れるので、本人へ直接渡してください。
      </p>
      <pre className="ocr__text">{invitation.invitation_url}</pre>
      <div className="action-bar">
        <button type="button" className="button button--ghost" onClick={() => void copy()}>
          {copied ? 'コピーしました' : 'リンクをコピー'}
        </button>
        <button type="button" className="button button--ghost" onClick={onDismiss}>
          閉じる
        </button>
      </div>
    </div>
  );
}
