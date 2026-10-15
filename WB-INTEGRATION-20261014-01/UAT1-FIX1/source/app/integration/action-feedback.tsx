import { useLayoutEffect, useRef } from 'react';
import './action-feedback.css';

/** Local to the initiating action, including inside a scrolling native dialog. */
export function ActionFeedback({context, busy, message, error, reveal = true, children}: {
  context: string; busy?: boolean; message?: string; error?: string; reveal?: boolean; children?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!reveal || !ref.current || !(busy || message || error)) return;
    const element = ref.current, rect = element.getBoundingClientRect();
    const dialog = element.closest('dialog')?.getBoundingClientRect();
    const top = Math.max(0, dialog?.top || 0), bottom = Math.min(window.innerHeight, dialog?.bottom || window.innerHeight);
    if (rect.top < top || rect.bottom > bottom) element.scrollIntoView({block: 'nearest'});
  }, [context, busy, message, error, reveal]);
  if (!(busy || message || error)) return null;
  return <div ref={ref} className="wb-action-feedback" data-error={!!error} aria-label={context + '反馈'}>
    <strong>{context}</strong>
    {busy && <p role="status">正在处理，请稍候；请勿重复提交。</p>}
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    {children}
  </div>;
}
