import { useId } from "react";

export function Logo({ size = 32, withWord = false, animated = true, word = "Cloudiator" }) {
  const raw = useId().replace(/:/g, "");
  const ring = `cld-ring-${raw}`;
  const core = `cld-core-${raw}`;
  return (
    <span className={animated ? "brand is-live" : "brand"}>
      <svg
        className="brand-mark"
        width={size}
        height={size}
        viewBox="0 0 64 64"
        role="img"
        aria-label="Cloudiator"
      >
        <defs>
          <linearGradient id={ring} x1="6" y1="2" x2="58" y2="62">
            <stop stopColor="#5eead4" />
            <stop offset="0.55" stopColor="#67e8f9" />
            <stop offset="1" stopColor="#818cf8" />
          </linearGradient>
          <linearGradient id={core} x1="28" y1="18" x2="50" y2="44">
            <stop stopColor="#f8fffe" />
            <stop offset="1" stopColor="#5eead4" />
          </linearGradient>
        </defs>
        <rect x="2.5" y="2.5" width="59" height="59" rx="18" fill="#071017" stroke={`url(#${ring})`} strokeWidth="1.4" />
        <ellipse className="brand-orbit" cx="31" cy="34" rx="16.5" ry="10.5" stroke={`url(#${ring})`} strokeOpacity="0.38" />
        <path
          d="M43.8 21.2c-4.3-3.8-10.4-5.4-16.1-3.9C19.6 19.2 14.2 26.4 14.6 34.8c.4 8.6 7.4 15.3 16 15.5 5.9.2 11.2-2.6 14.3-7.3"
          stroke={`url(#${ring})`}
          strokeWidth="5.6"
          strokeLinecap="round"
          fill="none"
        />
        <circle className="brand-node" cx="46.4" cy="31.2" r="4.35" fill={`url(#${core})`} />
        <circle cx="31.2" cy="33.8" r="2.15" fill="#5eead4" fillOpacity="0.95" />
      </svg>
      {withWord ? <span className="brand-word">{word}</span> : null}
    </span>
  );
}
