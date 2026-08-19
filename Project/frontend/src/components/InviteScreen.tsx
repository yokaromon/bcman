import { useEffect, useState, type FormEvent } from 'react';
import { completeInvitation, fetchInvitation, type InvitationDetail } from '../api';

const MINIMUM_PASSWORD_LENGTH = 12;

/** otpauth:// URI から手入力用の秘密鍵を取り出す。QRを読めない端末のための逃げ道。 */
export function extractSecret(provisioningUri: string): string {
  return /[?&]secret=([^&]+)/.exec(provisioningUri)?.[1] ?? '';
}

/**
 * 招待を受け取る画面。認証不要で開ける。
 *
 * トークンは props で受け取り、`window.location` は二度と読まない。
 * マウント直後にURLからトークンを消すので、読み直すと空になる。
 */
export function InviteScreen({ token, onCompleted }: { token: string; onCompleted: () => void }) {
  const [detail, setDetail] = useState<InvitationDetail | null>(null);
  const [loadError, setLoadError] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // 24時間有効な保持型資格情報なので、アドレスバーとこの履歴項目から消す。
  // pushState だと戻るボタン1回で復活してしまう。
  useEffect(() => {
    window.history.replaceState(null, '', '/bcman/invite');
  }, []);

  useEffect(() => {
    fetchInvitation(token)
      .then(setDetail)
      .catch(() => setLoadError('この招待は使えません。期限切れか、既に使われています。発行者に再発行を依頼してください。'));
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < MINIMUM_PASSWORD_LENGTH) {
      setErrorMessage(`パスワードは${MINIMUM_PASSWORD_LENGTH}文字以上にしてください`);
      return;
    }
    if (password !== confirmation) {
      setErrorMessage('確認用のパスワードが一致しません');
      return;
    }
    setBusy(true);
    setErrorMessage('');
    try {
      await completeInvitation(token, password, code);
      onCompleted();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '設定できませんでした');
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <div className="screen screen--center">
        <div className="hero__icon" aria-hidden="true">⌛</div>
        <h2 className="hero__title">招待が使えません</h2>
        <p className="alert alert--error">{loadError}</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="screen screen--center">
        <div className="spinner" />
        <p className="lead">読み込んでいます…</p>
      </div>
    );
  }

  return (
    <div className="screen screen--center">
      <div className="hero__icon" aria-hidden="true">🔑</div>
      <h2 className="hero__title">アカウントの設定</h2>

      <div className="alert alert--info">
        <p>
          <strong>{detail.organization_name}</strong> の <strong>{detail.name}</strong> さんとして設定します。
        </p>
        <p className="hint">次回からのログインには、この2つが必要です。控えておいてください。</p>
        <ul className="invitation__identity">
          <li>会社コード: <strong>{detail.company_code}</strong></li>
          <li>ID: <strong>{detail.username}</strong></li>
        </ul>
      </div>

      <h3 className="screen__title">1. 認証アプリに登録</h3>
      <p className="hint">
        Google Authenticator などでこのQRを読み取ってください。
        オフィス以外から・新しい端末でログインするとき、ここに出る6桁のコードを使います。
      </p>
      <img className="invitation__qr" src={detail.totp_qr_data_url} alt="認証アプリ登録用QRコード" />
      <p className="hint">QRを読めないときは、次のキーを手入力してください。</p>
      <pre className="ocr__text">{extractSecret(detail.otpauth_uri)}</pre>

      <h3 className="screen__title">2. パスワードを決めて確定</h3>
      <form className="screen--form" onSubmit={submit}>
        <label className="field">
          <span className="field__label">パスワード（{MINIMUM_PASSWORD_LENGTH}文字以上）</span>
          <input
            className="field__input"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">パスワード（確認）</span>
          <input
            className="field__input"
            type="password"
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">認証アプリの6桁コード</span>
          <input
            className="field__input"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <p className="hint">
          登録できているか、その場で確かめるために入力してもらっています。
          ここを通さないと、次のログインで初めて登録の失敗に気づくことになります。
        </p>
        {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
        <button type="submit" className="button button--primary button--xl" disabled={busy}>
          {busy ? '設定しています…' : 'この内容で始める'}
        </button>
      </form>
    </div>
  );
}
