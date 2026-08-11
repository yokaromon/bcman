import { useEffect, useState } from 'react';
import { fetchBootstrap, type User } from './api';
import { CaptureFlow } from './CaptureFlow';
import { HistoryScreen } from './components/HistoryScreen';

const STORED_USER_KEY = 'bcman.userId';

type Tab = 'capture' | 'history';

/** 撮影できるのは組織とグループを持つ利用者だけ（system_admin は不可）。 */
function pickDefaultUser(users: User[], storedId: string | null): User | null {
  const stored = users.find((user) => user.id === storedId);
  if (stored) {
    return stored;
  }
  const uploader = users.find((user) => user.organization_id && user.group_id);
  return uploader ?? users[0] ?? null;
}

export function App() {
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [tab, setTab] = useState<Tab>('capture');
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        const data = await fetchBootstrap();
        setUsers(data.users);
        setCurrentUser(pickDefaultUser(data.users, localStorage.getItem(STORED_USER_KEY)));
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : '初期データを取得できませんでした');
      }
    };
    void load();
  }, []);

  const changeUser = (userId: string) => {
    const selected = users.find((user) => user.id === userId) ?? null;
    setCurrentUser(selected);
    if (selected) {
      localStorage.setItem(STORED_USER_KEY, selected.id);
    }
  };

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__brand">BCMan</span>
        <select
          className="app__user"
          aria-label="利用者"
          value={currentUser?.id ?? ''}
          onChange={(event) => changeUser(event.target.value)}
        >
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
      </header>

      <main className="app__main">
        {loadError && <p className="alert alert--error">{loadError}</p>}
        {tab === 'capture' && <CaptureFlow user={currentUser} />}
        {tab === 'history' && <HistoryScreen user={currentUser} />}
      </main>

      <nav className="tabbar">
        <button
          type="button"
          className={tab === 'capture' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
          onClick={() => setTab('capture')}
        >
          <span aria-hidden="true">📷</span>
          撮影
        </button>
        <button
          type="button"
          className={tab === 'history' ? 'tabbar__item tabbar__item--active' : 'tabbar__item'}
          onClick={() => setTab('history')}
        >
          <span aria-hidden="true">🗂</span>
          履歴
        </button>
      </nav>
    </div>
  );
}
