import { defineConfig } from "vitest/config";

// Focused unit tests for the shared API client and pure helpers. The suite runs
// in a Node environment (no DOM) and stubs global `fetch`, so it needs no
// browser runner and no extra test dependency beyond Vitest.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
    clearMocks: true,
  },
});
