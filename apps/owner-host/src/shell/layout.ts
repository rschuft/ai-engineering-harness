import { useSyncExternalStore } from "react";

/**
 * The shell's two layouts. At or above WIDE_MIN_WIDTH pixels the areas are a
 * vertical navigation column beside the content; below it they are a
 * horizontal tab bar above the content and the identity is shown in its short
 * form. shell.css keys every layout rule on the root's data-layout attribute,
 * so this constant is the single source of the breakpoint.
 */
export const WIDE_MIN_WIDTH = 900;
export const WIDE_QUERY = `(min-width: ${WIDE_MIN_WIDTH}px)`;

export type ShellLayout = "narrow" | "wide";

function query(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(WIDE_QUERY) : null;
}

function subscribe(onChange: () => void): () => void {
  const list = query();
  if (!list) return () => {};
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

function snapshot(): ShellLayout {
  const list = query();
  // Without matchMedia (no browser), fall back to the wide layout.
  return list === null || list.matches ? "wide" : "narrow";
}

export function useShellLayout(): ShellLayout {
  return useSyncExternalStore(subscribe, snapshot, () => "wide");
}
