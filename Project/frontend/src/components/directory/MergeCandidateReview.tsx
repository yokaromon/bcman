import { useCallback, useEffect, useState } from 'react';
import { acceptMergeCandidate, dismissMergeCandidate, fetchMergeCandidates, type MergeCandidate } from '../../api';

export function MergeCandidateReview({ onChanged }: { onChanged?: () => void }) {
  const [candidates, setCandidates] = useState<MergeCandidate[]>([]);
  const [busyId, setBusyId] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      setCandidates(await fetchMergeCandidates());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '統合候補を読み込めませんでした');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (id: string, action: (id: string) => Promise<{ status: string }>) => {
    setBusyId(id);
    try {
      await action(id);
      await load();
      onChanged?.();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '処理に失敗しました');
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="screen">
      <h2 className="screen__title">統合候補</h2>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {loading && <p className="hint">読み込んでいます…</p>}
      {!loading && !errorMessage && candidates.length === 0 && <p className="hint">統合候補はありません。</p>}
      <ul className="candidate-list">
        {candidates.map((candidate) => (
          <li key={candidate.id} className="candidate">
            <span className="candidate__body">
              {candidate.kind === 'person' ? candidate.contact_person_name : candidate.contact_company_name}
              <small>
                {candidate.signal_label} ・ {candidate.target_display_name ?? '（既存の記録）'} と同じ{candidate.kind === 'person' ? '人物' : '企業'}かもしれません
              </small>
            </span>
            <button
              type="button"
              className="button button--ghost"
              disabled={busyId === candidate.id}
              onClick={() => void resolve(candidate.id, dismissMergeCandidate)}
            >
              別物
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={busyId === candidate.id}
              onClick={() => void resolve(candidate.id, acceptMergeCandidate)}
            >
              統合する
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
