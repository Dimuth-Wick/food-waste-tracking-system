import { useEffect, useState } from "react";

// The foods the cameras look for, with the weight of one piece. Edited here, saved for every station.
export default function FoodList({ url, onSaved }) {
  const [open, setOpen] = useState(false);
  const [foods, setFoods] = useState(null);
  const [dishes, setDishes] = useState([]);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || foods) return;
    fetch(url).then((response) => response.json()).then((data) => {
      setFoods(data.foods.filter((food) => food.station === null));
      setDishes(data.dishes);
    }).catch(() => setMessage({ ok: false, text: "The food list could not be loaded." }));
  }, [open, foods, url]);

  function change(index, key, value) {
    setFoods((current) => current.map((food, i) => (i === index ? { ...food, [key]: value } : food)));
  }

  async function save() {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      const response = await fetch(url, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(foods.map((food) => ({ ...food, kg_per_piece: Number(food.kg_per_piece), dish: food.dish || null }))),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setErrors(data.fields || {});
        setMessage({ ok: false, text: data.error || "The list could not be saved." });
        return;
      }
      setFoods(data.foods.filter((food) => food.station === null));
      setMessage({ ok: true, text: "Saved. New photos are counted with this list." });
      onSaved();
    } catch {
      setMessage({ ok: false, text: "The server did not respond." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="sheet cc-foods" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span>Foods the cameras look for</span>
        <small>Every photo is checked for each of these. Set the weight of one piece so leftovers become kilograms.</small>
      </summary>
      {!foods && !message && <p className="cc-muted">Loading…</p>}
      {foods && (
        <>
          <div className="table-scroll">
            <table className="cc-food-table">
              <thead>
                <tr><th scope="col">The camera looks for</th><th scope="col">Menu dish (for the forecast)</th><th scope="col" className="numeric">One piece weighs</th><th scope="col">In use</th></tr>
              </thead>
              <tbody>
                {foods.map((food, index) => (
                  <tr key={food.id ?? `new-${index}`} className={food.active ? undefined : "is-off"}>
                    <td>
                      <input value={food.count_label} maxLength={40} aria-label="What the camera looks for"
                        onChange={(event) => change(index, "count_label", event.target.value)} />
                      {errors[`${index}.count_label`] && <small className="cc-error">{errors[`${index}.count_label`]}</small>}
                    </td>
                    <td>
                      <select value={food.dish ?? ""} aria-label="Menu dish" onChange={(event) => change(index, "dish", event.target.value)}>
                        <option value="">None</option>
                        {dishes.map((dish) => <option key={dish} value={dish}>{dish}</option>)}
                      </select>
                    </td>
                    <td className="numeric">
                      <span className="cc-unit"><input type="number" min="0" step="0.005" value={food.kg_per_piece} aria-label="Weight of one piece in kilograms"
                        onChange={(event) => change(index, "kg_per_piece", event.target.value)} /> kg</span>
                      {errors[`${index}.kg_per_piece`] && <small className="cc-error">{errors[`${index}.kg_per_piece`]}</small>}
                    </td>
                    <td><input type="checkbox" checked={food.active} aria-label="In use" onChange={(event) => change(index, "active", event.target.checked)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="cc-foods-actions">
            <button type="button" className="button button-secondary"
              onClick={() => setFoods((current) => [...current, { id: null, count_label: "", dish: null, kg_per_piece: 0.05, active: true, station: null }])}>
              Add a food
            </button>
            <button type="button" className="button button-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save the list"}</button>
          </div>
        </>
      )}
      {message && <p className={message.ok ? "cc-message" : "inline-error"} role="status">{message.text}</p>}
    </details>
  );
}
