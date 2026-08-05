import { useState } from "react";

export function Identifier({
  value,
  label = "ID",
}: {
  value: string;
  label?: string;
}) {
  const [status, setStatus] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setStatus("Copied");
    } catch {
      setStatus("Copy failed");
    }
  }

  return (
    <span className="identifier-wrap">
      <code
        className="identifier"
        title={value}
        aria-label={`${label}: ${value}`}
      >
        {value}
      </code>
      <button
        type="button"
        className="copy-button"
        onClick={copy}
        aria-label={`Copy ${label}`}
      >
        ⧉
      </button>
      <span className={status ? "copy-feedback" : "sr-only"} aria-live="polite">
        {status || "Copy status"}
      </span>
    </span>
  );
}

export function LocalDate({ value }: { value: string }) {
  const parsed = new Date(value);
  const display = Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString();
  return (
    <time
      dateTime={value}
      title={`Original UTC value: ${value}`}
      aria-label={`${display}; UTC ${value}`}
    >
      {display}
    </time>
  );
}
