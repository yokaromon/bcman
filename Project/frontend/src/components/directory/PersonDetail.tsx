import { useEffect, useState } from 'react';
import { fetchPerson, splitPersonContact, type PersonDetail as PersonDetailData } from '../../api';
import { ConfirmButton } from '../ConfirmButton';

function formatDate(value: string | null): string {
  if (!value) return '未入力';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

export function PersonDetail({ personId, onBack }: { personId: string; onBack: () => void }) {
  const [detail, setDetail] = useState<PersonDetailData | null>(null);
  const [errorMessage, setErrorMessage] = useState('');

  const load = async () => {
    setErrorMessage('');
    try {
      setDetail(await fetchPerson(personId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '人物を読み込めませんでした');
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personId]);

  const split = async (contactId: string) => {
    await splitPersonContact(personId, contactId);
    await load();
  };

  return (
    <div className="screen">
      <button type="button" className="back-link" onClick={onBack}>
        ← 人物一覧へ
      </button>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {!detail ? (
        <p className="hint">読み込んでいます…</p>
      ) : (
        <>
          <h2 className="screen__title">{detail.display_name ?? '（氏名未入力）'}</h2>
          <p className="hint">{detail.display_company ?? '所属不明'}</p>
          <ul className="status-list">
            {detail.touch_history.map((entry) => (
              <li key={entry.contact_id} className="status-list__row">
                <span>
                  <strong>{formatDate(entry.exchanged_at)}</strong>
                  <br />
                  {entry.company_name ?? '会社名なし'}
                  {entry.department ? ` / ${entry.department}` : ''}
                  {entry.position ? ` / ${entry.position}` : ''}
                  <br />
                  登録者: {entry.card_owner?.name ?? '未設定'}
                </span>
                {detail.touch_history.length > 1 && (
                  <ConfirmButton
                    label="別人物として分離"
                    message="この接点だけを別の人物として切り離します。"
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
