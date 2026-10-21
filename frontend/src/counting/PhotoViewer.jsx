import { useEffect, useRef } from "react";

import { countsText, photoTime } from "./StationCard.jsx";

const percent = (value, total) => `${(value / total) * 100}%`;

// One captured photo, large, with a box on everything the model counted, to see how well it did.
export default function PhotoViewer({ photo, timezone, onClose }) {
  const dialog = useRef(null);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const counted = photo.detections.filter((match) => match.confidence >= 30);
  return (
    <dialog ref={dialog} className="cc-viewer" onClose={onClose} onClick={(event) => event.target === dialog.current && onClose()}
      aria-label={`Photo taken at ${photoTime(photo.time, timezone)}`}>
      <div className="cc-viewer-head">
        <p><strong>{photoTime(photo.time, timezone)}</strong> {photo.countStatus === "counted" ? countsText(photo.counts) : photo.countError || "Not counted yet"}</p>
        <button type="button" className="cc-viewer-close" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="cc-viewer-photo">
        <img src={photo.url} alt="Buffet photo" />
        {counted.map((match, index) => {
          const [x0, y0, x1, y1] = match.box;
          return (
            <span key={index} className="cc-box" title={`${match.label}, ${match.confidence}% sure`}
              style={{ left: percent(x0, photo.width), top: percent(y0, photo.height), width: percent(x1 - x0, photo.width), height: percent(y1 - y0, photo.height) }}>
              <span>{match.label}</span>
            </span>
          );
        })}
      </div>
      <p className="cc-muted">Boxes show what the model counted (30% sure or more). Weaker matches are kept for training but not counted.</p>
    </dialog>
  );
}
