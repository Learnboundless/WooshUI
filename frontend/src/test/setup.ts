import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

Object.defineProperties(HTMLMediaElement.prototype, {
  load: { configurable: true, value: () => undefined },
  pause: { configurable: true, value: () => undefined },
  play: { configurable: true, value: async () => undefined },
});

afterEach(cleanup);
