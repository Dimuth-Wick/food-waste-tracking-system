import { useCallback, useRef, useState } from "react";

import { IMAGE_ERROR, PhotoDrop, isImage, useDropTarget, usePastedImage } from "../shared/photo.jsx";

export default function FoodPrediction({ settings }) {
  const [photo, setPhoto] = useState(null); // { file, url }
  const [predictions, setPredictions] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);

  // A new photo is predicted straight away; there is nothing else to choose.
  const choosePhoto = useCallback(async (file) => {
    if (!isImage(file)) {
      setError(IMAGE_ERROR);
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPhoto((previous) => {
      if (previous) URL.revokeObjectURL(previous.url);
      return { file, url: URL.createObjectURL(file) };
    });
    setPredictions(null);
    setError("");
    setBusy(true);

    const form = new FormData();
    form.append("image", file);
    try {
      const response = await fetch(settings.apiUrl, {
        method: "POST", body: form, signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Prediction failed. Check the server logs.");
      setPredictions(data.predictions);
    } catch (failure) {
      if (failure.name === "AbortError") return;
      setError(failure.message === "Failed to fetch"
        ? "The server did not respond. Check that the app is still running."
        : failure.message);
    }
    setBusy(false);
  }, [settings.apiUrl]);

  usePastedImage(choosePhoto);
  const [dragging, dropHandlers] = useDropTarget(choosePhoto);
  const [best, ...others] = predictions ?? [];

  return (
    <div className="fp">
      {photo ? (
        <div className={`stage fp-stage${dragging ? " is-dragging" : ""}`} {...dropHandlers}>
          <div className={`photo-frame${busy ? " is-busy" : ""}`}>
            <img src={photo.url} alt={`Selected photo: ${photo.file.name}`} />
            {busy && <span className="scan" aria-hidden="true" />}
            {best && <span className="fp-tag">{best.label}</span>}
          </div>
          {busy && <p className="stage-status" role="status">Recognising the food…</p>}
        </div>
      ) : (
        <PhotoDrop
          title="Drop a photo of one dish here"
          note="One dish per photo works best. Up to 8 MB."
          onImage={choosePhoto}
        />
      )}

      <aside className="side-panel fp-panel" aria-label="Prediction result">
        {error && <p className="inline-error fp-error" role="alert">{error}</p>}
        {best ? (
          <section aria-labelledby="fp-best">
            <p className="fp-kicker">Most likely</p>
            <h2 id="fp-best" className="fp-best">{best.label}</h2>
            <Confidence value={best.confidence} lead />
            <h3 className="fp-others-heading">Other possibilities</h3>
            <ol className="fp-others">
              {others.map((item) => (
                <li key={item.label}>
                  <span className="fp-other-label">{item.label}</span>
                  <Confidence value={item.confidence} />
                </li>
              ))}
            </ol>
            <p className="hint">
              Confidence is how sure the model is among its {settings.classCount} Food-101 dishes. Check the result before using it in a waste record.
            </p>
          </section>
        ) : (
          <p className="fp-intro">
            {busy
              ? "Comparing the photo with 101 kinds of dish…"
              : `The model names the dish in a photo, choosing from ${settings.classCount} Food-101 dishes such as pizza, sushi and fried rice.`}
          </p>
        )}
        {photo && !busy && (
          <label className="link-button fp-another">
            Try another photo
            <input
              className="photo-drop-file"
              type="file"
              accept="image/*"
              onChange={(event) => choosePhoto(event.target.files[0])}
            />
          </label>
        )}
      </aside>
    </div>
  );
}

function Confidence({ value, lead = false }) {
  return (
    <div className={`fp-confidence${lead ? " is-lead" : ""}`}>
      <span className="fp-bar" aria-hidden="true"><span style={{ width: `${value}%` }} /></span>
      <span className="fp-value">{value.toFixed(1)}%</span>
    </div>
  );
}
