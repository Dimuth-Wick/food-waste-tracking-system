import { PhotoDrop, useDropTarget } from "../shared/photo.jsx";

const percent = (value, total) => `${(value / total) * 100}%`;

export default function PhotoStage({
  photo, counting, detections, result, removed, active, onActive, onToggle, onPhoto,
  title = "Drop a photo of the tray here",
}) {
  const [dragging, dropHandlers] = useDropTarget(onPhoto);

  if (!photo) {
    return (
      <PhotoDrop
        title={title}
        note="Shoot from above, with items not stacked. Up to 8 MB."
        onImage={onPhoto}
      />
    );
  }

  const size = result?.image;
  return (
    <div className={`stage fc-photo-stage${dragging ? " is-dragging" : ""}`} {...dropHandlers}>
      <div className={`photo-frame${counting ? " is-busy" : ""}`}>
        <img src={photo.url} alt={`Selected photo: ${photo.file.name}`} />
        {counting && <span className="scan" aria-hidden="true" />}
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
      {counting && <p className="stage-status" role="status">Looking for each item…</p>}
    </div>
  );
}
