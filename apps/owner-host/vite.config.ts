import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { canvasOfflineFonts } from "./build/canvas-offline-fonts.ts";

// Owner host build and test configuration (plan leaf U-01.1).
// The dev and preview servers bind to 127.0.0.1 only; nothing here proxies to
// an Agent Server or any other backend.
export default defineConfig({
  plugins: [canvasOfflineFonts(), react()],
  server: { host: "127.0.0.1", strictPort: true },
  preview: { host: "127.0.0.1", strictPort: true },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "build/**/*.test.ts"],
    restoreMocks: true,
    // Vitest blanks CSS by default. The stylesheet tests read the Canvas and
    // shell stylesheets as text (?raw); stylesheets imported for their effect
    // stay blank in jsdom, which applies no layout anyway.
    css: { include: [/\.css\?raw$/] },
  },
});
