function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function ConfidenceMeter({
  value,
  level,
}: {
  value: number;
  level: string;
}) {
  const percent = Math.round(clamp(value) * 100);
  return (
    <div className="confidence-meter">
      <div className="confidence-label">
        <span>{level} confidence</span>
        <strong>{percent}%</strong>
      </div>
      <div
        className="meter-track"
        role="meter"
        aria-label={`${level} confidence`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
