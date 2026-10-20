import { useEffect, useRef, useState } from "react";

const HEIGHT = 320;
const MARGIN = { top: 24, right: 84, bottom: 52, left: 46 };
const LABEL_GAP = 15;
const DAY_WIDTH = 28; // narrowest a day is allowed to get before the chart scrolls sideways

const VERDICT_TEXT = { hit: "On target", over: "Predicted too much", under: "Predicted too little" };
const LEGEND = [["hit", "On target"], ["over", "Off day"]];
const HIT_COLOR = "#0a8a54";
const MISS_COLOR = "#d00f35";

function niceStep(span, ticks = 4) {
  const raw = span / ticks;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 2.5, 5, 10].map((n) => n * power).find((n) => n >= raw) || power;
}

function parseDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function shortDate(value) {
  const date = parseDate(value);
  return date ? date.toLocaleDateString(undefined, { day: "numeric", month: "short" }) : value;
}

// Smooth line through the points that never overshoots them (monotone cubic),
// so a curve can't dip below a real value between two days.
function smooth(points) {
  const n = points.length;
  if (n < 3) return points.slice(1).map((p, i) => ({ c1: points[i], c2: p, p }));
  const dx = [], slope = [];
  for (let i = 0; i < n - 1; i += 1) {
    dx.push(points[i + 1][0] - points[i][0]);
    slope.push((points[i + 1][1] - points[i][1]) / dx[i]);
  }
  const m = [slope[0]];
  for (let i = 1; i < n - 1; i += 1) m.push(slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2);
  m.push(slope[n - 2]);
  for (let i = 0; i < n - 1; i += 1) {
    if (slope[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / slope[i], b = m[i + 1] / slope[i], size = a * a + b * b;
    if (size > 9) { const t = 3 / Math.sqrt(size); m[i] = t * a * slope[i]; m[i + 1] = t * b * slope[i]; }
  }
  return points.slice(1).map((p, i) => ({
    c1: [points[i][0] + dx[i] / 3, points[i][1] + (m[i] * dx[i]) / 3],
    c2: [p[0] - dx[i] / 3, p[1] - (m[i + 1] * dx[i]) / 3],
    p,
  }));
}

const fmt = (n) => Math.round(n * 10) / 10;
const linePath = (start, segments) => `M${fmt(start[0])},${fmt(start[1])} ` + segments
  .map((s) => `C${fmt(s.c1[0])},${fmt(s.c1[1])} ${fmt(s.c2[0])},${fmt(s.c2[1])} ${fmt(s.p[0])},${fmt(s.p[1])}`).join(" ");

// The same curve walked backwards, so two curves can be joined into one shaded band.
function reversed(start, segments) {
  const out = [];
  let from = segments.length ? segments[segments.length - 1].p : start;
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    const before = i === 0 ? start : segments[i - 1].p;
    out.push(`C${fmt(segments[i].c2[0])},${fmt(segments[i].c2[1])} ${fmt(segments[i].c1[0])},${fmt(segments[i].c1[1])} ${fmt(before[0])},${fmt(before[1])}`);
    from = before;
  }
  return out.join(" ");
}

// Marker for one day on the "actual" line: a green dot when on target, a red dot with a
// halo when the forecast missed. The halo means the two never rely on colour alone.
function Marker({ kind, cx, cy, size = 5, dim = false }) {
  const style = { opacity: dim ? 0.2 : 1, transition: "opacity .2s" };
  if (kind === "hit") return <circle cx={cx} cy={cy} r={size - 0.5} fill={HIT_COLOR} stroke="#fff" strokeWidth="1.5" style={style} />;
  return (
    <g style={style}>
      <circle cx={cx} cy={cy} r={size + 3.5} fill={MISS_COLOR} fillOpacity="0.16" stroke={MISS_COLOR} strokeOpacity="0.5" strokeWidth="1" />
      <circle cx={cx} cy={cy} r={size} fill={MISS_COLOR} stroke="#fff" strokeWidth="1.5" />
    </g>
  );
}

export default function LineChart({ rows, series, unit, title, verdicts = [], focus = "all", hover = null, onHover = () => {} }) {
  const wrap = useRef(null);
  const plot = useRef(null);
  const [available, setAvailable] = useState(640);
  const setHover = onHover;

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setAvailable(Math.max(280, entry.contentRect.width)));
    observer.observe(wrap.current);
    return () => observer.disconnect();
  }, []);

  const last = rows.length - 1;
  const width = Math.max(available, MARGIN.left + MARGIN.right + rows.length * DAY_WIDTH);
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  // The scale zooms to the data instead of starting at zero, so day-to-day differences are visible.
  const values = rows.flatMap((row) => series.map((s) => row[s.key]));
  const low = Math.min(...values), high = Math.max(...values, 0.1);
  const span = Math.max(high - low, high * 0.2, 0.1);
  const step = niceStep(span * 1.25, 8); // about eight gridlines so values are easy to read off
  const bottom = Math.max(0, Math.floor((low - span * 0.12) / step) * step);
  const top = Math.ceil((high + span * 0.08) / step) * step;
  const ticks = Array.from({ length: Math.round((top - bottom) / step) + 1 }, (_, i) => bottom + i * step);
  const x = (index) => MARGIN.left + (rows.length > 1 ? (index / last) * innerWidth : innerWidth / 2);
  const y = (value) => MARGIN.top + innerHeight - ((value - bottom) / (top - bottom)) * innerHeight;

  const curves = Object.fromEntries(series.map((s) => {
    const points = rows.map((row, index) => [x(index), y(row[s.key])]);
    return [s.key, { start: points[0], segments: smooth(points) }];
  }));
  const [first, second] = series;
  const band = rows.length > 1 && first && second
    ? `${linePath(curves[first.key].start, curves[first.key].segments)} L${fmt(curves[second.key].segments[last - 1].p[0])},${fmt(curves[second.key].segments[last - 1].p[1])} ${reversed(curves[second.key].start, curves[second.key].segments)} Z`
    : null;

  // End-of-line labels, nudged apart when the two lines finish close together.
  const ends = series.map((s) => ({ ...s, y: y(rows[last][s.key]) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i += 1) {
    if (ends[i].y - ends[i - 1].y < LABEL_GAP) ends[i].y = ends[i - 1].y + LABEL_GAP;
  }

  function pick(clientX) {
    const rect = plot.current.getBoundingClientRect();
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
  const marked = verdicts.length === rows.length;

  return (
    <figure className="chart">
      <div className="chart-legend" aria-hidden="true">
        {series.map((s) => (
          <span key={s.key} className="chart-legend-item">
            <svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? "5 3" : undefined} strokeLinecap="round" /></svg>
            {s.label}
          </span>
        ))}
        {marked && LEGEND.map(([kind, label]) => (
          <span key={kind} className="chart-legend-item">
            <svg width="18" height="18"><Marker kind={kind} cx={9} cy={9} size={4.5} /></svg>
            {label}
          </span>
        ))}
      </div>
      <div className="chart-scroll" ref={wrap}>
        <div
          ref={plot}
          className="chart-plot"
          style={{ width }}
          tabIndex={0}
          role="img"
          aria-label={`${title}. Use the left and right arrow keys to read each service.`}
          onPointerMove={(event) => pick(event.clientX)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKeyDown}
          onBlur={() => setHover(null)}
        >
          <svg width={width} height={HEIGHT} className="chart-svg">
            <defs>
              <linearGradient id="chart-band" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#ff7a1a" stopOpacity="0.2" />
                <stop offset="1" stopColor="#ff7a1a" stopOpacity="0.1" />
              </linearGradient>
            </defs>

            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={y(tick)} y2={y(tick)} className={tick === bottom ? "chart-baseline" : "chart-grid"} />
                <text x={MARGIN.left - 8} y={y(tick)} className="chart-tick" textAnchor="end" dominantBaseline="middle">
                  {Number.isInteger(tick) ? tick : tick.toFixed(1)}
                </text>
              </g>
            ))}
            <text x={MARGIN.left - 8} y={MARGIN.top - 12} className="chart-tick" textAnchor="end">{unit}</text>

            {/* Every day gets its own label; the month is added when it changes. */}
            {rows.map((row, index) => {
              const date = parseDate(row.date);
              const newMonth = date && (index === 0 || parseDate(rows[index - 1].date)?.getMonth() !== date.getMonth());
              return (
                <g key={index} className={hover === index ? "chart-day is-active" : "chart-day"}>
                  <text x={x(index)} y={HEIGHT - 28} className="chart-tick" textAnchor="middle">{date ? date.getDate() : row.date}</text>
                  {newMonth && <text x={x(index)} y={HEIGHT - 10} className="chart-month" textAnchor="middle">{date.toLocaleDateString(undefined, { month: "short" })}</text>}
                </g>
              );
            })}

            {tipRow && <rect x={x(hover) - Math.min(DAY_WIDTH, innerWidth / Math.max(1, last)) / 2} y={MARGIN.top} width={Math.min(DAY_WIDTH, innerWidth / Math.max(1, last))} height={innerHeight} className="chart-column" />}

            {band && <path d={band} fill="url(#chart-band)" style={{ opacity: focus === "hit" ? 0.35 : 1 }} />}

            {series.map((s) => (
              <path
                key={s.key}
                d={linePath(curves[s.key].start, curves[s.key].segments)}
                fill="none"
                stroke={s.color}
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? "6 5" : undefined}
              />
            ))}

            {marked && rows.map((row, index) => (
              <Marker key={`mark-${index}`} kind={verdicts[index]} cx={x(index)} cy={y(row.actual)}
                dim={focus !== "all" && (focus === "hit") !== (verdicts[index] === "hit")} />
            ))}
            {rows.length === 1 && series.map((s) => (
              <circle key={s.key} cx={x(0)} cy={y(rows[0][s.key])} r="4" fill={s.color} stroke="#fff" strokeWidth="2" />
            ))}
            {ends.map((s) => (
              <text key={s.key} x={x(last) + 12} y={s.y} className="chart-end-label" dominantBaseline="middle">{s.label}</text>
            ))}

            {tipRow && series.map((s) => (
              <circle key={s.key} cx={x(hover)} cy={y(tipRow[s.key])} r="5" fill={s.color} stroke="#fff" strokeWidth="2" />
            ))}
          </svg>

        </div>
      </div>
    </figure>
  );
}
