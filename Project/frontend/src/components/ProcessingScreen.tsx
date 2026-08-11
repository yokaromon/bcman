type Props = {
  fatalMessage: string;
  onRestart: () => void;
};

/** 名刺が1枚も取れていない間だけの画面。1枚でも取れたら CardPager 側で状態を出す。 */
export function ProcessingScreen({ fatalMessage, onRestart }: Props) {
  if (fatalMessage) {
    return (
      <div className="screen screen--center">
        <p className="alert alert--error">{fatalMessage}</p>
        <button type="button" className="button button--primary button--xl" onClick={onRestart}>
          撮り直す
        </button>
      </div>
    );
  }

  return (
    <div className="screen screen--center">
      <div className="spinner" />
      <p className="lead">名刺を探しています…</p>
    </div>
  );
}
