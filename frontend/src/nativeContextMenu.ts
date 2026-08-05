export function disableNativeContextMenu(target: Document = document) {
  const preventNativeMenu = (event: Event) => event.preventDefault();
  target.addEventListener("contextmenu", preventNativeMenu, { capture: true });
  return () => target.removeEventListener("contextmenu", preventNativeMenu, { capture: true });
}
