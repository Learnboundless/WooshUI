import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initializeBackend } from "./api";
import { disableNativeContextMenu } from "./nativeContextMenu";
import "./styles.css";

disableNativeContextMenu();
await initializeBackend();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
