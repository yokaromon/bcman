import { useEffect, useState } from 'react';
import { APP_BASE, fetchMe, logout, type Me } from './api';
import { CaptureFlow } from './CaptureFlow';
import { DirectoryScreen } from './components/directory/DirectoryScreen';
import { InstallAppButton } from './components/InstallAppButton';
import { InviteScreen } from './components/InviteScreen';
import { LEDGER_TAB_LABEL, LedgerScreen } from './components/ledger/LedgerScreen';
import { LoginScreen } from './components/LoginScreen';
import { SettingsScreen } from './components/SettingsScreen';

type Tab = 'capture' | 'ledger' | 'directory' | 'settings';

const INVITE_PREFIX = `${APP_BASE}/invite/`;

/** 招待リンクで開かれたかを判定する。API のパスへ埋める前に形を確かめる。 */
function readInviteToken(): string | null {
  const path = window.location.pathname;
  if (!path.startsWith(INVITE_PREFIX)) {
    return null;
  }
  const token = path.slice(INVITE_PREFIX.length);
  return /^[A-Za-z0-9_-]{20,64}$/.test(token) ? token : null;
}

export function App() {
  // 初期化子で同期的に読む。useEffect にすると初回描画でログイン画面が一瞬見える
  const [inviteToken, setInviteToken] = useState(readInviteToken);
  const [me, setMe] = useState<Me | null>(null);
  const [checkedLogin, setCheckedLogin] = useState(false);
  const [tab, setTab] = useState<Tab>('capture');
  // タブを押した回数。key に使い、開いているタブを押し直したときも作り直させる。
  // 同じタブに setTab しても state が変わらず、途中の画面に留まってしまうため。
  const [openCount, setOpenCount] = useState(0);

  const loadMe = async () => {
    try {
      setMe(await fetchMe());
    } catch {
      // 401（未ログイン）に限らず、失敗した時点ではログイン画面を出す
      setMe(null);
    } finally {
      setCheckedLogin(true);
    }
  };

  useEffect(() => {
    // 招待ページでは確実に401になるので呼ばない。完了時に onCompleted 側で読み直す
    if (!inviteToken) {
      void loadMe();
    }
  }, [inviteToken]);

  const openTab = (next: Tab) => {
    setTab(next);
    setOpenCount((count) => count + 1);
  };

  const handleLogout = async () => {
    await logout().catch(() => {});
    setMe(null);
    setTab('capture');
  };

  // 認証ゲートより手前に置く。共用端末で他人がログイン中でも、招待された本人の画面を出す
  if (inviteToken) {
    return (
      <div className="app">
        <main className="app__main">
          <InviteScreen
            token={inviteToken}
            onCompleted={() => {
              setInviteToken(null);
              void loadMe();
            }}
          />
        </main>
      </div>
    );
  }

  if (!checkedLogin) {
    return null;
  }

  if (!me) {
    return (
      <div className="app">
        <main className="app__main">
          <LoginScreen onLoggedIn={() => void loadMe()} />
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__header-group">
          <span className="app__brand">BCMan</span>
          <InstallAppButton />
        </div>
        <div className="app__header-group">
          <span className="hint">{me.name}</span>
          <button type="button" className="button button--ghost" onClick={() => void handleLogout()}>
            ログアウト
          </button>
        </div>
      </header>

      <main className="app__main">
        {tab === 'capture' && <CaptureFlow key={openCount} user={me} />}
        {tab === 'ledger' && <LedgerScreen key={openCount} user={me} />}
        {tab === 'directory' && <DirectoryScreen key={openCount} user={me} />}
        {tab === 'settings' && (me.role === 'admin' || me.is_provider_operator) && (
          <SettingsScreen key={openCount} user={me} />
        )}
      </main>

      <nav className="tabbar">
        <button
          type="button"
          className={tab === 'capture' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
          onClick={() => openTab('capture')}
        >
          <span aria-hidden="true">📷</span>
          撮影
        </button>
        <button
          type="button"
          className={tab === 'ledger' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
          onClick={() => openTab('ledger')}
        >
          <span aria-hidden="true">🗂</span>
          {LEDGER_TAB_LABEL}
        </button>
        <button
          type="button"
          className={tab === 'directory' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
          onClick={() => openTab('directory')}
        >
          <span aria-hidden="true">📇</span>
          名鑑
        </button>
        {(me.role === 'admin' || me.is_provider_operator) && (
          <button
            type="button"
            className={tab === 'settings' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
            onClick={() => openTab('settings')}
          >
            <span aria-hidden="true">⚙️</span>
            設定
          </button>
        )}
      </nav>
    </div>
  );
}
