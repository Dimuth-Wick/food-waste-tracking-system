import { useEffect, useState } from "react";

import LineChart from "./LineChart.jsx";

// Validated with the dataviz palette checker against white: both pass
// lightness, chroma, colour-blind separation and 3:1 contrast.
export const SERIES = [
  { key: "actual", label: "Actual", color: "#0e7c57", dashed: false },
  { key: "predicted", label: "Predicted", color: "#c27f12", dashed: true },
];

export default function History({ url }) {
  const [state, setState] = useState({ status: "loading" });
  const [selected, setSelected] = useState(0);

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
                onClick={() => setSelected(index)}
              >
                {entry.food_item}
              </button>
            ))}
          </div>
          <div id="mf-history-panel" role="tabpanel" aria-labelledby={`mf-tab-${selected}`}>
            <Accuracy history={item.history} />
            <LineChart key={item.food_item} rows={item.history} series={SERIES} unit="kg" title={`${item.food_item}: actual and predicted amount eaten`} />
            <details className="mf-table-toggle">
              <summary>Show as a table</summary>
              <div className="table-scroll">
                <table>
                  <thead><tr><th scope="col">Date</th><th scope="col" className="numeric">Actual</th><th scope="col" className="numeric">Predicted</th><th scope="col" className="numeric">Difference</th></tr></thead>
                  <tbody>
                    {item.history.map((row, index) => (
                      <tr key={`${row.date}-${index}`}>
                        <td>{row.date}</td>
                        <td className="numeric">{row.actual.toFixed(2)} kg</td>
                        <td className="numeric">{row.predicted.toFixed(2)} kg</td>
                        <td className="numeric">{signed(row.predicted - row.actual)} kg</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        </>
      )}
    </section>
  );
}

function signed(value) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}

// One plain sentence on accuracy: average miss, and which way it leans.
function Accuracy({ history }) {
  const misses = history.map((row) => row.predicted - row.actual);
  const average = misses.reduce((sum, miss) => sum + Math.abs(miss), 0) / misses.length;
  const lean = misses.reduce((sum, miss) => sum + miss, 0) / misses.length;
  const direction = Math.abs(lean) < average * 0.25
    ? "with no clear lean either way"
    : lean > 0 ? "and it tends to predict too much" : "and it tends to predict too little";
  return (
    <p className="mf-accuracy">
      Over {history.length} services, the forecast was off by <strong>{average.toFixed(2)} kg</strong> on average, {direction}.
    </p>
  );
}
