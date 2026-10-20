import { useEffect, useState } from "react";

const kg = (value) => `${value.toFixed(2)} kg`;

function guessMeal(hour) {
  return hour < 11 ? "Breakfast" : hour < 16 ? "Lunch" : "Dinner";
}

function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// Suggest the menu item from what was counted: "bread roll" suggests "Bread".
function guessFood(label, foods) {
  const words = (label || "").toLowerCase().split(/\s+/).filter(Boolean);
  return foods.find((food) => words.some((word) => food.toLowerCase().includes(word))) || "";
}

const asCount = (value) => (value === "" ? NaN : Number(value));

export default function SaveMealCheck({ settings, counts, onShowPhoto }) {
  const [meal, setMeal] = useState(() => guessMeal(new Date().getHours()));
  const [endedAt, setEndedAt] = useState(() => `${today()}T${settings?.mealEnds[guessMeal(new Date().getHours())] ?? "10:00"}`);
  const [timeEdited, setTimeEdited] = useState(false);
  const [food, setFood] = useState("");
  const [foodEdited, setFoodEdited] = useState(false);
  const [weight, setWeight] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [guests, setGuests] = useState("");
  const [ranOut, setRanOut] = useState(false);
  const [short, setShort] = useState("");
  const [areaId, setAreaId] = useState(settings?.defaultAreaId ?? "");
  const [reasonId, setReasonId] = useState(settings?.defaultReasonId ?? "");
  const [status, setStatus] = useState("idle"); // idle | saving | saved
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(null);

  // The photo counts fill in the numbers; staff can still correct them.
  useEffect(() => { if (counts.start) setStart(String(counts.start.count)); }, [counts.start]);
  useEffect(() => { if (counts.end) setEnd(String(counts.end.count)); }, [counts.end]);
  useEffect(() => {
    const label = counts.start?.label || counts.end?.label;
    if (!foodEdited && settings && label) setFood(guessFood(label, settings.foodItems));
  }, [counts.start, counts.end, foodEdited, settings]);
  // Reuse the weight per piece saved last time for this food.
  useEffect(() => {
    const known = settings?.pieceWeights[food];
    setWeight(known ? String(known) : "");
  }, [food, settings]);

  if (!settings) {
    return (
      <section className="sheet mc-save" id="mc-save">
        <h2>Save the meal check</h2>
        <p className="inline-error" role="alert">Saving needs the local database. Initialize it, then reload this page. Counting still works.</p>
      </section>
    );
  }

  const startN = asCount(start), endN = asCount(end), weightN = Number(weight), shortN = ranOut ? asCount(short) : 0;
  const ready = Number.isInteger(startN) && Number.isInteger(endN) && endN <= startN && weightN > 0;
  const eaten = ready ? (startN - endN) * weightN : null;
  const leftover = ready ? endN * weightN : null;
  const shortKg = ready && Number.isInteger(shortN) ? shortN * weightN : 0;
  const waiting = !Number.isInteger(startN) || !Number.isInteger(endN)
    ? "Needs the start and end counts"
    : endN > startN ? "More pieces at the end than at the start" : "Needs the weight of one piece";

  function chooseMeal(value) {
    setMeal(value);
    if (!timeEdited) setEndedAt(`${endedAt.slice(0, 10) || today()}T${settings.mealEnds[value]}`);
  }

  async function save(event) {
    event.preventDefault();
    setStatus("saving");
    setErrors({});
    setMessage("");
    try {
      const response = await fetch(settings.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          food_item: food, count_label: counts.start?.label || counts.end?.label || "",
          meal_type: meal, ended_at: endedAt, area_id: Number(areaId), reason_id: Number(reasonId),
          start_count: startN, end_count: endN, short_count: ranOut ? shortN : 0,
          kg_per_piece: weightN, guest_count: asCount(guests),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setErrors(data.fields || {});
        setMessage(data.error || "The meal check could not be saved.");
        setStatus("idle");
        return;
      }
      setSaved(data);
      setStatus("saved");
    } catch {
      setMessage("The server did not respond. Check that the app is still running.");
      setStatus("idle");
    }
  }

  if (status === "saved") {
    return (
      <section className="sheet mc-save mc-saved" id="mc-save" aria-live="polite">
        <h2>Meal check saved</h2>
        <p>
          {saved.waste_kg > 0 ? <><strong>{kg(saved.waste_kg)}</strong> of {food.toLowerCase()} was added to the waste records. </> : "Nothing was left over, so no waste was recorded. "}
          {saved.short_kg > 0 && <><strong>{kg(saved.short_kg)}</strong> was recorded as ran out. </>}
          <strong>{kg(saved.eaten_kg)}</strong> eaten by {guests} guests now counts toward the meal forecast.
        </p>
        <div className="mc-saved-actions">
          <a className="button button-primary" href={saved.overview_url}>Open the waste overview</a>
          <a className="button button-secondary" href={saved.forecast_url}>See the meal forecast</a>
          <button type="button" className="link-button" onClick={() => window.location.reload()}>Count another meal</button>
        </div>
      </section>
    );
  }

  const field = (name) => (errors[name] ? { "aria-invalid": true, "aria-describedby": `mc-${name}-error` } : {});
  const problem = (name) => errors[name] && <small className="mc-error" id={`mc-${name}-error`}>{errors[name]}</small>;

  return (
    <form className="sheet mc-save" id="mc-save" onSubmit={save} noValidate>
      <div className="sheet-heading">
        <h2>Save the meal check</h2>
        <span className="sheet-note">Leftovers become waste; what was eaten updates the forecast</span>
      </div>

      <div className="mc-grid">
        <fieldset className="mc-field mc-wide">
          <legend>Meal</legend>
          <div className="mc-segment">
            {settings.mealTypes.map((name) => (
              <button key={name} type="button" aria-pressed={meal === name} onClick={() => chooseMeal(name)}>{name}</button>
            ))}
          </div>
        </fieldset>

        <label className="mc-field">
          <span>Food item</span>
          <select className="fc-input" value={food} onChange={(e) => { setFood(e.target.value); setFoodEdited(true); }} {...field("food_item")}>
            <option value="">Choose the dish</option>
            {settings.foodItems.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          {problem("food_item")}
        </label>

        <label className="mc-field">
          <span>Meal ended</span>
          <input className="fc-input" type="datetime-local" value={endedAt} onChange={(e) => { setEndedAt(e.target.value); setTimeEdited(true); }} {...field("ended_at")} />
          {problem("ended_at")}
        </label>

        <label className="mc-field">
          <span>Pieces at the start</span>
          <input className="fc-input" type="number" min="0" step="1" inputMode="numeric" value={start} onChange={(e) => setStart(e.target.value)} {...field("start_count")} />
          {problem("start_count") || (!counts.start && <small><button type="button" className="link-button" onClick={() => onShowPhoto("start")}>Count the start photo</button> or type it.</small>)}
        </label>

        <label className="mc-field">
          <span>Pieces left at the end</span>
          <input className="fc-input" type="number" min="0" step="1" inputMode="numeric" value={end} onChange={(e) => setEnd(e.target.value)} {...field("end_count")} />
          {problem("end_count") || (!counts.end && <small><button type="button" className="link-button" onClick={() => onShowPhoto("end")}>Count the end photo</button> or type it.</small>)}
        </label>

        <label className="mc-field">
          <span>Weight of one piece</span>
          <span className="mc-unit"><input className="fc-input" type="number" min="0" step="any" inputMode="decimal" placeholder="0.060" value={weight} onChange={(e) => setWeight(e.target.value)} {...field("kg_per_piece")} /><em>kg</em></span>
          {problem("kg_per_piece") || <small>{settings.pieceWeights[food] ? "Saved from last time. Change it if the size differs." : "Weigh a few pieces and divide. It is remembered for this dish."}</small>}
        </label>

        <label className="mc-field">
          <span>Guests served</span>
          <input className="fc-input" type="number" min="1" step="1" inputMode="numeric" value={guests} onChange={(e) => setGuests(e.target.value)} {...field("guest_count")} />
          {problem("guest_count")}
        </label>

        <label className="mc-field">
          <span>Area</span>
          <select className="fc-input" value={areaId} onChange={(e) => setAreaId(e.target.value)} {...field("area_id")}>
            {settings.areas.map((area) => <option key={area.id} value={area.id}>{area.name}</option>)}
          </select>
          {problem("area_id")}
        </label>

        <label className="mc-field">
          <span>Reason for the leftovers</span>
          <select className="fc-input" value={reasonId} onChange={(e) => setReasonId(e.target.value)} {...field("reason_id")}>
            {settings.reasons.map((reason) => <option key={reason.id} value={reason.id}>{reason.name}</option>)}
          </select>
          {problem("reason_id")}
        </label>

        <div className="mc-field mc-wide">
          <label className="mc-check">
            <input type="checkbox" checked={ranOut} onChange={(e) => setRanOut(e.target.checked)} />
            The food ran out before the meal ended
          </label>
          {ranOut && (
            <label className="mc-short">
              <span>About how many more pieces were needed?</span>
              <input className="fc-input" type="number" min="0" step="1" inputMode="numeric" value={short} onChange={(e) => setShort(e.target.value)} {...field("short_count")} />
              {problem("short_count")}
            </label>
          )}
        </div>
      </div>

      <dl className="mc-summary" aria-live="polite">
        <div><dt>Eaten</dt><dd>{eaten === null ? "–" : kg(eaten)}<small>{ready ? `${startN - endN} pieces` : waiting}</small></dd></div>
        <div className="is-waste"><dt>Saved as waste</dt><dd>{leftover === null ? "–" : kg(leftover)}<small>{ready ? `${endN} pieces left` : " "}</small></dd></div>
        {ranOut && <div className="is-short"><dt>Ran out</dt><dd>{shortKg ? `−${kg(shortKg)}` : "–"}<small>{shortN ? `${shortN} pieces short` : " "}</small></dd></div>}
      </dl>

      {message && <p className="inline-error" role="alert">{message}</p>}
      <button className="wide-button mc-submit" type="submit" disabled={status === "saving"}>
        {status === "saving" ? "Saving…" : "Save to waste records and forecast"}
      </button>
    </form>
  );
}
