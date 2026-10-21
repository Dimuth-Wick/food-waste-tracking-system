import { useEffect, useState } from "react";

import { plural } from "../shared/text.js";

const kg = (value) => `${value.toFixed(2)} kg`;
const money = (value, symbol) => `${symbol} ${Math.round(value).toLocaleString("en-US")}`;

export function photoTime(iso, timezone) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: timezone });
}

// "8 eggs, 3 donuts" from {egg: 8, donut: 3, apple: 0}.
export function countsText(counts) {
  const found = Object.entries(counts ?? {}).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);
  return found.length ? found.map(([label, count]) => `${count} ${plural(label, count)}`).join(", ") : "Nothing found";
}

const PHOTO_STATE = {
  pending: "Counting…",
  needs_setup: "No foods set up",
  failed: "Count failed",
};

function Side({ title, time, side, kind, timezone, onOpenPhoto }) {
  const counting = side.photos.filter((photo) => photo.countStatus === "pending").length;
  return (
    <div className={`cc-side is-${kind}`}>
      <div className="cc-side-heading">
        <h5>{title}{time && <small>{time}</small>}</h5>
        <p className="cc-side-counts">
          {side.photos.length === 0 ? "No photos yet"
            : side.combined ? countsText(side.combined)
              : counting ? "Counting…" : "Not counted"}
        </p>
        {side.combined && side.photos.length > 1 && (
          <p className="cc-side-rule">{kind === "start" ? "Highest" : "Lowest"} count of {side.photos.length} photos</p>
        )}
      </div>
      {side.photos.length > 0 && (
        <ul className="cc-photos">
          {side.photos.map((photo) => (
            <li key={photo.id}>
              {photo.url ? (
                <button type="button" className="cc-thumb" onClick={() => onOpenPhoto(photo)}
                  aria-label={`Open the ${photoTime(photo.time, timezone)} photo: ${countsText(photo.counts)}`}>
                  <img src={photo.url} alt="" loading="lazy" />
                  {PHOTO_STATE[photo.countStatus] && <span className={`cc-thumb-state is-${photo.countStatus}`}>{PHOTO_STATE[photo.countStatus]}</span>}
                  {photo.countStatus === "counted" && (
                    <span className="cc-thumb-total">{Object.values(photo.counts).reduce((sum, n) => sum + n, 0)}</span>
                  )}
                </button>
              ) : (
                <div className="cc-thumb is-missing" title={photo.error || undefined}>
                  {photo.status === "failed" ? "Camera offline" : "Photo missing"}
                </div>
              )}
              <span className="cc-photo-time">{photoTime(photo.time, timezone)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// One station's start and end photos for a meal, and its meal check.
export default function StationCard({ meal, station, timezone, mealCheck, confirmUrl, dayUrl, currency, onOpenPhoto, onSaved }) {
  const draft = station.draft;
  return (
    <article className="sheet cc-station">
      <header className="cc-station-heading">
        <h4>{station.station}</h4>
        {draft?.status === "waiting" && <span className="cc-badge is-waiting">Waiting for confirmation</span>}
        {draft?.status === "confirmed" && <span className="cc-badge is-confirmed">Confirmed</span>}
      </header>
      <div className="cc-sides">
        <Side title="Start of meal" time={meal.times?.start} side={station.start} kind="start" timezone={timezone} onOpenPhoto={onOpenPhoto} />
        <Side title="End of meal" time={meal.times?.end} side={station.end} kind="end" timezone={timezone} onOpenPhoto={onOpenPhoto} />
      </div>
      {draft?.status === "waiting" && (
        <DraftForm draft={draft} mealCheck={mealCheck} currency={currency} url={confirmUrl.replace("{id}", draft.id)} onSaved={onSaved} />
      )}
      {draft?.status === "confirmed" && <Confirmed draft={draft} dayUrl={dayUrl} currency={currency} />}
      {!draft && (
        <p className="cc-muted cc-waiting">
          {!station.end.photos.length ? `The meal check appears here once the end photos${meal.times ? ` (${meal.times.end})` : ""} are counted.`
            : !station.start.photos.length ? "There are no start photos for this meal, so it cannot be checked."
              : "The meal check appears here once both sides are counted."}
        </p>
      )}
    </article>
  );
}

function Confirmed({ draft, dayUrl, currency }) {
  const waste = draft.foods.reduce((sum, food) => sum + food.wasteKg, 0);
  const eaten = draft.foods.reduce((sum, food) => sum + food.eatenKg, 0);
  const lost = draft.foods.reduce((sum, food) => sum + (food.wasteValue ?? 0), 0);
  return (
    <div className="cc-confirmed">
      <p>
        Saved for <strong>{draft.guests}</strong> guests: <strong>{kg(eaten)}</strong> eaten and <strong>{kg(waste)}</strong> left over as waste (about <strong>{money(lost, currency)}</strong>)
        ({draft.foods.map((food) => `${food.end} of ${food.start} ${plural(food.label, food.start)}`).join(", ")} left).
      </p>
      <a className="text-link" href={dayUrl}>See it on the day's page</a>
    </div>
  );
}

function DraftForm({ draft, mealCheck, currency, url, onSaved }) {
  const [lines, setLines] = useState(() => draft.foods.map((food) => ({ ...food, short: 0 })));
  const [showAll, setShowAll] = useState(false);
  const [guests, setGuests] = useState("");
  const [areaId, setAreaId] = useState(mealCheck?.defaultAreaId ?? "");
  const [reasonId, setReasonId] = useState(mealCheck?.defaultReasonId ?? "");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");

  // New counts arrive while the draft waits (more photos counted): take them unless staff changed a line.
  useEffect(() => {
    setLines((current) => draft.foods.map((food) => {
      const edited = current.find((line) => line.label === food.label && line.edited);
      return edited ?? { ...food, short: 0 };
    }));
  }, [draft.foods]);

  if (!mealCheck) return <p className="inline-error">Saving needs the local database. Initialize it, then reload this page.</p>;

  const shown = showAll ? lines : lines.filter((line) => line.start || line.end || line.edited);
  const eaten = lines.reduce((sum, line) => sum + Math.max(0, line.start - line.end) * line.kgPerPiece, 0);
  const waste = lines.reduce((sum, line) => sum + line.end * line.kgPerPiece, 0);
  const lost = lines.reduce((sum, line) => sum + line.end * line.kgPerPiece * line.pricePerKg, 0);

  function change(label, key, value) {
    const number = value === "" ? 0 : Math.max(0, Math.floor(Number(value)) || 0);
    setLines((current) => current.map((line) => (line.label === label ? { ...line, [key]: number, edited: true } : line)));
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setErrors({});
    setMessage("");
    try {
      const response = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          guest_count: guests === "" ? null : Number(guests), area_id: Number(areaId), reason_id: Number(reasonId),
          foods: lines.map((line) => ({ label: line.label, start_count: line.start, end_count: line.end, short_count: line.short })),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setErrors(data.fields || {});
        setMessage(data.error || "The meal check could not be saved.");
        return;
      }
      await onSaved();
    } catch {
      setMessage("The server did not respond. Check that the app is still running.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="cc-draft" onSubmit={save} noValidate>
      <div className="table-scroll">
        <table className="cc-draft-table">
          <thead>
            <tr><th scope="col">Food</th><th scope="col" className="numeric">At the start</th><th scope="col" className="numeric">Left at the end</th><th scope="col" className="numeric">Ran short</th><th scope="col" className="numeric">Eaten</th><th scope="col" className="numeric">Saved as waste</th><th scope="col" className="numeric">Waste value</th></tr>
          </thead>
          <tbody>
            {shown.map((line) => (
              <tr key={line.label} className={errors[`foods.${line.label}`] ? "has-error" : undefined}>
                <th scope="row">
                  {line.label[0].toUpperCase() + line.label.slice(1)}
                  {line.dish && <small>{line.dish}</small>}
                  {errors[`foods.${line.label}`] && <small className="cc-error">{errors[`foods.${line.label}`]}</small>}
                </th>
                {["start", "end", "short"].map((key) => (
                  <td key={key} className="numeric">
                    <input type="number" min="0" step="1" inputMode="numeric" value={line[key]}
                      aria-label={`${line.label}: ${key === "start" ? "pieces at the start" : key === "end" ? "pieces left at the end" : "pieces short"}`}
                      onChange={(event) => change(line.label, key, event.target.value)} />
                  </td>
                ))}
                <td className="numeric">{kg(Math.max(0, line.start - line.end) * line.kgPerPiece)}</td>
                <td className="numeric">{kg(line.end * line.kgPerPiece)}</td>
                <td className="numeric">{money(line.end * line.kgPerPiece * line.pricePerKg, currency)}</td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={7} className="cc-muted">No food was counted. Show every food to type the counts.</td></tr>}
          </tbody>
          <tfoot>
            <tr><th scope="row">Total</th><td colSpan={3} /><td className="numeric">{kg(eaten)}</td><td className="numeric">{kg(waste)}</td><td className="numeric">{money(lost, currency)}</td></tr>
          </tfoot>
        </table>
      </div>
      <label className="cc-check"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} /> Show every food, to add one the camera missed</label>
      {errors.foods && <p className="cc-error">{errors.foods}</p>}

      <div className="cc-draft-fields">
        <label>
          <span>Guests served</span>
          <input type="number" min="1" step="1" inputMode="numeric" value={guests} onChange={(event) => setGuests(event.target.value)}
            aria-invalid={errors.guest_count ? true : undefined} required />
          {errors.guest_count && <small className="cc-error">{errors.guest_count}</small>}
        </label>
        <label>
          <span>Area</span>
          <select value={areaId} onChange={(event) => setAreaId(event.target.value)}>
            {mealCheck.areas.map((area) => <option key={area.id} value={area.id}>{area.name}</option>)}
          </select>
        </label>
        <label>
          <span>Reason for the leftovers</span>
          <select value={reasonId} onChange={(event) => setReasonId(event.target.value)}>
            {mealCheck.reasons.map((reason) => <option key={reason.id} value={reason.id}>{reason.name}</option>)}
          </select>
        </label>
        <button type="submit" className="button button-primary" disabled={saving}>{saving ? "Saving…" : "Confirm meal check"}</button>
      </div>
      {message && <p className="inline-error" role="alert">{message}</p>}
    </form>
  );
}
