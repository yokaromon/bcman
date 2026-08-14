import { useEffect, useState } from 'react';
import { fetchMergeCandidates, type Me } from '../../api';
import { CompanyList } from './CompanyList';
import { MergeCandidateReview } from './MergeCandidateReview';
import { PersonList } from './PersonList';

type SubTab = 'persons' | 'companies' | 'candidates';

export function DirectoryScreen({ user: _user }: { user: Me }) {
  const [subTab, setSubTab] = useState<SubTab>('persons');
  const [pendingCount, setPendingCount] = useState(0);

  const loadPendingCount = () => {
    fetchMergeCandidates()
      .then((candidates) => setPendingCount(candidates.length))
      .catch(() => {
        // バッジが更新できないだけなので、名鑑の閲覧自体は続けられる
      });
  };

  useEffect(() => {
    loadPendingCount();
  }, []);

  return (
    <div className="screen">
      <h2 className="screen__title">名鑑</h2>
      <div className="action-bar">
        <button
          type="button"
          className={subTab === 'persons' ? 'button button--primary' : 'button button--ghost'}
          onClick={() => setSubTab('persons')}
        >
          人物
        </button>
        <button
          type="button"
          className={subTab === 'companies' ? 'button button--primary' : 'button button--ghost'}
          onClick={() => setSubTab('companies')}
        >
          企業
        </button>
        <button
          type="button"
          className={subTab === 'candidates' ? 'button button--primary' : 'button button--ghost'}
          onClick={() => setSubTab('candidates')}
        >
          統合候補{pendingCount > 0 && <span className="badge badge--busy">{pendingCount}</span>}
        </button>
      </div>

      {subTab === 'persons' && <PersonList />}
      {subTab === 'companies' && <CompanyList />}
      {subTab === 'candidates' && <MergeCandidateReview onChanged={loadPendingCount} />}
    </div>
  );
}
