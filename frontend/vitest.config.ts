import { defineConfig } from "vitest/config";

// Focused unit tests for the shared API client, pure helpers and shared UI
// components. The default environment is Node (no DOM) and the client/helper
// tests stub global `fetch`, so they need no browser runner. Component tests opt
// into jsdom per file with the `// @vitest-environment jsdom` pragma.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    restoreMocks: true,
    clearMocks: true,
    testTimeout: 30000,
  },
});
