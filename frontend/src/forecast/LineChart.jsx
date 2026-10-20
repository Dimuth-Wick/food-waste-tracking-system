import { useEffect, useRef, useState } from "react";

const HEIGHT = 280;
const MARGIN = { top: 28, right: 84, bottom: 32, left: 46 };
const LABEL_GAP = 15;

function niceStep(max, ticks = 4) {
  const raw = max / ticks;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((n) => n * power).find((n) => n >= raw);
  return step || power;
}

function shortDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function LineChart({ rows, series, unit, title }) {
  const box = useRef(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const peak = Math.max(...rows.flatMap((row) => series.map((s) => row[s.key])), 0.1);
  const step = niceStep(peak);
  const top = Math.ceil(peak / step) * step;
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
  const x = (index) => MARGIN.left + (rows.length > 1 ? (index / (rows.length - 1)) * innerWidth : innerWidth / 2);
  const y = (value) => MARGIN.top + innerHeight - (value / top) * innerHeight;

  const labelEvery = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(innerWidth / 90))));
  const last = rows.length - 1;

  // End-of-line labels, nudged apart when the two lines finish close together.
  const ends = series.map((s) => ({ ...s, y: y(rows[last][s.key]) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i += 1) {
    if (ends[i].y - ends[i - 1].y < LABEL_GAP) ends[i].y = ends[i - 1].y + LABEL_GAP;
  }

  function pick(clientX) {
    const rect = box.current.getBoundingClientRect();
    const position = ((clientX - rect.left) - MARGIN.left) / innerWidth;
    setHover(Math.min(last, Math.max(0, Math.round(position * last))));
  }

  function onKeyDown(event) {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const move = event.key === "ArrowRight" ? 1 : -1;
      setHover((current) => Math.min(last, Math.max(0, (current ?? (move > 0 ? -1 : last + 1)) + move)));
    } else if (event.key === "Escape") {
      setHover(null);
    }
  }

  const tipRow = hover === null ? null : rows[hover];
  const tipOnLeft = hover !== null && x(hover) > width * 0.6;

  return (
    <figure className="chart">
      <div className="chart-legend" aria-hidden="true">
        {series.map((s) => (
          <span key={s.key} className="chart-legend-item">
            <svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? "5 3" : undefined} strokeLinecap="round" /></svg>
            {s.label}
          </span>
        ))}
      </div>
      <div
        ref={box}
        className="chart-plot"
        tabIndex={0}
        role="img"
        aria-label={`${title}. Use the left and right arrow keys to read each service.`}
        onPointerMove={(event) => pick(event.clientX)}
        onPointerLeave={() => setHover(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setHover(null)}
      >
        <svg width={width} height={HEIGHT} className="chart-svg">
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={y(tick)} y2={y(tick)} className={tick === 0 ? "chart-baseline" : "chart-grid"} />
              <text x={MARGIN.left - 8} y={y(tick)} className="chart-tick" textAnchor="end" dominantBaseline="middle">
                {Number.isInteger(tick) ? tick : tick.toFixed(1)}
              </text>
            </g>
          ))}
          <text x={MARGIN.left - 8} y={MARGIN.top - 16} className="chart-tick" textAnchor="end">{unit}</text>
          {rows.map((row, index) => (index % labelEvery === 0 || index === last) && (
            <text key={index} x={x(index)} y={HEIGHT - 10} className="chart-tick" textAnchor={index === 0 ? "start" : index === last ? "end" : "middle"}>
              {shortDate(row.date)}
            </text>
          ))}

          {series.map((s) => (
            <path
              key={s.key}
              d={rows.map((row, index) => `${index ? "L" : "M"}${x(index)},${y(row[s.key])}`).join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={s.dashed ? "6 4" : undefined}
            />
          ))}
          {rows.length === 1 && series.map((s) => (
            <circle key={s.key} cx={x(0)} cy={y(rows[0][s.key])} r="4" fill={s.color} stroke="#fff" strokeWidth="2" />
          ))}
          {ends.map((s) => (
            <text key={s.key} x={x(last) + 8} y={s.y} className="chart-end-label" dominantBaseline="middle">{s.label}</text>
          ))}

          {tipRow && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={MARGIN.top + innerHeight} className="chart-crosshair" />
              {series.map((s) => (
                <circle key={s.key} cx={x(hover)} cy={y(tipRow[s.key])} r="5" fill={s.color} stroke="#fff" strokeWidth="2" />
              ))}
            </g>
          )}
        </svg>

        {tipRow && (
          <div
            className="chart-tooltip"
            style={tipOnLeft
              ? { right: width - x(hover) + 12, top: MARGIN.top }
              : { left: x(hover) + 12, top: MARGIN.top }}
          >
            <p className="chart-tooltip-date">{shortDate(tipRow.date)}</p>
            {series.map((s) => (
              <p key={s.key} className="chart-tooltip-row">
                <svg width="14" height="6" aria-hidden="true"><line x1="1" y1="3" x2="13" y2="3" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? "4 2" : undefined} /></svg>
                <strong>{tipRow[s.key].toFixed(2)} {unit}</strong>
                <span>{s.label}</span>
              </p>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}
