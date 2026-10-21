import { useCallback, useEffect, useState } from "react";

import FoodList from "./FoodList.jsx";
import PhotoViewer from "./PhotoViewer.jsx";
import StationCard from "./StationCard.jsx";
import "./captures.css";

const STATE_TEXT = { ok: "OK", offline: "Offline", none: "No photos yet" };

export function dayLabel(day, today) {
  const text = new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  return day === today ? `${text} (today)` : text;
}

function currentMeal(meals) {
  const clock = new Date().toTimeString().slice(0, 5);
  const started = meals.filter((meal) => meal.times && meal.times.start <= clock);
  return (started.at(-1) ?? meals.at(-1))?.meal ?? "";
}

// The buffet cameras' photos for one day, grouped by meal and station, with what was counted in each
// and the meal checks waiting for staff to add the guests and confirm.
export default function CameraCaptures({ camera, mealCheck }) {
  const [date, setDate] = useState("");
  const [view, setView] = useState(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState(null);
  const [captureMeal, setCaptureMeal] = useState("");
  const [capturing, setCapturing] = useState("");
  const [message, setMessage] = useState(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${camera.capturesUrl}${date ? `?date=${encodeURIComponent(date)}` : ""}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The photos could not be loaded.");
      setView(data);
      setError("");
    } catch (failure) {
      setError(failure.message === "Failed to fetch" ? "The server did not respond. Check that the app is still running." : failure.message);
    }
  }, [camera.capturesUrl, date]);

  // Refresh often while photos are being counted, and now and then otherwise for new captures.
  useEffect(() => {
    load();
    const timer = setInterval(load, view?.counting ? 4000 : 30000);
    return () => clearInterval(timer);
  }, [load, view?.counting]);

  useEffect(() => {
    if (view && !captureMeal) setCaptureMeal(currentMeal(view.meals));
  }, [view, captureMeal]);

  async function captureNow(kind) {
    setCapturing(kind);
    setMessage(null);
    try {
      const response = await fetch(camera.runNowUrl, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ meal: captureMeal, kind }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The photos could not be taken.");
      setMessage({ ok: true, text: `${data.ok_count} ${data.ok_count === 1 ? "photo" : "photos"} taken${data.failed_count ? `, ${data.failed_count} failed` : ""}. They are being counted now.` });
      setDate("");
      await load();
    } catch (failure) {
      setMessage({ ok: false, text: failure.message === "Failed to fetch" ? "The server did not respond." : failure.message });
    } finally {
      setCapturing("");
    }
  }

  const meals = view?.meals ?? [];
  const withPhotos = meals.filter((meal) => meal.photoCount);
  const without = meals.filter((meal) => !meal.photoCount);

  return (
    <section className="cc" aria-labelledby="cc-title">
      <div className="sheet cc-bar">
        <div className="cc-cameras">
          <h2 id="cc-title">Buffet cameras</h2>
          {camera.camerasConfigured ? (
            <ul aria-label="Camera status">
              {(view?.cameras ?? []).map((item) => (
                <li key={item.station} className={`cc-camera is-${item.state}`} title={item.error || undefined}>
                  <span className="cc-dot" aria-hidden="true" />{item.station}: {STATE_TEXT[item.state]}
                </li>
              ))}
              {camera.testMode && <li className="cc-camera is-test">Test mode: a capture every 15 seconds</li>}
            </ul>
          ) : (
            <p className="cc-muted">No cameras are set up. Set <code>CAMERA_SOURCES</code> and restart the app to take photos automatically.</p>
          )}
        </div>
        {camera.camerasConfigured && (
          <div className="cc-now" role="group" aria-label="Capture now">
            <label className="cc-now-meal">
              <span>Capture now for</span>
              <select value={captureMeal} onChange={(event) => setCaptureMeal(event.target.value)}>
                {camera.meals.map((meal) => <option key={meal} value={meal}>{meal[0].toUpperCase() + meal.slice(1)}</option>)}
              </select>
            </label>
            <button type="button" className="button button-secondary" disabled={Boolean(capturing)} onClick={() => captureNow("start")}>
              {capturing === "start" ? "Taking photos…" : "Start photos"}
            </button>
            <button type="button" className="button button-secondary" disabled={Boolean(capturing)} onClick={() => captureNow("end")}>
              {capturing === "end" ? "Taking photos…" : "End photos"}
            </button>
          </div>
        )}
        {message && <p className={message.ok ? "cc-message" : "inline-error"} role="status">{message.text}</p>}
      </div>

      {error && <p className="inline-error" role="alert">{error}</p>}

      {view && (
        <div className="cc-day">
          <div className="cc-day-bar">
            <label className="cc-date">
              <span>Photos from</span>
              <select value={view.date} onChange={(event) => setDate(event.target.value)} disabled={view.dates.length < 2}>
                {(view.dates.length ? view.dates : [view.date]).map((day) => <option key={day} value={day}>{dayLabel(day, view.today)}</option>)}
              </select>
            </label>
            {view.counting > 0 && <span className="cc-counting" role="status">Counting {view.counting} {view.counting === 1 ? "photo" : "photos"}…</span>}
          </div>

          {withPhotos.length === 0 && (
            <div className="sheet cc-empty">
              <h3>No photos {view.date === view.today ? "yet today" : "on this day"}</h3>
              <p>The cameras take photos at the start and end of each meal{camera.camerasConfigured ? ", or press Start photos above." : " once CAMERA_SOURCES is set."}</p>
            </div>
          )}

          {withPhotos.map((meal) => (
            <section key={meal.meal} className="cc-meal" aria-labelledby={`cc-meal-${meal.meal}`}>
              <h3 id={`cc-meal-${meal.meal}`}>
                {meal.meal[0].toUpperCase() + meal.meal.slice(1)}
                {meal.times && <small>{meal.times.start} to {meal.times.end}</small>}
              </h3>
              {meal.stations.filter((station) => station.start.photos.length || station.end.photos.length).map((station) => (
                <StationCard key={station.station} meal={meal} station={station} timezone={camera.timezone}
                  mealCheck={mealCheck} confirmUrl={camera.confirmUrl} dayUrl={camera.dayUrl.replace("DATE", view.date)}
                  onOpenPhoto={setViewer} onSaved={load} />
              ))}
            </section>
          ))}

          {without.length > 0 && withPhotos.length > 0 && (
            <p className="cc-muted cc-later">
              No photos yet for {without.map((meal) => `${meal.meal}${meal.times ? ` (${meal.times.start} to ${meal.times.end})` : ""}`).join(", ")}.
            </p>
          )}
        </div>
      )}

      <FoodList url={camera.foodsUrl} onSaved={load} />
      {viewer && <PhotoViewer photo={viewer} timezone={camera.timezone} onClose={() => setViewer(null)} />}
    </section>
  );
}
