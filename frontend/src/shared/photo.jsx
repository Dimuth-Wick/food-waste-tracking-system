import { useEffect, useState } from "react";

export const IMAGE_ERROR = "Choose an image file, such as a JPG or PNG photo.";

export function isImage(file) {
  return Boolean(file && file.type.startsWith("image/"));
}

// Call onImage with a photo pasted anywhere on the page (Ctrl+V).
export function usePastedImage(onImage) {
  useEffect(() => {
    const onPaste = (event) => {
      const file = [...(event.clipboardData?.files ?? [])].find(isImage);
      if (file) {
        event.preventDefault();
        onImage(file);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onImage]);
}

// Drag-and-drop handlers plus whether a file is being dragged over.
export function useDropTarget(onImage) {
  const [dragging, setDragging] = useState(false);
  const handlers = {
    onDragOver: (event) => {
      event.preventDefault();
      setDragging(true);
    },
    onDragLeave: () => setDragging(false),
    onDrop: (event) => {
      event.preventDefault();
      setDragging(false);
      onImage(event.dataTransfer.files[0]);
    },
  };
  return [dragging, handlers];
}

// The empty pine stage: drop, browse, or paste a photo.
export function PhotoDrop({ title, note, onImage }) {
  const [dragging, handlers] = useDropTarget(onImage);
  return (
    <label className={`stage photo-drop${dragging ? " is-dragging" : ""}`} {...handlers}>
      <input
        className="photo-drop-file"
        type="file"
        accept="image/*"
        onChange={(event) => onImage(event.target.files[0])}
      />
      <TrayIcon />
      <span className="photo-drop-title">{title}</span>
      <span className="photo-drop-text">
        or <span className="photo-drop-browse">browse your files</span>
        <span className="photo-drop-paste">, or paste with Ctrl+V</span>
      </span>
      <span className="photo-drop-note">{note}</span>
    </label>
  );
}

function TrayIcon() {
  return (
    <svg className="photo-drop-icon" viewBox="0 0 64 40" aria-hidden="true">
      <rect x="2" y="6" width="60" height="30" rx="6" />
      <circle cx="18" cy="21" r="6" />
      <circle cx="32" cy="21" r="6" />
      <circle cx="46" cy="21" r="6" />
    </svg>
  );
}
