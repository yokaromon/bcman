import { useCallback, useEffect, useState } from 'react';
import {
  cardImageUrl,
  confirmCard,
  fetchCard,
  reprocessCard,
  saveContact,
  toContactInput,
  type CardDetail,
  type ContactField,
  type ContactInput,
} from '../api';

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

type Props = {
  userId: string;
  cardId: string;
  position: number;
  total: number;
  failed: boolean;
  onAdvance: () => void;
};

export function CardReviewScreen({ userId, cardId, position, total, failed, onAdvance }: Props) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [values, setValues] = useState<ContactInput>(() => toContactInput(null));
  const [busy, setBusy] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const load = useCallback(async () => {
    setErrorMessage('');
    try {
      const loaded = await fetchCard(userId, cardId);
      setDetail(loaded);
      setValues(toContactInput(loaded.contact));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を読み込めませんでした');
    }
  }, [userId, cardId]);

  useEffect(() => {
    setDetail(null);
    void load();
  }, [load]);

  const updateField = (field: ContactField, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
  };

  const handleConfirm = async () => {
    setBusy('登録しています…');
    setErrorMessage('');
    try {
      await saveContact(userId, cardId, values);
      await confirmCard(userId, cardId);
      onAdvance();
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
      await reprocessCard(userId, cardId);
      await load();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '再解析に失敗しました');
    } finally {
      setBusy('');
    }
  };

  if (!detail) {
    return (
      <div className="screen screen--center">
        <div className="spinner" />
        <p className="lead">名刺を読み込んでいます…</p>
      </div>
    );
  }

  return (
    <div className="screen screen--form">
      <p className="progress-note">
        名刺 {position} / {total}
      </p>

      <a className="card-image" href={cardImageUrl(cardId)} target="_blank" rel="noreferrer">
        <img src={cardImageUrl(cardId)} alt={`名刺 ${position} の画像`} />
      </a>

      {failed && (
        <p className="alert alert--warn">
          自動読み取りに失敗しました。画像を見ながら入力するか、「もう一度読み取る」をお試しください。
        </p>
      )}
      {errorMessage && <p className="alert alert--error">{errorMessage}</p>}

      <div className="fields">
        {FIELDS.map((config) => (
          <Field key={config.field} config={config} value={values[config.field]} onChange={updateField} />
        ))}
      </div>

      <details className="ocr">
        <summary>読み取った文字を見る</summary>
        <pre className="ocr__text">{detail.ocr_text || '（テキストなし）'}</pre>
      </details>

      <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={handleReprocess}>
        もう一度読み取る
      </button>

      <div className="action-bar">
        <button type="button" className="button button--ghost" disabled={Boolean(busy)} onClick={onAdvance}>
          あとで
        </button>
        <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={handleConfirm}>
          {busy || (position < total ? '登録して次へ' : '登録して完了')}
        </button>
      </div>
    </div>
  );
}

type FieldProps = {
  config: FieldConfig;
  value: string;
  onChange: (field: ContactField, value: string) => void;
};

function Field({ config, value, onChange }: FieldProps) {
  const { field, label, kind = 'text' } = config;

  if (kind === 'multiline') {
    return (
      <label className="field">
        <span className="field__label">{label}</span>
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
      <span className="field__label">{label}</span>
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
