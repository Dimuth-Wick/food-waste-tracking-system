import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const source = (path) => fileURLToPath(new URL(path, import.meta.url));

// Builds each React page into Flask's static folder with fixed file names, so
// the page templates can link to them directly:
//   app/static/react/<page>.js  - one script per page
//   app/static/react/react.css  - all page styles in one file
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: source("../app/static/react"),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: {
        counting: source("./src/counting/main.jsx"),
        forecast: source("./src/forecast/main.jsx"),
        prediction: source("./src/prediction/main.jsx"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "[name].js",
        assetFileNames: "react[extname]",
      },
    },
  },
});
