import { useCallback, useState } from "react";

import FoodCounter from "./FoodCounter.jsx";
import SaveMealCheck from "./SaveMealCheck.jsx";
import { plural } from "../shared/text.js";

const STEPS = [
  { slot: "start", title: "Start of meal", photo: "Drop the start-of-meal photo here" },
  { slot: "end", title: "End of meal", photo: "Drop the end-of-meal photo here" },
];

// A buffet meal check: count the start photo, count the end photo, then save the difference.
export default function MealCheck({ settings }) {
  const [item, setItem] = useState(settings.defaultItem);
  const [tab, setTab] = useState("start");
  const [counts, setCounts] = useState({ start: null, end: null });
  const report = useCallback((slot, value) => {
    setCounts((current) => (sameCount(current[slot], value) ? current : { ...current, [slot]: value }));
  }, []);

  return (
    <div className="mc">
      <div className="mc-steps" role="tablist" aria-label="Meal photos">
        {STEPS.map((step, index) => {
          const found = counts[step.slot];
          return (
            <button
              key={step.slot}
              type="button"
              role="tab"
              id={`mc-tab-${step.slot}`}
              aria-selected={tab === step.slot}
              aria-controls={`mc-panel-${step.slot}`}
              className="mc-step"
              onClick={() => setTab(step.slot)}
            >
              <span className="mc-step-number">{index + 1}</span>
              <span className="mc-step-text">
                <strong>{step.title} photo</strong>
                <small>{found ? `${found.count} ${plural(found.label, found.count)} counted` : "Not counted yet"}</small>
              </span>
            </button>
          );
        })}
      </div>

      {STEPS.map((step) => (
        <div key={step.slot} id={`mc-panel-${step.slot}`} role="tabpanel" aria-labelledby={`mc-tab-${step.slot}`} hidden={tab !== step.slot}>
          <FoodCounter
            settings={settings}
            slot={step.slot}
            onScreen={tab === step.slot}
            item={item}
            setItem={setItem}
            onCount={report}
            photoTitle={step.photo}
            next={step.slot === "start"
              ? <button type="button" className="wide-button mc-next" onClick={() => setTab("end")}>Next: count the end-of-meal photo</button>
              : <a className="wide-button mc-next" href="#mc-save">Next: save the meal check</a>}
          />
        </div>
      ))}

      <SaveMealCheck settings={settings.mealCheck} counts={counts} onShowPhoto={setTab} />
    </div>
  );
}

function sameCount(a, b) {
  return a === b || (a && b && a.count === b.count && a.label === b.label);
}
