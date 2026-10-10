import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function WorkbenchDialog({ title, subtitle, onClose, children, wide = false }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]'));
    focusables()[0]?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key === "Tab") {
        const items = focusables();
        const first = items[0]; const last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    dialog.addEventListener("keydown", key);
    return () => { dialog.removeEventListener("keydown", key); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop"><div ref={ref} className={`workbench-dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
    <header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" title="关闭弹窗" onClick={onClose}><X size={19} /></button></header>
    {children}
  </div></div>;
}
