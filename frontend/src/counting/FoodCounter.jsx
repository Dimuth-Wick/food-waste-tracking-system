import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import PhotoStage from "./PhotoStage.jsx";
import Tally from "./Tally.jsx";
import { IMAGE_ERROR, isImage, usePastedImage } from "../shared/photo.jsx";
import { plural, prefersReducedMotion } from "../shared/text.js";

const PIN_DELAY_MS = 160;

// One photo's count. The meal check page shows two: the start and the end of the meal.
// The item being counted is shared between them, and each reports its count upward.
export default function FoodCounter({ settings, slot, onScreen, item, setItem, onCount, photoTitle, next }) {
  const [photo, setPhoto] = useState(null); // { file, url }
  const [status, setStatus] = useState("idle"); // idle | counting | done
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [confidence, setConfidence] = useState(settings.defaultConfidence);
  const [removed, setRemoved] = useState(() => new Set());
  const [revealed, setRevealed] = useState(0);
  const [active, setActive] = useState(null);
  const request = useRef(null);

  const cleanItem = item.trim().replace(/\s+/g, " ").toLowerCase();
  const resultItem = result?.item ?? cleanItem;
  const isStale = result && result.item !== cleanItem;

  // Matches above the slider value, strongest first, numbered in that order.
  const visible = useMemo(
    () => (result?.detections ?? [])
      .map((found, index) => ({ ...found, id: index }))
      .filter((found) => found.confidence >= confidence),
    [result, confidence],
  );
  const shown = visible.slice(0, revealed);
  const counted = shown.filter((found) => !removed.has(found.id)).length;

  const choosePhoto = useCallback((file) => {
    if (!isImage(file)) {
      setError(IMAGE_ERROR);
      return;
    }
    request.current?.abort();
    setPhoto((previous) => {
      if (previous) URL.revokeObjectURL(previous.url);
      return { file, url: URL.createObjectURL(file) };
    });
    setResult(null);
    setStatus("idle");
    setError("");
  }, []);

  function clearPhoto() {
    request.current?.abort();
    if (photo) URL.revokeObjectURL(photo.url);
    setPhoto(null);
    setResult(null);
    setStatus("idle");
    setError("");
  }

  // Only the photo tab on screen takes a pasted image.
  const pasteHere = useCallback((file) => { if (onScreen) choosePhoto(file); }, [onScreen, choosePhoto]);
  usePastedImage(pasteHere);

  // Drop the pins in one at a time after a new result arrives.
  useEffect(() => {
    if (!result) return undefined;
    const total = result.detections.length;
    if (prefersReducedMotion()) {
      setRevealed(total);
      return undefined;
    }
    setRevealed(0);
    const timer = setInterval(() => {
      setRevealed((count) => {
        if (count + 1 >= total) clearInterval(timer);
        return Math.min(count + 1, total);
      });
    }, PIN_DELAY_MS);
    return () => clearInterval(timer);
  }, [result]);

  async function count(event) {
    event.preventDefault();
    if (!photo) {
      setError("Add a photo first: drop it on the left, paste it, or browse.");
      return;
    }
    if (!cleanItem) {
      setError("Type what to count, for example cupcake.");
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;

    const form = new FormData();
    form.append("image", photo.file);
    form.append("item", cleanItem);
    setStatus("counting");
    setError("");
    try {
      const response = await fetch(settings.apiUrl, {
        method: "POST", body: form, signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Counting failed. Check the server logs.");
      setRemoved(new Set());
      setActive(null);
      setResult(data);
      setStatus("done");
    } catch (failure) {
      if (failure.name === "AbortError") return;
      setError(failure.message === "Failed to fetch"
        ? "The server did not respond. Check that the app is still running."
        : failure.message);
      setStatus(result ? "done" : "idle");
    }
  }

  function toggle(id) {
    setRemoved((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const counting = status === "counting";
  const finished = result && revealed >= visible.length;

  useEffect(() => {
    onCount(slot, result && finished ? { count: counted, label: resultItem } : null);
  }, [onCount, slot, result, finished, counted, resultItem]);

  return (
    <div className="fc">
      <PhotoStage
        photo={photo}
        counting={counting}
        detections={shown}
        result={result}
        removed={removed}
        active={active}
        onActive={setActive}
        onToggle={toggle}
        onPhoto={choosePhoto}
        title={photoTitle}
      />

      <aside className="side-panel fc-panel" aria-label="Counting controls and result">
        <form className="fc-form" onSubmit={count}>
          <label className="field-label" htmlFor="fc-item">What to count</label>
          <input
            id="fc-item"
            className="fc-input"
            value={item}
            maxLength={settings.maxItemLength}
            onChange={(event) => setItem(event.target.value)}
            placeholder="cupcake, egg, bread roll…"
            autoComplete="off"
          />
          <div className="chips" role="group" aria-label="Quick choices">
            {settings.quickItems.map((choice) => (
              <button
                key={choice}
                type="button"
                className="chip"
                aria-pressed={cleanItem === choice}
                onClick={() => setItem(choice)}
              >
                {choice}
              </button>
            ))}
          </div>
          <button className="wide-button" type="submit" disabled={counting}>
            {counting ? `Counting ${plural(cleanItem || "item")}…` : `Count ${plural(cleanItem || "item")}`}
          </button>
          {photo && (
            <button type="button" className="link-button" onClick={clearPhoto}>
              Use a different photo
            </button>
          )}
        </form>

        {error && <p className="inline-error" role="alert">{error}</p>}

        {result ? (
          <section className={`fc-result${isStale ? " is-stale" : ""}`} aria-labelledby="fc-result-heading">
            <h2 id="fc-result-heading" className="fc-result-heading">
              <span className="fc-total" aria-live="polite">{counted}</span>
              <span>{plural(resultItem, counted)} counted</span>
            </h2>
            <Tally count={counted} />
            {finished && next}
            {isStale && (
              <p className="hint">This count is for “{resultItem}”. Press Count to count {plural(cleanItem)} instead.</p>
            )}
            {finished && removed.size > 0 && (
              <p className="hint">
                {removed.size} removed by you. Click a crossed-out item to count it again.
              </p>
            )}

            <label className="field-label fc-slider-label" htmlFor="fc-confidence">
              <span>Minimum confidence</span>
              <output htmlFor="fc-confidence">{confidence}%</output>
            </label>
            <input
              id="fc-confidence"
              className="fc-slider"
              type="range"
              min={result.minConfidence}
              max={90}
              step={5}
              value={confidence}
              onChange={(event) => setConfidence(Number(event.target.value))}
            />
            <p className="hint">Lower finds more, but may count things that are not a {resultItem}.</p>

            {visible.length > 0 ? (
              <ol className="fc-list">
                {visible.map((found, index) => (
                  <li key={found.id} className={index < revealed ? "is-shown" : ""}>
                    <button
                      type="button"
                      className={`fc-row${removed.has(found.id) ? " is-removed" : ""}${active === found.id ? " is-active" : ""}`}
                      aria-pressed={!removed.has(found.id)}
                      aria-label={`${resultItem} ${index + 1}, ${found.confidence}% confidence. ${removed.has(found.id) ? "Removed. Click to count it again." : "Click to remove from the count."}`}
                      onClick={() => toggle(found.id)}
                      onMouseEnter={() => setActive(found.id)}
                      onMouseLeave={() => setActive(null)}
                      onFocus={() => setActive(found.id)}
                      onBlur={() => setActive(null)}
                    >
                      <span className="fc-row-number">{index + 1}</span>
                      <span className="fc-row-bar" aria-hidden="true">
                        <span style={{ width: `${found.confidence}%` }} />
                      </span>
                      <span className="fc-row-value">{Math.round(found.confidence)}%</span>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="fc-empty">
                No {plural(resultItem)} found at {confidence}%+. Move the slider left, or try another name, such as “{resultItem === "cupcake" ? "muffin" : "cake"}”.
              </p>
            )}
          </section>
        ) : (
          <p className="fc-intro">
            The model looks for whatever you type and pins each one it finds. You can then remove any it got wrong.
          </p>
        )}
      </aside>
    </div>
  );
}
