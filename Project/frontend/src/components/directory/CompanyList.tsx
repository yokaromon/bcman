import { useCallback, useEffect, useState } from 'react';
import { fetchCompanies, type CompanySummary } from '../../api';
import { CompanyDetail } from './CompanyDetail';

function formatDate(value: string | null): string {
  if (!value) return '未入力';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

export function CompanyList() {
  const [companies, setCompanies] = useState<CompanySummary[]>([]);
  const [openCompanyId, setOpenCompanyId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      setCompanies(await fetchCompanies());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '企業一覧を読み込めませんでした');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (openCompanyId) {
    return (
      <CompanyDetail
        companyId={openCompanyId}
        onBack={() => {
          setOpenCompanyId(null);
          void load();
        }}
      />
    );
  }

  return (
    <div className="screen">
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {loading && <p className="hint">読み込んでいます…</p>}
      {!loading && !errorMessage && companies.length === 0 && <p className="hint">まだ企業がありません。</p>}
      <ul className="status-list">
        {companies.map((company) => (
          <li key={company.id}>
            <button type="button" className="row-button" onClick={() => setOpenCompanyId(company.id)}>
              <span>
                <strong>{company.display_name ?? '（会社名未入力）'}</strong>
              </span>
              <span className="row-button__meta">
                人物 {company.person_count}名
                <br />
                {formatDate(company.latest_exchanged_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
