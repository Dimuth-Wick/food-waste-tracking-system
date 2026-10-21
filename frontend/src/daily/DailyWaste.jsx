import { useEffect, useRef, useState } from "react";

const HEIGHT = 300;
const MARGIN = { top: 20, right: 92, bottom: 50, left: 52 };
const DAY_WIDTH = 28; // narrowest a day may get before the chart scrolls sideways

// Validated with the dataviz palette checker: a warm and a cool pole, safe for colour-blind readers.
const WASTE = "#d9480f";
const SHORT = "#1d6fb8";

const kg = (amount) => `${amount.toFixed(1)} kg`;
const money = (amount, symbol) => `${amount < 0 ? "-" : ""}${symbol} ${Math.round(Math.abs(amount)).toLocaleString("en-US")}`;
const tickText = (tick, isValue) => {
  if (isValue && Math.abs(tick) >= 1000) return `${+(tick / 1000).toFixed(1)}k`;
  return String(Number.isInteger(tick) ? tick : tick.toFixed(1));
};
const minus = (text) => text.replace("-", "−");

function niceStep(span, ticks = 4) {
  const raw = span / ticks;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 2.5, 5, 10].map((n) => n * power).find((n) => n >= raw) || power;
}

function parse(value) {
  return new Date(`${value}T00:00:00`);
}

