import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { canvasOfflineFonts } from "./build/canvas-offline-fonts.ts";
import { ownerContentSecurityPolicy, SECURITY_HEADERS } from "./build/csp.ts";

// Owner host build and test configuration (plan leaves U-01.1 and U-01.3).
// The dev and preview servers bind to 127.0.0.1 only; nothing here proxies to
// an Agent Server or any other backend. The shell calls the Integration
// process directly at http://127.0.0.1:13310 with the Owner UI session header;
// the content-security policy (build/csp.ts) allows no other connection.
export default defineConfig({
  plugins: [canvasOfflineFonts(), ownerContentSecurityPolicy(), react()],
  server: { host: "127.0.0.1", strictPort: true, headers: SECURITY_HEADERS("dev") },
  preview: { host: "127.0.0.1", strictPort: true, headers: SECURITY_HEADERS("build") },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "build/**/*.test.ts", "scripts/**/*.test.mjs"],
    restoreMocks: true,
    // Vitest blanks CSS by default. The stylesheet tests read the Canvas and
    // shell stylesheets as text (?raw); stylesheets imported for their effect
    // stay blank in jsdom, which applies no layout anyway.
    css: { include: [/\.css\?raw$/] },
  },
});
