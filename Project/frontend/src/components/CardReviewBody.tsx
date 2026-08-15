import { useCallback, useEffect, useRef, useState } from 'react';
import {
  confirmCard,
  fetchCard,
  fetchMembers,
  reprocessCard,
  saveContact,
  setCardOrientation,
  toContactInput,
  updateCardRegistration,
  type CardDetail,
  type ContactField,
  type ContactInput,
  type OrgMember,
} from '../api';
import { CardRetake } from './CardRetake';

type FieldConfig = {
  field: ContactField;
  label: string;
  kind?: 'text' | 'tel' | 'email' | 'url' | 'multiline';
};

const FIELDS: FieldConfig[] = [
  { field: 'company_name', label: '会社名' },
  { field: 'company_name_kana', label: '会社名カナ' },
  { field: 'department', label: '部署' },
  { field: 'position', label: '役職' },
  { field: 'person_name', label: '氏名' },
  { field: 'person_name_kana', label: '氏名カナ' },
  { field: 'telephone', label: '電話番号', kind: 'tel' },
  { field: 'mobile', label: '携帯番号', kind: 'tel' },
  { field: 'fax', label: 'FAX', kind: 'tel' },
  { field: 'email', label: 'メール', kind: 'email' },
  { field: 'website', label: 'Webサイト', kind: 'url' },
  { field: 'postal_code', label: '郵便番号' },
  { field: 'address', label: '住所', kind: 'multiline' },
  { field: 'notes', label: '備考', kind: 'multiline' },
];

/**
 * review: 撮影後の確認。離脱時に下書きを自動保存し、「登録」で確定する。
 * edit:   登録済み台帳の修正。自動保存はせず、明示の「保存」だけが DB を変える。
 */
export type ReviewMode = 'review' | 'edit';

