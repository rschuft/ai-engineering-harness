import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CanvasBoundary } from "./CanvasBoundary";

function Broken(): never {
  throw new Error("simulated Canvas failure");
}

it("replaces a failed Canvas mount with an explicit empty state naming the reason", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <CanvasBoundary>
      <Broken />
    </CanvasBoundary>,
  );
  const failed = screen.getByTestId("canvas-failed");
  expect(failed.textContent).toMatch(/Agent Canvas failed to load/);
  expect(failed.textContent).toMatch(/simulated Canvas failure/);
});