function label(value) {
  return parse(value).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// A bar from the zero line with only its far end rounded, so it stays anchored to the baseline.
function bar(x, width, zero, end, radius = 4) {
  const top = Math.min(zero, end), height = Math.abs(end - zero);
  if (height < 0.5) return null;
  const r = Math.min(radius, height, width / 2), left = x - width / 2, right = x + width / 2;
  return end < zero
    ? `M${left},${zero} V${top + r} Q${left},${top} ${left + r},${top} H${right - r} Q${right},${top} ${right},${top + r} V${zero} Z`
    : `M${left},${zero} V${top + height - r} Q${left},${top + height} ${left + r},${top + height} H${right - r} Q${right},${top + height} ${right},${top + height - r} V${zero} Z`;
}

export default function DailyWaste({ settings }) {
  const currency = settings.currency || "Rs";
  const [mode, setMode] = useState("value");   // value (money) | weight (kg)
  const value = mode === "value";
  const rawDays = settings.days;
  // The same chart, drawn from either the money or the kilograms.
  const days = rawDays.map((d) => ({ date: d.date, waste: value ? d.waste_value : d.waste, short: value ? d.short_value : d.short }));
  const fmt = (amount) => (value ? money(amount, currency) : kg(amount));
  const unit = value ? currency : "kg";
  const wrap = useRef(null);
  const plot = useRef(null);
  const [available, setAvailable] = useState(640);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setAvailable(Math.max(280, entry.contentRect.width)));
    observer.observe(wrap.current);
    return () => observer.disconnect();
  }, []);

  const last = days.length - 1;
  const totalWaste = days.reduce((sum, d) => sum + d.waste, 0);
  const totalShort = days.reduce((sum, d) => sum + d.short, 0);
  const average = totalWaste / days.length;
  const peak = days.reduce((best, d) => (d.waste > best.waste ? d : best), days[0]);
  const shortDays = days.filter((d) => d.short > 0).length;

  const width = Math.max(available, MARGIN.left + MARGIN.right + days.length * DAY_WIDTH);
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const maxWaste = Math.max(...days.map((d) => d.waste), 0.5);
  const maxShort = Math.max(...days.map((d) => d.short), 0);
  const step = niceStep((maxWaste + maxShort) * 1.1, 5);
  const top = Math.ceil(maxWaste / step) * step;
  const bottom = maxShort > 0 ? -Math.ceil(maxShort / step) * step : 0;
  const ticks = Array.from({ length: Math.round((top - bottom) / step) + 1 }, (_, i) => bottom + i * step);
  const column = innerWidth / days.length;
  const x = (i) => MARGIN.left + (i + 0.5) * column;
  const y = (v) => MARGIN.top + innerHeight - ((v - bottom) / (top - bottom)) * innerHeight;
  const zero = y(0);
  const barWidth = Math.min(18, column * 0.62);

  function pick(clientX) {
    const rect = plot.current.getBoundingClientRect();
    setHover(Math.min(last, Math.max(0, Math.floor(((clientX - rect.left) - MARGIN.left) / column))));
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

  const day = hover === null ? null : days[hover];

  return (
    <div className="dw">
      <dl className="dw-stats">
        <div><dt>{value ? "Waste value" : "Thrown away"}</dt><dd>{fmt(totalWaste)}</dd></div>
        <div><dt>Daily average</dt><dd>{fmt(average)}</dd></div>
        <div><dt>Highest day</dt><dd>{peak.waste > 0 ? `${label(peak.date)} · ${fmt(peak.waste)}` : "None"}</dd></div>
        <div className={shortDays ? "has-short" : undefined}>
          <dt>Ran out of food</dt>
          <dd>{shortDays ? `${shortDays} ${shortDays === 1 ? "day" : "days"} · ${minus(fmt(-totalShort))}` : "No days"}</dd>
        </div>
      </dl>

      <div className="dw-mode" role="group" aria-label="Show the chart in">
        <button type="button" aria-pressed={value} onClick={() => setMode("value")}>Cost ({currency})</button>
        <button type="button" aria-pressed={!value} onClick={() => setMode("weight")}>Weight (kg)</button>
      </div>

      <div className="dw-bar">
        <div className="dw-legend" aria-hidden="true">
          <span><i style={{ background: WASTE }} />Thrown away (above zero)</span>
          <span><i style={{ background: SHORT }} />Ran out of food (below zero)</span>
          <span><svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" stroke="#557064" strokeWidth="2" strokeDasharray="4 3" /></svg>30-day average</span>
        </div>
        <p className="dw-detail" aria-live="polite">
          {day ? (
            <>
              <strong>{label(day.date)}</strong>
              <span><i style={{ background: WASTE }} />Thrown away <strong>{fmt(day.waste)}</strong></span>
              <span><i style={{ background: SHORT }} />Ran out <strong>{day.short ? minus(fmt(-day.short)) : fmt(0)}</strong></span>
            </>
          ) : "Point at a day to see its numbers."}
        </p>
      </div>

      <div className="dw-scroll" ref={wrap}>
        <div
          ref={plot}
          className="dw-plot"
          style={{ width }}
          tabIndex={0}
          role="img"
          aria-label={`Daily waste for the last ${days.length} days. Bars above zero are kilograms thrown away; bars below zero are days food ran out. Use the left and right arrow keys to read each day.`}
          onPointerMove={(event) => pick(event.clientX)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKeyDown}
          onBlur={() => setHover(null)}
        >
          <svg width={width} height={HEIGHT} className="dw-svg">
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={y(tick)} y2={y(tick)} className={tick === 0 ? "dw-zero" : "dw-grid"} />
                <text x={MARGIN.left - 8} y={y(tick)} className={tick === 0 ? "dw-tick is-zero" : "dw-tick"} textAnchor="end" dominantBaseline="middle">
                  {minus(tickText(tick, value))}
                </text>
              </g>
            ))}
            <text x={MARGIN.left - 8} y={MARGIN.top - 8} className="dw-tick" textAnchor="end">{unit}</text>

            {hover !== null && <rect x={MARGIN.left + hover * column} y={MARGIN.top} width={column} height={innerHeight} className="dw-column" />}

            {average > 0 && (
              <g>
                <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={y(average)} y2={y(average)} className="dw-average" />
                <text x={MARGIN.left + innerWidth + 8} y={y(average)} className="dw-average-label" dominantBaseline="middle">Average</text>
              </g>
            )}

            {days.map((d, i) => (
              <g key={d.date}>
                {d.waste > 0 && <path d={bar(x(i), barWidth, zero, y(d.waste))} fill={WASTE} />}
                {d.short > 0 && <path d={bar(x(i), barWidth, zero, y(-d.short))} fill={SHORT} />}
              </g>
            ))}

            {days.map((d, i) => {
              const date = parse(d.date);
              const newMonth = i === 0 || parse(days[i - 1].date).getMonth() !== date.getMonth();
              return (
                <g key={d.date} className={hover === i ? "dw-day is-active" : "dw-day"}>
                  <text x={x(i)} y={HEIGHT - 26} className="dw-tick" textAnchor="middle">{date.getDate()}</text>
                  {newMonth && <text x={x(i)} y={HEIGHT - 8} className="dw-month" textAnchor="middle">{date.toLocaleDateString(undefined, { month: "short" })}</text>}
                </g>
              );
            })}
          </svg>
        </div>
      </div>

      <details className="dw-table">
        <summary>Show as a table</summary>
        <div className="table-scroll">
          <table>
            <thead><tr><th scope="col">Date</th><th scope="col" className="numeric">Waste value</th><th scope="col" className="numeric">Thrown away</th><th scope="col" className="numeric">Ran out</th></tr></thead>
            <tbody>
              {[...rawDays].reverse().map((d) => (
                <tr key={d.date}>
                  <td>{parse(d.date).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td className="numeric">{d.waste_value ? money(d.waste_value, currency) : "–"}</td>
                  <td className="numeric">{d.waste ? kg(d.waste) : "–"}</td>
                  <td className="numeric">{d.short ? `${minus(kg(-d.short))} (${money(d.short_value, currency)})` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
