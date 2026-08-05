import { safeErrorMessage } from "../../api/errors";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-panel loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "Unable to load data",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div className="state-panel error-state" role="alert">
      <strong>{title}</strong>
      <p>{safeErrorMessage(error)}</p>
      {onRetry && (
        <button type="button" className="secondary-button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="state-panel empty-state">
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

export function Notification({
  tone,
  children,
}: {
  tone: "success" | "warning" | "error";
  children: React.ReactNode;
}) {
  return (
    <div
      className={`notification ${tone}`}
      role={tone === "error" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
