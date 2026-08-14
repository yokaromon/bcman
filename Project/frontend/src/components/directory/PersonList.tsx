import { useCallback, useEffect, useState } from 'react';
import { fetchPersons, type PersonSummary } from '../../api';
import { PersonDetail } from './PersonDetail';

function formatDate(value: string | null): string {
  if (!value) return '未入力';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

export function PersonList() {
  const [persons, setPersons] = useState<PersonSummary[]>([]);
  const [openPersonId, setOpenPersonId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      setPersons(await fetchPersons());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '人物一覧を読み込めませんでした');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (openPersonId) {
    return (
      <PersonDetail
        personId={openPersonId}
        onBack={() => {
          setOpenPersonId(null);
          void load();
        }}
      />
    );
  }

  return (
    <div className="screen">
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {loading && <p className="hint">読み込んでいます…</p>}
      {!loading && !errorMessage && persons.length === 0 && <p className="hint">まだ人物がいません。</p>}
      <ul className="status-list">
        {persons.map((person) => (
          <li key={person.id}>
            <button type="button" className="row-button" onClick={() => setOpenPersonId(person.id)}>
              <span>
                <strong>{person.display_name ?? '（氏名未入力）'}</strong>
                <br />
                {person.display_company ?? '所属不明'}
              </span>
              <span className="row-button__meta">
                接点 {person.contact_count}件
                <br />
                {formatDate(person.latest_exchanged_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
