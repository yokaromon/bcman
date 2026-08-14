import { useEffect, useState } from 'react';
import { fetchCompany, splitCompanyContact, type CompanyDetail as CompanyDetailData } from '../../api';
import { ConfirmButton } from '../ConfirmButton';

function formatDate(value: string | null): string {
  if (!value) return '未入力';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

export function CompanyDetail({ companyId, onBack }: { companyId: string; onBack: () => void }) {
  const [detail, setDetail] = useState<CompanyDetailData | null>(null);
  const [errorMessage, setErrorMessage] = useState('');

  const load = async () => {
    setErrorMessage('');
    try {
      setDetail(await fetchCompany(companyId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '企業を読み込めませんでした');
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const split = async (contactId: string) => {
    await splitCompanyContact(companyId, contactId);
    await load();
  };

  return (
    <div className="screen">
      <button type="button" className="back-link" onClick={onBack}>
        ← 企業一覧へ
      </button>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {!detail ? (
        <p className="hint">読み込んでいます…</p>
      ) : (
        <>
          <h2 className="screen__title">{detail.display_name ?? '（会社名未入力）'}</h2>
          <ul className="status-list">
            {detail.touch_history.map((entry) => (
              <li key={entry.contact_id} className="status-list__row">
                <span>
                  <strong>{entry.person_name ?? '（氏名未入力）'}</strong>
                  {entry.department ? ` / ${entry.department}` : ''}
                  {entry.position ? ` / ${entry.position}` : ''}
                  <br />
                  {formatDate(entry.exchanged_at)} ・ 登録者: {entry.card_owner?.name ?? '未設定'}
                </span>
                {detail.touch_history.length > 1 && (
                  <ConfirmButton
                    label="別企業として分離"
                    message="この接点だけを別の企業として切り離します。"
                    confirmLabel="分離する"
                    onConfirm={() => split(entry.contact_id)}
                  />
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
