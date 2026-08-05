export function ConfirmedActionButton({
  busy,
  idleLabel,
  busyLabel,
}: {
  busy: boolean;
  idleLabel: string;
  busyLabel: string;
}) {
  return (
    <button
      type="submit"
      className="primary-button"
      disabled={busy}
      aria-disabled={busy}
    >
      {busy ? busyLabel : idleLabel}
    </button>
  );
}
