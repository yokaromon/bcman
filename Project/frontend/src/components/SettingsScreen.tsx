import { useState } from 'react';
import { type Me } from '../api';
import { AdminScreen } from './AdminScreen';
import { ProviderScreen } from './ProviderScreen';

type Section = 'admin' | 'provider';

/**
 * 「管理」と「会社」をまとめた入口。役割の組み合わせに関わらずタブ数の増加を
 * ここで吸収する（撮影・台帳・名鑑・設定の4つで頭打ちにする）。
 *
 * 大多数の組織管理者はセクションが1つしか無いので、その場合は切り替えUIごと
 * 隠して中身を直接出す。ほぼ誰も使わないボタンを常時出す理由が無いため。
 */
export function SettingsScreen({ user }: { user: Me }) {
  const sections: Section[] = [
    ...(user.role === 'admin' ? (['admin'] as const) : []),
    ...(user.is_provider_operator ? (['provider'] as const) : []),
  ];
  const [section, setSection] = useState<Section>(sections[0] ?? 'admin');

  if (sections.length === 0) {
    return null;
  }

  return (
    <div>
      {sections.length > 1 && (
        <div className="action-bar">
          <button
            type="button"
            className={section === 'admin' ? 'button button--primary' : 'button button--ghost'}
            onClick={() => setSection('admin')}
          >
            利用者管理
          </button>
          <button
            type="button"
            className={section === 'provider' ? 'button button--primary' : 'button button--ghost'}
            onClick={() => setSection('provider')}
          >
            会社管理
          </button>
        </div>
      )}

      {section === 'admin' && sections.includes('admin') && <AdminScreen user={user} />}
      {section === 'provider' && sections.includes('provider') && <ProviderScreen />}
    </div>
  );
}
