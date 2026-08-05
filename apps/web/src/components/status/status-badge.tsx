import type { ReactNode } from "react";

export function StatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: "success" | "warning" | "danger" | "info" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