type Props = {
  cardId: string;
  failed: boolean;
  confirmLabel: string;
  previewRotation: number;
  mode?: ReviewMode;
  onConfirmed: (cardId: string) => void;
  onRotationChange: (rotation: number) => void;
  onImageRevision: (revision: string) => void;
  onOrientationCommitted?: () => void;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

export function CardReviewBody({ cardId, failed, confirmLabel, previewRotation, mode = 'review', onConfirmed, onRotationChange, onImageRevision, onOrientationCommitted, onBusyChange, onDirtyChange }: Props) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [values, setValues] = useState<ContactInput>(() => toContactInput(null));
  const [busy, setBusy] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [registrationError, setRegistrationError] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    onBusyChange?.(Boolean(busy));
  }, [busy, onBusyChange]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    fetchMembers()
      .then(setMembers)
      .catch(() => {
        // 登録者の選択肢が出せないだけで、確認・登録自体は続けられる
      });
  }, []);

  // 離脱時に下書きを保存するため、クリーンアップから最新値を読めるようにしておく
  const draftRef = useRef<ContactInput | null>(null);
  const dirtyRef = useRef(false);
  const editedFieldsRef = useRef<Set<ContactField>>(new Set());

  const load = useCallback(async () => {
    setErrorMessage('');
    try {
      const loaded = await fetchCard(cardId);
      setDetail(loaded);
      onImageRevision(loaded.image_revision);
      const initial = toContactInput(loaded.contact);
      setValues(initial);
      draftRef.current = initial;
      dirtyRef.current = false;
      setDirty(false);
      editedFieldsRef.current = new Set();
      onRotationChange(0);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を読み込めませんでした');
    }
  }, [cardId, onImageRevision, onRotationChange]);

  useEffect(() => {
    setDetail(null);
    void load();
  }, [load]);

  // 名刺を切り替えたときに入力が消えないよう、未保存の変更だけ黙って下書き保存する。
  // confirm は呼ばないので「確定登録」にはならない。
  // 登録済みの台帳を直す edit では行わない。明示の「保存」以外で DB が変わると、
  // 見ただけ・触っただけのつもりの操作が確定済みデータを書き換えてしまう。
  useEffect(() => {
    if (mode === 'edit') {
      return;
    }
    return () => {
      const draft = draftRef.current;
      if (!dirtyRef.current || !draft) {
        return;
      }
      void saveContact(cardId, draft, [...editedFieldsRef.current]).catch(() => {
        // 離脱後なので画面に出す先がない。次に開いたとき元の値が見えるだけで実害はない
      });
    };
  }, [cardId, mode]);

  const updateField = (field: ContactField, value: string) => {
    setValues((current) => {
      const next = { ...current, [field]: value };
      draftRef.current = next;
      dirtyRef.current = true;
      editedFieldsRef.current.add(field);
      return next;
    });
    setDirty(true);
  };

  const handleSave = async () => {
    setBusy('保存しています…');
    setErrorMessage('');
    try {
      await saveContact(cardId, values, [...editedFieldsRef.current]);
      dirtyRef.current = false;
      setDirty(false);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '保存に失敗しました');
    } finally {
      setBusy('');
    }
  };

  const handleReplaced = async (reread: boolean) => {
    // 読み直した場合は項目も入れ替わっている。画像だけの差し替えでも
    // image_revision が変わるので、どちらにせよ読み込み直す。
    if (reread) {
      dirtyRef.current = false;
      setDirty(false);
    }
    await load();
    onOrientationCommitted?.();
  };

  const handleConfirm = async () => {
    setBusy('登録しています…');
    setErrorMessage('');
    try {
      // プレビューで回転しただけで「この向きで再認識」を押さずに登録すると、画像が
      // 撮影時の向きのまま保存されてしまう。登録時に未確定の回転が残っていれば、
      // 入力済みのフィールドを上書きしないよう画像・向きだけ書き込んでおく。
      if (detail && previewRotation !== 0) {
        await setCardOrientation(cardId, (detail.orientation + previewRotation) % 360, false);
        onRotationChange(0);
        onOrientationCommitted?.();
      }
      await saveContact(cardId, values, [...editedFieldsRef.current]);
      await confirmCard(cardId);
      dirtyRef.current = false;
      setDirty(false);
      onConfirmed(cardId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '登録に失敗しました');
    } finally {
      setBusy('');
    }
  };

  const handleReprocess = async () => {
    setBusy('もう一度読み取っています…');
    setErrorMessage('');
    try {
      await reprocessCard(cardId);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '再解析に失敗しました');
    } finally {
      setBusy('');
    }
  };

  const updateRegistration = async (field: 'card_owner_user_id' | 'exchanged_at', value: string) => {
    if (!detail?.contact?.card_owner_user_id || !detail.contact.exchanged_at) return;
    const body = {
      card_owner_user_id: detail.contact.card_owner_user_id,
      exchanged_at: detail.contact.exchanged_at,
      [field]: value,
    };
    setRegistrationError('');
    try {
      const result = await updateCardRegistration(cardId, body);
      setDetail((current) => (current ? { ...current, contact: { ...current.contact, ...result } } : current));
    } catch (error) {
      setRegistrationError(error instanceof Error ? error.message : '登録者・交換日の更新に失敗しました');
    }
  };

  // 台帳では向きだけを直す。再認識まで走らせると、確定済みの14項目が読み取り結果で
  // 上書きされてしまう（読み直したいときは撮り直しから明示的に選ぶ）。
  const commitOrientation = async () => {
    if (!detail || previewRotation === 0) return;
    const reread = mode !== 'edit';
    setBusy(reread ? '向きを直して読み取っています…' : '向きを直しています…'); setErrorMessage('');
    try {
      await setCardOrientation(cardId, (detail.orientation + previewRotation) % 360, reread);
      await load();
      onOrientationCommitted?.();
    } catch (error) { setErrorMessage(error instanceof Error ? error.message : '向きの補正に失敗しました'); }
    finally { setBusy(''); }
  };

  if (!detail) {
    return (
      <div className="waiting">
        <div className="spinner" />
        <p className="lead">名刺を読み込んでいます…</p>
      </div>
    );
  }

  return (
    <div className="review">
      {failed && (
        <p className="alert alert--warn">
          自動読み取りに失敗しました。画像を見ながら入力するか、「もう一度読み取る」をお試しください。
        </p>
      )}
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}

      <div className="fields">
        {FIELDS.map((config) => (
          <Field key={config.field} config={config} value={values[config.field]} flagged={Boolean(detail.review_flags[config.field])} onChange={updateField} />
        ))}
      </div>

      <details className="ocr">
        <summary>読み取った文字を見る</summary>
        <pre className="ocr__text">{detail.ocr_text || '（テキストなし）'}</pre>
      </details>

      {mode === 'review' && (
        <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={handleReprocess}>
          もう一度読み取る
        </button>
      )}
      {previewRotation !== 0 && (
        <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={() => void commitOrientation()}>
          {mode === 'edit' ? 'この向きで確定' : 'この向きで再認識'}
        </button>
      )}

      <CardRetake
        cardId={cardId}
        disabled={Boolean(busy)}
        onBusyChange={(retaking) => setBusy(retaking ? '撮り直しています…' : '')}
        onReplaced={(reread) => void handleReplaced(reread)}
      />

      {mode === 'edit' && dirty && <p className="alert alert--warn">未保存の変更があります。</p>}

      <div className="action-bar">
        {mode === 'edit' ? (
          <button type="button" className="button button--primary" disabled={Boolean(busy) || !dirty} onClick={() => void handleSave()}>
            {busy || '保存'}
          </button>
        ) : (
          <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={handleConfirm}>
            {busy || confirmLabel}
          </button>
        )}
      </div>

      {detail.contact?.confirmed && detail.contact.card_owner_user_id && detail.contact.exchanged_at && (
        <div className="fields">
          {registrationError && <p className="alert alert--error">{registrationError}</p>}
          <label className="field">
            <span className="field__label">登録者</span>
            <select
              className="field__input"
              value={detail.contact.card_owner_user_id}
              onChange={(event) => void updateRegistration('card_owner_user_id', event.target.value)}
            >
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">名刺交換日</span>
            <input
              className="field__input"
              type="date"
              value={detail.contact.exchanged_at}
              onChange={(event) => void updateRegistration('exchanged_at', event.target.value)}
            />
          </label>
        </div>
      )}
    </div>
  );
}

type FieldProps = {
  config: FieldConfig;
  value: string;
  flagged: boolean;
  onChange: (field: ContactField, value: string) => void;
};

function Field({ config, value, flagged, onChange }: FieldProps) {
  const { field, label, kind = 'text' } = config;

  if (kind === 'multiline') {
    return (
      <label className="field">
        <span className="field__label">{label}{flagged && <em className="field__flag">要確認</em>}</span>
        <textarea
          className="field__input"
          value={value}
          rows={2}
          onChange={(event) => onChange(field, event.target.value)}
        />
      </label>
    );
  }

  return (
    <label className="field">
      <span className="field__label">{label}{flagged && <em className="field__flag">要確認</em>}</span>
      <input
        className="field__input"
        type={kind}
        inputMode={kind === 'tel' ? 'tel' : undefined}
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </label>
  );
}
