import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./shared.css";

// Each page template renders <div id="react-root" data-settings="{...}">.
export function mount(Page, rootId = "react-root") {
  const root = document.getElementById(rootId);
  const settings = JSON.parse(root.dataset.settings);
  createRoot(root).render(
    <StrictMode>
      <Page settings={settings} />
    </StrictMode>,
  );
}
