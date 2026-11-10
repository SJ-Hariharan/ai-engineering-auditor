import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit and component tests only. This file is outside src/app, so Next.js never
// bundles it, and the tests run under plain Vitest (not `next dev`).
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    clearMocks: true,
    restoreMocks: true,
  },
});
