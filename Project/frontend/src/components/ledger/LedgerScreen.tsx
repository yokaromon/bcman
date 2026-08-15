import { useState } from 'react';
import { type Me } from '../../api';
import { HistoryScreen } from '../HistoryScreen';
import { ContactSearch } from './ContactSearch';

type SubTab = 'search' | 'photos';

/** タブバーと見出しで同じ語を使うための一箇所。呼び名を変えるならここだけ直す。 */
export const LEDGER_TAB_LABEL = '台帳';

/**
 * 台帳。登録済み名刺を引く「検索」と、撮影単位でたどる「写真から」を1つのタブにまとめる。
 * どちらも Business Card Management の文脈で、名鑑（人物・会社）とは別物。
 */
export function LedgerScreen({ user }: { user: Me | null }) {
  const [subTab, setSubTab] = useState<SubTab>('search');

  return (
    <div className="screen">
      <h2 className="screen__title">{LEDGER_TAB_LABEL}</h2>
      <div className="action-bar">
        <button
          type="button"
          className={subTab === 'search' ? 'button button--primary' : 'button button--ghost'}
          onClick={() => setSubTab('search')}
        >
          検索
        </button>
        <button
          type="button"
          className={subTab === 'photos' ? 'button button--primary' : 'button button--ghost'}
          onClick={() => setSubTab('photos')}
        >
          写真から
        </button>
      </div>

      {subTab === 'search' ? <ContactSearch /> : <HistoryScreen user={user} />}
    </div>
  );
}
