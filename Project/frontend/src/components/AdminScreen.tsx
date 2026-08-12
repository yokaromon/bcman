import { useCallback, useEffect, useState } from 'react';
import {
  createOrgGroup,
  createOrgUser,
  fetchOrgGroups,
  fetchOrgUsers,
  fetchUserDevices,
  resetUserPassword,
  resetUserTotp,
  revokeDevice,
  unlockUser,
  type Group,
  type Me,
  type OrgUser,
  type Role,
  type TrustedDevice,
} from '../api';

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** otpauth:// URI から手入力用の秘密鍵を取り出す。QRを生成しない代わりに、
 * 認証アプリの「セットアップキーを入力」機能で登録できるようにする。 */
function extractSecret(provisioningUri: string): string {
  return /[?&]secret=([^&]+)/.exec(provisioningUri)?.[1] ?? '';
}

function NewCredential({ username, uri, onDismiss }: { username: string; uri: string; onDismiss: () => void }) {
  return (
    <div className="alert alert--warn">
      <p>
        <strong>{username}</strong> の認証アプリ登録用シークレット（この画面を閉じると二度と表示されません。今すぐ本人の端末で認証アプリに登録してください）:
      </p>
      <pre className="ocr__text">{extractSecret(uri)}</pre>
      <p className="hint">セットアップキー（Base32）として認証アプリに手入力するか、次のURIを対応アプリで開いてください。</p>
      <pre className="ocr__text">{uri}</pre>
      <button type="button" className="button button--ghost" onClick={onDismiss}>
        閉じた（登録済み）
      </button>
    </div>
  );
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
  const [newPassword, setNewPassword] = useState('');
  const [newSecretUri, setNewSecretUri] = useState('');

  const groupNames = user.groups
    .map((id) => groups.find((group) => group.id === id)?.name ?? id)
    .join('、');

  const runResetPassword = async () => {
    if (newPassword.length < 12) {
      setMessage('パスワードは12文字以上にしてください');
      return;
    }
    setBusy('resetting');
    setMessage('');
    try {
      await resetUserPassword(orgId, user.id, newPassword);
      setNewPassword('');
      setMessage('パスワードを再設定しました');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '再設定に失敗しました');
    } finally {
      setBusy('');
    }
  };

  const runResetTotp = async () => {
    setBusy('totp');
    setMessage('');
    try {
      const result = await resetUserTotp(orgId, user.id);
      setNewSecretUri(result.totp_provisioning_uri);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'リセットに失敗しました');
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
          <strong>{user.name}</strong>（{user.username} / {user.role === 'admin' ? '管理者' : '一般'} / {groupNames || '未所属'}）
        </span>
        <button type="button" className="button button--ghost" onClick={() => setExpanded((value) => !value)}>
          {expanded ? '閉じる' : '端末・操作'}
        </button>
      </div>

      {expanded && (
        <div className="review">
          {newSecretUri && (
            <NewCredential username={user.username} uri={newSecretUri} onDismiss={() => setNewSecretUri('')} />
          )}
          {message && <p className="alert alert--warn">{message}</p>}

          <div className="fields">
            <label className="field">
              <span className="field__label">新しいパスワード（12文字以上）</span>
              <input
                className="field__input"
                type="text"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </label>
          </div>
          <div className="action-bar">
            <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={runResetPassword}>
              パスワード再設定
            </button>
            <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={runResetTotp}>
              認証コードをリセット
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
  const [form, setForm] = useState({ username: '', name: '', password: '', role: 'member' as Role });
  const [formGroupIds, setFormGroupIds] = useState<string[]>([]);
  const [createdCredential, setCreatedCredential] = useState<{ username: string; uri: string } | null>(null);

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
      const result = await createOrgUser(user.organization_id, { ...form, group_ids: formGroupIds });
      setCreatedCredential({ username: result.username, uri: result.totp_provisioning_uri });
      setForm({ username: '', name: '', password: '', role: 'member' });
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
        <NewCredential
          username={createdCredential.username}
          uri={createdCredential.uri}
          onDismiss={() => setCreatedCredential(null)}
        />
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
          <span className="field__label">初期パスワード（12文字以上）</span>
          <input
            className="field__input"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
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
    </div>
  );
}
