import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GradeBadge, ScoreBar, scoreTone } from "./score";

describe("scoreTone", () => {
  it.each([
    [100, "bg-ok"],
    [80, "bg-ok"],
    [79.9, "bg-warn"],
    [55, "bg-warn"],
    [54.9, "bg-sev-critical"],
    [0, "bg-sev-critical"],
  ])("score %s uses %s", (score, bar) => {
    expect(scoreTone(score).bar).toBe(bar);
  });
});

describe("ScoreBar", () => {
  it("exposes the rounded score as an accessible progressbar", () => {
    render(<ScoreBar score={72.6} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "73");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("keeps a visible sliver for a zero score and never exceeds the track", () => {
    const { rerender } = render(<ScoreBar score={0} />);
    expect(screen.getByRole("progressbar").firstElementChild).toHaveStyle({ width: "1%" });

    rerender(<ScoreBar score={140} />);
    expect(screen.getByRole("progressbar").firstElementChild).toHaveStyle({ width: "100%" });
  });
});

describe("GradeBadge", () => {
  it("announces the grade to assistive technology", () => {
    render(<GradeBadge grade="B" score={84} />);
    expect(screen.getByLabelText("Grade B")).toHaveTextContent("B");
  });
});
