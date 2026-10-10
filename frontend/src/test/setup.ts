import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { api } from "../api";

beforeEach(() => { vi.spyOn(api, "assetHealth").mockResolvedValue({ assets: [], files: [] }); });

Object.defineProperties(HTMLMediaElement.prototype, {
  load: { configurable: true, value: () => undefined },
  pause: { configurable: true, value: () => undefined },
  play: { configurable: true, value: async () => undefined },
});

afterEach(cleanup);
