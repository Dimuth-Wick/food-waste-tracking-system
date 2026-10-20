import { useState } from "react";

const percent = (value, total) => `${(value / total) * 100}%`;

export default function PhotoStage({
  photo, counting, detections, result, removed, active, onActive, onToggle, onPhoto,
}) {
  const [dragging, setDragging] = useState(false);

  const dropHandlers = {
    onDragOver: (event) => {
      event.preventDefault();
      setDragging(true);
    },
    onDragLeave: () => setDragging(false),
    onDrop: (event) => {
      event.preventDefault();
      setDragging(false);
      onPhoto(event.dataTransfer.files[0]);
    },
  };

  if (!photo) {
    return (
      <label className={`fc-stage fc-drop${dragging ? " is-dragging" : ""}`} {...dropHandlers}>
        <input
          className="fc-file"
          type="file"
          accept="image/*"
          onChange={(event) => onPhoto(event.target.files[0])}
        />
        <TrayIcon />
        <span className="fc-drop-title">Drop a photo of the tray here</span>
        <span className="fc-drop-text">
          or <span className="fc-drop-browse">browse your files</span>
          <span className="fc-drop-paste">, or paste with Ctrl+V</span>
        </span>
        <span className="fc-drop-note">Shoot from above, with items not stacked. Up to 8 MB.</span>
      </label>
    );
  }

  const size = result?.image;
  return (
    <div className={`fc-stage fc-photo-stage${dragging ? " is-dragging" : ""}`} {...dropHandlers}>
      <div className={`fc-photo${counting ? " is-counting" : ""}`}>
        <img src={photo.url} alt={`Selected photo: ${photo.file.name}`} />
        {counting && <span className="fc-scan" aria-hidden="true" />}
        {size && !counting && detections.map((found, index) => {
          const [x0, y0, x1, y1] = found.box;
          const isRemoved = removed.has(found.id);
          const isActive = active === found.id;
          return (
            <div key={found.id}>
              <span
                className={`fc-box${isRemoved ? " is-removed" : ""}${isActive ? " is-active" : ""}`}
                style={{
                  left: percent(x0, size.width), top: percent(y0, size.height),
                  width: percent(x1 - x0, size.width), height: percent(y1 - y0, size.height),
                }}
                aria-hidden="true"
              />
              <button
                type="button"
                className={`fc-pin${isRemoved ? " is-removed" : ""}${isActive ? " is-active" : ""}`}
                style={{
                  left: percent((x0 + x1) / 2, size.width),
                  top: percent((y0 + y1) / 2, size.height),
                }}
                tabIndex={-1}
                aria-hidden="true"
                title={isRemoved ? "Removed. Click to count it again." : `${Math.round(found.confidence)}% confidence. Click to remove.`}
                onClick={() => onToggle(found.id)}
                onMouseEnter={() => onActive(found.id)}
                onMouseLeave={() => onActive(null)}
              >
                {isRemoved ? "×" : index + 1}
              </button>
            </div>
          );
        })}
      </div>
      {counting && <p className="fc-stage-status" role="status">Looking for each item…</p>}
    </div>
  );
}

function TrayIcon() {
  return (
    <svg className="fc-drop-icon" viewBox="0 0 64 40" aria-hidden="true">
      <rect x="2" y="6" width="60" height="30" rx="6" />
      <circle cx="18" cy="21" r="6" />
      <circle cx="32" cy="21" r="6" />
      <circle cx="46" cy="21" r="6" />
    </svg>
  );
}
