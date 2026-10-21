import CameraCaptures from "./CameraCaptures.jsx";
import MealCheck from "./MealCheck.jsx";

// The camera photos come first. Counting your own photos stays at the bottom, to check how well the
// model counts, until it is no longer needed.
export default function CountingPage({ settings }) {
  return (
    <>
      <CameraCaptures camera={settings.camera} mealCheck={settings.mealCheck} />
      <section className="cc-manual" aria-labelledby="cc-manual-title">
        <div className="cc-manual-heading">
          <h2 id="cc-manual-title">Test the model with your own photos</h2>
          <p>Upload a start and an end photo and type what to count, to see how well the model counts. Nothing is saved. This is for testing and will be removed later.</p>
        </div>
        <MealCheck settings={settings} />
      </section>
    </>
  );
}
