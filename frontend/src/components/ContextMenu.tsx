import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export interface ContextMenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  destructive?: boolean;
  separatorBefore?: boolean;
  onSelect: () => void | Promise<void>;
}

interface ContextMenuProps {
  x: number;
  y: number;
  label: string;
  items: ContextMenuItem[];
  onClose: () => void;
}

export function ContextMenu({ x, y, label, items, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x, y });

  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const margin = 8;
    setPosition({
      x: Math.max(margin, Math.min(x, window.innerWidth - menu.offsetWidth - margin)),
      y: Math.max(margin, Math.min(y, window.innerHeight - menu.offsetHeight - margin)),
    });
    menu.querySelector<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)')?.focus();
  }, [x, y]);

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("scroll", onClose, true);
    window.addEventListener("blur", onClose);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("scroll", onClose, true);
      window.removeEventListener("blur", onClose);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const buttons = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)') ?? [],
    );
    if (buttons.length === 0) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const target = event.key === "Home"
      ? 0
      : event.key === "End"
        ? buttons.length - 1
        : event.key === "ArrowDown"
          ? (current + 1 + buttons.length) % buttons.length
          : (current - 1 + buttons.length) % buttons.length;
    buttons[target]?.focus();
  }

  return (
    <div
      ref={menuRef}
      className="context-menu"
      role="menu"
      aria-label={label}
      style={{ left: position.x, top: position.y }}
      onKeyDown={handleKeyDown}
      onContextMenu={(event) => event.preventDefault()}
    >
      {items.map((item) => (
        <div className="context-menu__entry" key={item.id}>
          {item.separatorBefore && <div className="context-menu__separator" role="separator" />}
          <button
            role="menuitem"
            className={item.destructive ? "destructive" : ""}
            disabled={item.disabled}
            onClick={() => {
              onClose();
              void item.onSelect();
            }}
          >
            <span className="context-menu__icon" aria-hidden="true">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        </div>
      ))}
    </div>
  );
}
