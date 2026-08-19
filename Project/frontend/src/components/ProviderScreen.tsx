import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  createProviderOrganization,
  fetchProviderOrganizations,
  fetchProviderOrgUsers,
  providerReinvite,
  type IssuedInvitation,
  type OrgUser,
  type ProviderOrganization,
} from '../api';
import { InvitationHandover } from './InvitationHandover';

const EMPTY_FORM = {
  name: '',
  code: '',
  sharing_mode: 'isolated',
  group_name: '一般',
  admin_username: 'admin',
  admin_name: '',
};

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ja-JP');
}

/** 会社の中の利用者一覧。ロックアウトした管理者を招待し直すために開く。 */
function OrganizationUsers({ org, onIssued }: { org: ProviderOrganization; onIssued: (invitation: IssuedInvitation) => void }) {
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    fetchProviderOrgUsers(org.id)
      .then(setUsers)
      .catch((error) => setErrorMessage(error instanceof Error ? error.message : '読み込めませんでした'));
  }, [org.id]);

  const reinvite = async (user: OrgUser) => {
    setErrorMessage('');
    try {
      onIssued(await providerReinvite(org.id, user.id));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '招待できませんでした');
    }
  };

  return (
    <div>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      <ul className="media-list">
        {users.map((user) => (
          <li key={user.id} className="hint">
            {user.name}（{user.username} / {user.role === 'admin' ? '管理者' : '一般'}
            {user.activated ? '' : ' / 招待中'}）
            <button type="button" className="button button--ghost" onClick={() => void reinvite(user)}>
              招待し直す
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 運営者の画面。会社を作り、招待を渡し、ロックアウトを戻すためだけのもの。
 * 各社の名刺・連絡先はここからは一切見えない（docs/identity/adr/0002）。
 */
export function ProviderScreen() {
  const [organizations, setOrganizations] = useState<ProviderOrganization[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);
  const [openOrgId, setOpenOrgId] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const load = useCallback(async () => {
    try {
      setOrganizations(await fetchProviderOrganizations());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '読み込めませんでした');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setErrorMessage('');
    try {
      setIssued(await createProviderOrganization(form));
      setForm(EMPTY_FORM);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '作成できませんでした');
    } finally {
      setBusy(false);
    }
  };

  const update = (key: keyof typeof EMPTY_FORM) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="screen">
      <h2 className="screen__title">会社の管理（運営者）</h2>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {issued && <InvitationHandover invitation={issued} onDismiss={() => setIssued(null)} />}

      <h3 className="screen__title">会社を追加</h3>
      <form className="screen--form" onSubmit={submit}>
        <label className="field">
          <span className="field__label">会社名</span>
          <input className="field__input" type="text" value={form.name} onChange={update('name')} />
        </label>
        <label className="field">
          <span className="field__label">会社コード（英小文字・数字・ハイフン、3〜20文字）</span>
          <input
            className="field__input"
            type="text"
            autoCapitalize="none"
            autoCorrect="off"
            value={form.code}
            onChange={update('code')}
          />
        </label>
        <p className="hint">
          この会社の全員がログイン時に打つ文字列です。<strong>後から変更できません</strong>
          （変えるとその会社の全員がログインできなくなるため）。
        </p>
        <label className="field">
          <span className="field__label">共有モード</span>
          <select className="field__input" value={form.sharing_mode} onChange={update('sharing_mode')}>
            <option value="isolated">グループ内のみ共有</option>
            <option value="shared">会社全体で共有</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">初期グループ名</span>
          <input className="field__input" type="text" value={form.group_name} onChange={update('group_name')} />
        </label>
        <label className="field">
          <span className="field__label">管理者のログインID</span>
          <input
            className="field__input"
            type="text"
            autoCapitalize="none"
            value={form.admin_username}
            onChange={update('admin_username')}
          />
        </label>
        <label className="field">
          <span className="field__label">管理者の表示名</span>
          <input className="field__input" type="text" value={form.admin_name} onChange={update('admin_name')} />
        </label>
        <button type="submit" className="button button--primary" disabled={busy}>
          {busy ? '作成しています…' : '会社と管理者を作成'}
        </button>
      </form>

      <h3 className="screen__title">会社一覧</h3>
      <ul className="media-list">
        {organizations.map((org) => (
          <li key={org.id}>
            <div className="hint">
              <strong>{org.name}</strong>（コード: {org.code} / {org.user_count}人 / {formatDate(org.created_at)}）
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setOpenOrgId(openOrgId === org.id ? '' : org.id)}
              >
                {openOrgId === org.id ? '閉じる' : '利用者'}
              </button>
            </div>
            {openOrgId === org.id && <OrganizationUsers org={org} onIssued={setIssued} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
