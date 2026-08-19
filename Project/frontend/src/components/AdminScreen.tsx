import { useCallback, useEffect, useState } from 'react';
import {
  createOrgGroup,
  createOrgUser,
  fetchAuditLogs,
  fetchOrgGroups,
  fetchOrgUsers,
  fetchUserDevices,
  reinviteUser,
  revokeDevice,
  unlockUser,
  type AuditEntry,
  type Group,
  type IssuedInvitation,
  type Me,
  type OrgUser,
  type Role,
  type TrustedDevice,
} from '../api';
import { InvitationHandover } from './InvitationHandover';

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function DeviceList({ orgId, userId }: { orgId: string; userId: string }) {
  const [devices, setDevices] = useState<TrustedDevice[]>([]);
  const [errorMessage, setErrorMessage] = useState('');

  const load = useCallback(async () => {
    try {
      setDevices(await fetchUserDevices(orgId, userId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '端末を読み込めませんでした');
    }
  }, [orgId, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async (deviceId: string) => {
    try {
      await revokeDevice(orgId, deviceId);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '端末を失効できませんでした');
    }
  };

  if (errorMessage) {
    return <p className="alert alert--error">{errorMessage}</p>;
  }
  if (devices.length === 0) {
    return <p className="hint">信頼済み端末はありません。</p>;
  }

  return (
    <ul className="media-list">
      {devices.map((device) => (
        <li key={device.id} className="field">
          <span className="field__label">{device.label || '(不明な端末)'}</span>
          <span className="hint">
            登録: {formatDate(device.created_at)} / 最終利用: {formatDate(device.last_used_at)} / 期限:{' '}
            {formatDate(device.expires_at)}
          </span>
          {device.revoked ? (
            <span className="hint">失効済み</span>
          ) : (
            <button type="button" className="button button--ghost" onClick={() => void revoke(device.id)}>
              この端末を即時失効
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function UserRow({ orgId, user, groups }: { orgId: string; user: OrgUser; groups: Group[] }) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);

  const groupNames = user.groups
    .map((id) => groups.find((group) => group.id === id)?.name ?? id)
    .join('、');

  /** パスワード忘れも認証アプリ紛失もこれ1つ。管理者が値を決めて伝える経路は無い。 */
  const runReinvite = async () => {
    setBusy('invite');
    setMessage('');
    try {
      setIssued(await reinviteUser(orgId, user.id));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '招待できませんでした');
    } finally {
      setBusy('');
    }
  };

  const runUnlock = async () => {
    setBusy('unlock');
    setMessage('');
    try {
      await unlockUser(orgId, user.id);
      setMessage('ロックを解除しました');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '解除に失敗しました');
    } finally {
      setBusy('');
    }
  };

  return (
    <li className="field">
      <div className="action-bar">
        <span>
          <strong>{user.name}</strong>（{user.username} / {user.role === 'admin' ? '管理者' : '一般'} / {groupNames || '未所属'}
          {user.activated ? '' : ' / 招待中'}）
        </span>
        <button type="button" className="button button--ghost" onClick={() => setExpanded((value) => !value)}>
          {expanded ? '閉じる' : '端末・操作'}
        </button>
      </div>

      {expanded && (
        <div className="review">
          {issued && <InvitationHandover invitation={issued} onDismiss={() => setIssued(null)} />}
          {message && <p className="alert alert--warn">{message}</p>}

          <p className="hint">
            パスワードを忘れた・認証アプリを失くしたときは「招待し直す」を押して、出たQRを本人に読んでもらってください。
            本人が自分で決め直すので、こちらでパスワードを決めて伝える必要はありません。
          </p>
          <div className="action-bar">
            <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={runReinvite}>
              招待し直す
            </button>
            <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={runUnlock}>
              ロック解除
            </button>
          </div>

          <h3 className="screen__title">信頼済み端末</h3>
          <DeviceList orgId={orgId} userId={user.id} />
        </div>
      )}
    </li>
  );
}

export function AdminScreen({ user }: { user: Me }) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [errorMessage, setErrorMessage] = useState('');
  const [newGroupName, setNewGroupName] = useState('');
  const [form, setForm] = useState({ username: '', name: '', role: 'member' as Role });
  const [formGroupIds, setFormGroupIds] = useState<string[]>([]);
  const [createdCredential, setCreatedCredential] = useState<IssuedInvitation | null>(null);

  const load = useCallback(async () => {
    try {
      const [orgGroups, orgUsers] = await Promise.all([fetchOrgGroups(user.organization_id), fetchOrgUsers(user.organization_id)]);
      setGroups(orgGroups);
      setUsers(orgUsers);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '読み込めませんでした');
    }
  }, [user.organization_id]);

  useEffect(() => {
    void load();
  }, [load]);

  const addGroup = async () => {
    if (!newGroupName.trim()) return;
    try {
      await createOrgGroup(user.organization_id, newGroupName.trim());
      setNewGroupName('');
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'グループを作成できませんでした');
    }
  };

  const toggleFormGroup = (groupId: string) => {
    setFormGroupIds((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  };

  const addUser = async () => {
    setErrorMessage('');
    if (formGroupIds.length === 0) {
      setErrorMessage('所属グループを1つ以上選んでください');
      return;
    }
    try {
      setCreatedCredential(await createOrgUser(user.organization_id, { ...form, group_ids: formGroupIds }));
      setForm({ username: '', name: '', role: 'member' });
      setFormGroupIds([]);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '利用者を作成できませんでした');
    }
  };

  return (
    <div className="screen">
      <h2 className="screen__title">ユーザ管理</h2>
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
      {createdCredential && (
        <InvitationHandover invitation={createdCredential} onDismiss={() => setCreatedCredential(null)} />
      )}

      <h3 className="screen__title">グループ</h3>
      <ul className="media-list">
        {groups.map((group) => (
          <li key={group.id} className="hint">
            {group.name}
          </li>
        ))}
      </ul>
      <div className="action-bar">
        <input
          className="field__input"
          placeholder="新しいグループ名"
          value={newGroupName}
          onChange={(event) => setNewGroupName(event.target.value)}
        />
        <button type="button" className="button button--ghost" onClick={() => void addGroup()}>
          追加
        </button>
      </div>

      <h3 className="screen__title">利用者を追加</h3>
      <p className="hint">
        作成すると招待用のQRが出ます。本人にそれを読んでもらうと、パスワードと認証アプリを自分で設定できます。
        こちらでパスワードを決めて伝える必要はありません。
      </p>
      <div className="fields">
        <label className="field">
          <span className="field__label">ID（ログインID）</span>
          <input
            className="field__input"
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field__label">表示名</span>
          <input
            className="field__input"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field__label">ロール</span>
          <select
            className="field__input"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
          >
            <option value="member">一般ユーザー</option>
            <option value="admin">管理者</option>
          </select>
        </label>
        <div className="field">
          <span className="field__label">所属グループ</span>
          {groups.map((group) => (
            <label key={group.id} className="field">
              <input
                type="checkbox"
                checked={formGroupIds.includes(group.id)}
                onChange={() => toggleFormGroup(group.id)}
              />{' '}
              {group.name}
            </label>
          ))}
        </div>
      </div>
      <button type="button" className="button button--primary" onClick={() => void addUser()}>
        利用者を作成
      </button>

      <h3 className="screen__title">利用者一覧</h3>
      <ul className="media-list">
        {users.map((orgUser) => (
          <UserRow key={orgUser.id} orgId={user.organization_id} user={orgUser} groups={groups} />
        ))}
      </ul>

      <AuditLogList orgId={user.organization_id} />
    </div>
  );
}

const AUDIT_LABELS: Record<string, string> = {
  invite: '招待を発行',
  provider_invite_user: '運営者が招待を発行',
  provider_create_organization: '運営者が会社を作成',
  invitation_completed: '招待を完了',
  delete: '削除',
  update: '更新',
};

/**
 * この組織に対して行われた操作の記録。
 * 運営者は資格情報を作り直せる以上、他社アカウントになりすませる。それを抑止できるのは
 * 事後に当事者が読めることだけなので、この一覧が無いと抑止が成立しない（docs/identity/adr/0002）。
 */
function AuditLogList({ orgId }: { orgId: string }) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    if (!open) return;
    fetchAuditLogs(orgId)
      .then(setEntries)
      .catch((error) => setErrorMessage(error instanceof Error ? error.message : '読み込めませんでした'));
  }, [open, orgId]);

  return (
    <div>
      <div className="action-bar">
        <h3 className="screen__title">操作の記録</h3>
        <button type="button" className="button button--ghost" onClick={() => setOpen((value) => !value)}>
          {open ? '閉じる' : '表示'}
        </button>
      </div>
      {open && (
        <>
          {errorMessage && <p className="alert alert--error">{errorMessage}</p>}
          {entries.length === 0 && !errorMessage && <p className="hint">記録はまだありません。</p>}
          <ul className="media-list">
            {entries.map((entry) => (
              <li key={entry.id} className="hint">
                {formatDate(entry.created_at)}・{AUDIT_LABELS[entry.action] ?? entry.action}
                {typeof entry.detail?.username === 'string' && `（対象: ${entry.detail.username}）`}
                ・実行者: {entry.user_name || '不明'}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
