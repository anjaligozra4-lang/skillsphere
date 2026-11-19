import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    preserveSymlinks: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.js",
  },
  server: {
    port: 5174,
    strictPort: true,
    fs: {
      strict: false,
    },
  },
});
