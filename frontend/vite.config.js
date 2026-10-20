import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Builds the Food counting page into Flask's static folder with fixed file
// names, so app/templates/food_detection.html can link to them directly.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../app/static/food-counter", import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL("./src/main.jsx", import.meta.url)),
      output: {
        entryFileNames: "food-counter.js",
        chunkFileNames: "food-counter-[name].js",
        assetFileNames: "food-counter[extname]",
      },
    },
  },
});
