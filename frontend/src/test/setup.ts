import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Vitest runs without globals, so Testing Library's automatic cleanup is wired up here.
afterEach(() => {
  cleanup();
});
