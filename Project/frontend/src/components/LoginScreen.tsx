import { useState, type FormEvent } from 'react';
import { login, verifyTotp } from '../api';

type Step = 'password' | 'totp';

export function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [step, setStep] = useState<Step>('password');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setErrorMessage('');
    try {
      const result = await login(username, password);
      if (result.status === 'totp_required') {
        setStep('totp');
      } else {
        onLoggedIn();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'ログインできませんでした');
    } finally {
      setBusy(false);
    }
  };

  const submitTotp = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setErrorMessage('');
    try {
      await verifyTotp(code);
      onLoggedIn();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'コードが確認できませんでした');
    } finally {
      setBusy(false);
    }
  };

  if (step === 'totp') {
    return (
      <div className="screen screen--center">
        <h2 className="hero__title">認証コードの入力</h2>
        <p className="hero__note">この端末は未登録のため、認証アプリに表示される6桁のコードを入力してください。</p>
        <form className="screen--form" onSubmit={submitTotp}>
          <label className="field">
            <span className="field__label">認証コード</span>
            <input
              className="field__input"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              autoFocus
            />
          </label>
          {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
          <button type="submit" className="button button--primary button--xl" disabled={busy}>
            {busy ? '確認しています…' : '確認'}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="screen screen--center">
      <div className="hero__icon" aria-hidden="true">🔒</div>
      <h2 className="hero__title">ログイン</h2>
      <form className="screen--form" onSubmit={submitPassword}>
        <label className="field">
          <span className="field__label">ID</span>
          <input
            className="field__input"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoFocus
          />
        </label>
        <label className="field">
          <span className="field__label">パスワード</span>
          <input
            className="field__input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
        <button type="submit" className="button button--primary button--xl" disabled={busy}>
          {busy ? 'ログインしています…' : 'ログイン'}
        </button>
      </form>
    </div>
  );
}
