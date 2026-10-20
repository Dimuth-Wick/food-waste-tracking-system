import { useEffect, useState } from "react";

import LineChart from "./LineChart.jsx";

// Validated with the dataviz palette checker against white: both pass
// lightness, chroma, colour-blind separation and 3:1 contrast.
export const SERIES = [
  { key: "actual", label: "Actual", color: "#0a8a54", dashed: false },
  { key: "predicted", label: "Predicted", color: "#d9480f", dashed: true },
];

// A day counts as "on target" when the forecast was within this share of what was eaten.
export const TOLERANCE = 0.1;

export function verdict(row) {
  const miss = row.predicted - row.actual;
  if (Math.abs(miss) <= row.actual * TOLERANCE) return "hit";
  return miss > 0 ? "over" : "under";
}

export const VERDICT_TEXT = {
  hit: "On target",
  over: "Predicted too much",
  under: "Predicted too little",
};

export default function History({ url }) {
  const [state, setState] = useState({ status: "loading" });
  const [selected, setSelected] = useState(0);
  const [focus, setFocus] = useState("all"); // all | hit | miss
  const [meal, setMeal] = useState("all");   // all | Breakfast | Lunch | Dinner
  const [hover, setHover] = useState(null);   // index of the day being pointed at

  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "The history could not be loaded.");
        setState({ status: "ready", items: data.items ?? [] });
      })
      .catch((failure) => {
        if (failure.name !== "AbortError") {
          setState({ status: "error", message: failure.message === "Failed to fetch"
            ? "The server did not respond. Check that the app is still running."
            : failure.message });
        }
      });
    return () => controller.abort();
  }, [url]);

  const items = state.items ?? [];
  const item = items[selected];
  const history = item ? item.history.filter((row) => meal === "all" || row.meal_type === meal) : [];
  const mealCount = (name) => (item ? item.history.filter((row) => name === "all" || row.meal_type === name).length : 0);
  const verdicts = history.map(verdict);
  const hits = verdicts.filter((v) => v === "hit").length;
  const shows = (kind) => focus === "all" || (focus === "hit") === (kind === "hit");

  return (
    <section className="sheet mf-history" aria-labelledby="mf-history-title">
      <div className="sheet-heading">
        <h2 id="mf-history-title">How close past forecasts were</h2>
        {item && <span className="sheet-note">Up to 5 food items with recorded service details</span>}
      </div>

      {state.status === "loading" && <p className="mf-history-note" role="status">Loading past service…</p>}
      {state.status === "error" && <p className="inline-error" role="alert">{state.message}</p>}
      {state.status === "ready" && !item && (
        <p className="mf-history-note">
          No past records include a meal, food item, guest count and amount eaten yet. Once they do, this compares what was eaten with what the model would have predicted.
        </p>
      )}

      {item && (
        <>
          <div className="mf-tabs" role="tablist" aria-label="Food item">
            {items.map((entry, index) => (
              <button
                key={entry.food_item}
                type="button"
                role="tab"
                id={`mf-tab-${index}`}
                aria-selected={index === selected}
                aria-controls="mf-history-panel"
                className="mf-tab"
                onClick={() => { setSelected(index); setHover(null); }}
              >
                {entry.food_item}
              </button>
            ))}
          </div>
          <div id="mf-history-panel" role="tabpanel" aria-labelledby={`mf-tab-${selected}`}>
            <div className="mf-meals" role="group" aria-label="Meal">
              <span className="mf-meals-label">Meal</span>
              <div className="mf-focus">
                {[["all", "All meals"], ["Breakfast", "Breakfast"], ["Lunch", "Lunch"], ["Dinner", "Dinner"]].map(([key, label]) => (
                  <button key={key} type="button" className="mf-focus-button" aria-pressed={meal === key} disabled={mealCount(key) === 0}
                    onClick={() => { setMeal(key); setHover(null); }}>
                    {label}{key !== "all" && <span className="mf-count">{mealCount(key)}</span>}
                  </button>
                ))}
              </div>
            </div>
            {history.length === 0 ? (
              <p className="mf-history-note">No {meal === "all" ? "" : `${meal.toLowerCase()} `}records for {item.food_item} yet.</p>
            ) : (
            <>
            <Accuracy history={history} />
            <div className="mf-toolbar">
            <div className="mf-focus" role="group" aria-label="Highlight days">
              {[["all", `All ${verdicts.length} days`], ["hit", `On target (${hits})`], ["miss", `Off days (${verdicts.length - hits})`]].map(([key, label]) => (
                <button key={key} type="button" className="mf-focus-button" aria-pressed={focus === key} onClick={() => setFocus(key)}>{label}</button>
              ))}
            </div>
            <DayDetail row={hover === null ? null : history[hover]} kind={hover === null ? null : verdicts[hover]} />
            </div>
            <LineChart key={`${item.food_item}-${meal}`} rows={history} series={SERIES} unit="kg" verdicts={verdicts} focus={focus} hover={hover} onHover={setHover} title={`${item.food_item}: actual and predicted amount eaten`} />
            <details className="mf-table-toggle">
              <summary>Show as a table</summary>
              <div className="table-scroll">
                <table>
                  <thead><tr><th scope="col">Date</th><th scope="col" className="numeric">Actual</th><th scope="col" className="numeric">Predicted</th><th scope="col" className="numeric">Difference</th><th scope="col">Result</th></tr></thead>
                  <tbody>
                    {[...history.keys()].reverse().map((index) => [history[index], index]).map(([row, index]) => shows(verdicts[index]) && (
                      <tr key={`${row.date}-${index}`} className={verdicts[index] === "hit" ? undefined : "mf-off-day"}>
                        <td>{tableDate(row.date)}</td>
                        <td className="numeric">{row.actual.toFixed(2)} kg</td>
                        <td className="numeric">{row.predicted.toFixed(2)} kg</td>
                        <td className="numeric">{signed(row.predicted - row.actual)} kg</td>
                        <td><span className={`mf-result mf-result-${verdicts[index]}`}>{VERDICT_SHAPE[verdicts[index]]} {VERDICT_TEXT[verdicts[index]]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            </>
            )}
          </div>
        </>
      )}
    </section>
  );
}

// The pointed-at day's details, kept beside the filter buttons so they never cover the chart.
function DayDetail({ row, kind }) {
  if (!row) return <p className="mf-detail is-empty" aria-live="polite">Point at a day on the chart to see its details.</p>;
  const date = new Date(`${row.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return (
    <p className="mf-detail" aria-live="polite">
      <strong className="mf-detail-date">{date}</strong>
      <span className={`mf-result mf-result-${kind}`}>● {VERDICT_TEXT[kind]}</span>
      <span><span className="mf-detail-key mf-key-actual" />Actual <strong>{row.actual.toFixed(2)} kg</strong></span>
      <span><span className="mf-detail-key mf-key-predicted" />Predicted <strong>{row.predicted.toFixed(2)} kg</strong></span>
    </p>
  );
}

// Newest day first, written the way people say it.
function tableDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

const VERDICT_SHAPE = { hit: "●", over: "●", under: "●" };

function signed(value) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}

// Headline accuracy over the days shown: average miss in kg and as a share of what was eaten,
// how many days were on target, and which way the forecast leans.
function Accuracy({ history }) {
  const misses = history.map((row) => row.predicted - row.actual);
  const days = history.length;
  const averageKg = misses.reduce((sum, miss) => sum + Math.abs(miss), 0) / days;
  const averagePercent = history.reduce((sum, row, index) => sum + (row.actual > 0 ? Math.abs(misses[index]) / row.actual : 0), 0) / days * 100;
  const lean = misses.reduce((sum, miss) => sum + miss, 0) / days;
  const onTarget = history.filter((row) => verdict(row) === "hit").length;
  const leaning = Math.abs(lean) < averageKg * 0.25
    ? { label: "Balanced", note: "No clear lean either way" }
    : lean > 0
      ? { label: "Too much", note: `Predicts ${Math.abs(lean).toFixed(2)} kg too much on average` }
      : { label: "Too little", note: `Predicts ${Math.abs(lean).toFixed(2)} kg too little on average` };
  const tiles = [
    { label: "Average error", value: averageKg.toFixed(2), unit: "kg", note: `Per service, over ${days} days`, main: true },
    { label: "Average error", value: averagePercent.toFixed(1), unit: "%", note: "Of what was eaten" },
    { label: "Days on target", value: `${onTarget}`, unit: `of ${days}`, note: `Within ${TOLERANCE * 100}% of what was eaten` },
    { label: "Forecast leans", value: leaning.label, unit: "", note: leaning.note },
  ];
  return (
    <dl className="mf-stats" aria-label={`Forecast accuracy over ${days} services`}>
      {tiles.map((tile) => (
        <div key={tile.label + tile.unit} className={tile.main ? "mf-stat is-main" : "mf-stat"}>
          <dt>{tile.label}</dt>
          <dd><strong>{tile.value}</strong>{tile.unit && <span>{tile.unit}</span>}</dd>
          <dd className="mf-stat-note">{tile.note}</dd>
        </div>
      ))}
    </dl>
  );
}
