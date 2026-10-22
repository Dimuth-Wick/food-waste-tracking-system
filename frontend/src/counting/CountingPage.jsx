import CameraCaptures from "./CameraCaptures.jsx";

export default function CountingPage({ settings }) {
  return <CameraCaptures camera={settings.camera} mealCheck={settings.mealCheck} />;
}
