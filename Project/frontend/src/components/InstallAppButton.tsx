import { useEffect, useRef, useState } from 'react';

// beforeinstallprompt はまだ標準DOM型に無いので、使う分だけ最小限に定義する。
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

const IOS_GUIDE_MS = 8000;

function isIOS(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function isStandalone(): boolean {
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return window.matchMedia('(display-mode: standalone)').matches || Boolean(nav.standalone);
}

// iOS SafariはbeforeinstallpromptもuserChoiceも持たず、共有メニューからの
// 手動追加しかできないため、案内文を表示する形で代替する。
export function InstallAppButton() {
  const [visible, setVisible] = useState(false);
  const [showIOSGuide, setShowIOSGuide] = useState(false);
  const deferredPrompt = useRef<BeforeInstallPromptEvent | null>(null);
  const guideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isStandalone()) return;
    if (isIOS()) setVisible(true);

    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      deferredPrompt.current = event as BeforeInstallPromptEvent;
      setVisible(true);
    };
    const onAppInstalled = () => {
      setVisible(false);
      deferredPrompt.current = null;
    };

    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt);
    window.addEventListener('appinstalled', onAppInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt);
      window.removeEventListener('appinstalled', onAppInstalled);
      if (guideTimer.current) clearTimeout(guideTimer.current);
    };
  }, []);

  const handleClick = async () => {
    if (deferredPrompt.current) {
      await deferredPrompt.current.prompt();
      const result = await deferredPrompt.current.userChoice;
      deferredPrompt.current = null;
      if (result.outcome === 'accepted') setVisible(false);
      return;
    }
    if (!isIOS()) return;
    if (guideTimer.current) {
      clearTimeout(guideTimer.current);
      guideTimer.current = null;
    }
    if (showIOSGuide) {
      setShowIOSGuide(false);
      return;
    }
    setShowIOSGuide(true);
    guideTimer.current = setTimeout(() => setShowIOSGuide(false), IOS_GUIDE_MS);
  };

  if (!visible) return null;

  return (
    <>
      <button type="button" className="install-btn" onClick={() => void handleClick()}>
        <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="2" width="14" height="20" rx="2" />
          <line x1="12" y1="7" x2="12" y2="15" />
          <polyline points="8 11 12 15 16 11" />
          <line x1="5" y1="20" x2="19" y2="20" />
        </svg>
        ホーム画面に追加
      </button>
      {showIOSGuide && (
        <div className="install-guide">
          Safariの<strong>共有（↑）</strong>ボタン → <strong>「ホーム画面に追加」</strong>
          <br />
          をタップすると次回からすぐ使えます
        </div>
      )}
    </>
  );
}
