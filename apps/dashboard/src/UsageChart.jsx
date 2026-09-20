export function UsageChart({ days }) {
  if (!days.length) {
    return <p className="muted">No usage_daily rows yet. Mint a key, chat from the playground, then refresh.</p>;
  }
  const max = Math.max(1, ...days.map((row) => row.calls));
  return (
    <div className="chart" role="img" aria-label="Daily API calls from usage_daily">
      {days.map((row) => (
        <div key={row.day} className="bar-col">
          <div className="bar" style={{ height: `${Math.max(8, (row.calls / max) * 120)}px` }} title={`${row.calls} calls`} />
          <span className="bar-label">{row.day.slice(5)}</span>
          <span className="bar-n">{row.calls}</span>
        </div>
      ))}
    </div>
  );
}
