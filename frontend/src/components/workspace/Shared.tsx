import { useEffect, useRef, type ReactNode } from "react";
import { ArrowUpRight, Check, LoaderCircle, X } from "lucide-react";
import { categoryName, safeLink } from "../../services/workspaceApi";

export function Mark({ small = false }: { small?: boolean }) {
  return (
    <span className={"gm-mark " + (small ? "small" : "")}>
      <svg viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <path
          d="M7 20 14 6l7 14M10 15h8M5 8l4 3m14-3-4 3"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
export function Badge({
  value,
  children,
}: {
  value: string;
  children?: ReactNode;
}) {
  return (
    <span className={"badge badge-" + value}>
      {value === "verified" && <Check size={11} />}{" "}
      {children || categoryName(value)}
    </span>
  );
}
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading-inline">
      <LoaderCircle className="spin" size={18} />
      {label}
    </div>
  );
}
export function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function ExternalLink({
  url,
  children,
}: {
  url?: string | null;
  children: ReactNode;
}) {
  const href = safeLink(url);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className="external-link">
      {children}
      <ArrowUpRight size={13} />
    </a>
  ) : (
    <span>{children}</span>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={"modal " + (wide ? "modal-wide" : "")}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
