import { useEffect, useState } from 'react';
import { fetchMe, logout, type Me } from './api';
import { CaptureFlow } from './CaptureFlow';
import { AdminScreen } from './components/AdminScreen';
import { DirectoryScreen } from './components/directory/DirectoryScreen';
import { InstallAppButton } from './components/InstallAppButton';
import { LEDGER_TAB_LABEL, LedgerScreen } from './components/ledger/LedgerScreen';
import { LoginScreen } from './components/LoginScreen';

type Tab = 'capture' | 'ledger' | 'directory' | 'admin';

export function App() {
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
    void loadMe();
  }, []);

  const openTab = (next: Tab) => {
    setTab(next);
    setOpenCount((count) => count + 1);
  };

  const handleLogout = async () => {
    await logout().catch(() => {});
    setMe(null);
    setTab('capture');
  };

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
        {tab === 'admin' && me.role === 'admin' && <AdminScreen key={openCount} user={me} />}
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
        {me.role === 'admin' && (
          <button
            type="button"
            className={tab === 'admin' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
            onClick={() => openTab('admin')}
          >
            <span aria-hidden="true">👤</span>
            管理
          </button>
        )}
      </nav>
    </div>
  );
}
