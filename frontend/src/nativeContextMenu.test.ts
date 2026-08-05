import { describe, expect, it, vi } from "vitest";
import { disableNativeContextMenu } from "./nativeContextMenu";

describe("disableNativeContextMenu", () => {
  it("blocks the WebView menu without suppressing application context events", () => {
    const element = document.createElement("button");
    const customHandler = vi.fn((event: Event) => event.preventDefault());
    element.addEventListener("contextmenu", customHandler);
    document.body.appendChild(element);
    const restore = disableNativeContextMenu();

    const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    expect(element.dispatchEvent(event)).toBe(false);
    expect(customHandler).toHaveBeenCalledOnce();

    restore();
    element.remove();
  });
});
