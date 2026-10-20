import { useEffect, useRef, useState } from "react";

import History from "./History.jsx";

const DEBOUNCE_MS = 300;
const GUEST_STEP = 10;
const MAX_GUESTS = 2000;

const kg = (value) => value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export default function Forecast({ settings }) {
  const [meal, setMeal] = useState("");
  const [food, setFood] = useState("");
  const [guestText, setGuestText] = useState("");
  const [forecast, setForecast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);

  const guests = Number(guestText);
  const guestsValid = guestText !== "" && Number.isFinite(guests) && guests > 0 && guests <= MAX_GUESTS;
  const ready = meal && food && guestsValid;
  const missing = [!meal && "a meal", !food && "a food item", !guestsValid && "the guest count"].filter(Boolean);

  // Re-forecast shortly after any input changes.
  useEffect(() => {
    if (!ready) return undefined;
    const timer = setTimeout(async () => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setBusy(true);
      try {
        const response = await fetch(settings.predictUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ meal_type: meal, food_item: food, guest_count: guests }),
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const fields = data.fields ? ` ${Object.values(data.fields).join(" ")}` : "";
          throw new Error((data.error || "The forecast failed.") + fields);
        }
        setForecast({ ...data, meal, food, guests });
        setError("");
      } catch (failure) {
        if (failure.name === "AbortError") return;
        setError(failure.message === "Failed to fetch"
          ? "The server did not respond. Check that the app is still running."
          : failure.message);
      }
      setBusy(false);
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [ready, meal, food, guests, settings.predictUrl]);

  function stepGuests(direction) {
    const current = guestsValid ? guests : 0;
    const next = Math.min(MAX_GUESTS, Math.max(GUEST_STEP, Math.round(current / GUEST_STEP) * GUEST_STEP + direction * GUEST_STEP));
    setGuestText(String(next));
  }

  const isCurrent = forecast && ready && forecast.meal === meal && forecast.food === food && forecast.guests === guests;

  return (
    <>
      <div className="mf-layout">
        <section className="sheet mf-inputs" aria-labelledby="mf-inputs-title">
          <h2 id="mf-inputs-title" className="visually-hidden">Service details</h2>

          <fieldset className="mf-fieldset">
            <legend className="field-label">Meal</legend>
            <div className="mf-segments">
              {settings.mealTypes.map((option) => (
                <button key={option} type="button" className="mf-segment" aria-pressed={meal === option} onClick={() => setMeal(option)}>
                  {option}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="mf-fieldset">
            <legend className="field-label">Food item</legend>
            <div className="chips mf-foods">
              {settings.foodItems.map((option) => (
                <button key={option} type="button" className="chip" aria-pressed={food === option} onClick={() => setFood(option)}>
                  {option}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mf-fieldset">
            <label className="field-label" htmlFor="mf-guests">Expected guests</label>
            <div className="mf-guests">
              <button type="button" className="mf-step" aria-label={`${GUEST_STEP} fewer guests`} onClick={() => stepGuests(-1)}>−</button>
              <input
                id="mf-guests"
                className="mf-guest-input"
                type="number"
                inputMode="numeric"
                min="1"
                max={MAX_GUESTS}
                placeholder="0"
                value={guestText}
                onChange={(event) => setGuestText(event.target.value)}
                aria-invalid={guestText !== "" && !guestsValid}
              />
              <button type="button" className="mf-step" aria-label={`${GUEST_STEP} more guests`} onClick={() => stepGuests(1)}>+</button>
              <span className="mf-guest-unit">guests</span>
            </div>
            {guestText !== "" && !guestsValid && (
              <p className="mf-field-error">Enter a number from 1 to {MAX_GUESTS.toLocaleString()}.</p>
            )}
          </div>
        </section>

        <section className={`stage mf-readout${busy ? " is-busy" : ""}`} aria-labelledby="mf-readout-title" aria-live="polite">
          {forecast ? (
            <div className={`mf-answer${isCurrent ? "" : " is-stale"}`}>
              <h2 id="mf-readout-title" className="mf-readout-title">
                Prepare for {forecast.guests.toLocaleString()} guests at {forecast.meal.toLowerCase()}
              </h2>
              <p className="mf-amount">{kg(forecast.recommended_quantity)}<span>kg</span></p>
              <p className="mf-food">of {forecast.food.toLowerCase()}</p>

              <div className="mf-split" aria-hidden="true">
                <span className="mf-split-eaten" style={{ flexGrow: forecast.predicted_consumption }} />
                <span className="mf-split-margin" style={{ flexGrow: forecast.safety_margin }} />
              </div>
              <dl className="mf-breakdown">
                <div>
                  <dt><span className="mf-key mf-key-eaten" aria-hidden="true" />Expected to be eaten</dt>
                  <dd>{kg(forecast.predicted_consumption)} kg</dd>
                </div>
                <div>
                  <dt><span className="mf-key mf-key-margin" aria-hidden="true" />Safety margin (10%)</dt>
                  <dd>{kg(forecast.safety_margin)} kg</dd>
                </div>
                <div>
                  <dt>Per guest</dt>
                  <dd>{Math.round((forecast.recommended_quantity / forecast.guests) * 1000)} g</dd>
                </div>
              </dl>
            </div>
          ) : (
            <div className="mf-waiting">
              <h2 id="mf-readout-title" className="mf-readout-title">How much to prepare</h2>
              <p>Choose {missing.join(", ").replace(/, ([^,]*)$/, " and $1")}, and the forecast appears here.</p>
            </div>
          )}
          {error && <p className="mf-readout-error" role="alert">{error}</p>}
          <p className="mf-readout-note">Based on past service. Kitchen staff should review it before preparing food.</p>
        </section>
      </div>

      <History url={settings.historyUrl} />
    </>
  );
}
