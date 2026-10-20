import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import FoodCounter from "./FoodCounter.jsx";
import "./food-counter.css";

const root = document.getElementById("food-counter");
const settings = JSON.parse(root.dataset.settings);

createRoot(root).render(
  <StrictMode>
    <FoodCounter settings={settings} />
  </StrictMode>,
);
