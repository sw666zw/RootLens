function publicHttpUrl(configured: unknown, fallback: string): string {
  if (typeof configured !== "string") return fallback;
  try {
    const url = new URL(configured);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.href
      : fallback;
  } catch {
    return fallback;
  }
}

const tools = [
  {
    label: "Grafana",
    url: publicHttpUrl(
      import.meta.env.VITE_GRAFANA_URL,
      "http://localhost:3000",
    ),
  },
  {
    label: "Jaeger",
    url: publicHttpUrl(
      import.meta.env.VITE_JAEGER_URL,
      "http://localhost:16686",
    ),
  },
  {
    label: "Prometheus",
    url: publicHttpUrl(
      import.meta.env.VITE_PROMETHEUS_URL,
      "http://localhost:9090",
    ),
  },
];

export function ExternalToolLinks({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "external-links compact" : "external-links"}>
      {tools.map((tool) => (
        <a
          key={tool.label}
          href={tool.url}
          target="_blank"
          rel="noreferrer noopener"
        >
          <span>{tool.label}</span>
          <span aria-hidden="true">↗</span>
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ))}
    </div>
  );
}
