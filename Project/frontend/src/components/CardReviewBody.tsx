import { useCallback, useEffect, useRef, useState } from 'react';
import {
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
  cardId: string;
  failed: boolean;
  confirmLabel: string;
  onConfirmed: (cardId: string) => void;
};

export function CardReviewBody({ cardId, failed, confirmLabel, onConfirmed }: Props) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [values, setValues] = useState<ContactInput>(() => toContactInput(null));
  const [busy, setBusy] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  // 離脱時に下書きを保存するため、クリーンアップから最新値を読めるようにしておく
  const draftRef = useRef<ContactInput | null>(null);
  const dirtyRef = useRef(false);

  const load = useCallback(async () => {
    setErrorMessage('');
    try {
      const loaded = await fetchCard(cardId);
      setDetail(loaded);
      const initial = toContactInput(loaded.contact);
      setValues(initial);
      draftRef.current = initial;
      dirtyRef.current = false;
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '名刺を読み込めませんでした');
    }
  }, [cardId]);

  useEffect(() => {
    setDetail(null);
    void load();
  }, [load]);

  // 名刺を切り替えたときに入力が消えないよう、未保存の変更だけ黙って下書き保存する。
  // confirm は呼ばないので「確定登録」にはならない。
  useEffect(() => {
    return () => {
      const draft = draftRef.current;
      if (!dirtyRef.current || !draft) {
        return;
      }
      void saveContact(cardId, draft).catch(() => {
        // 離脱後なので画面に出す先がない。次に開いたとき元の値が見えるだけで実害はない
      });
    };
  }, [cardId]);

  const updateField = (field: ContactField, value: string) => {
    setValues((current) => {
      const next = { ...current, [field]: value };
      draftRef.current = next;
      dirtyRef.current = true;
      return next;
    });
  };

  const handleConfirm = async () => {
    setBusy('登録しています…');
    setErrorMessage('');
    try {
      await saveContact(cardId, values);
      await confirmCard(cardId);
      dirtyRef.current = false;
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
        <button type="button" className="button button--primary" disabled={Boolean(busy)} onClick={handleConfirm}>
          {busy || confirmLabel}
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
