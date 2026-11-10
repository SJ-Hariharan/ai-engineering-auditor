import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SeverityBadge, SeverityCounts } from "./badges";
import type { Severity } from "@/lib/types";

const SEVERITIES: [Severity, string][] = [
  ["critical", "Critical"],
  ["high", "High"],
  ["medium", "Medium"],
  ["low", "Low"],
  ["info", "Info"],
];

describe("SeverityBadge", () => {
  it.each(SEVERITIES)("renders the text label for %s, not only a colour", (severity, label) => {
    render(<SeverityBadge severity={severity} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("gives each severity a different label", () => {
    const { container } = render(
      <>
        {SEVERITIES.map(([s]) => (
          <SeverityBadge key={s} severity={s} />
        ))}
      </>,
    );
    const texts = [...container.querySelectorAll("span")].map((el) => el.textContent);
    expect(new Set(texts).size).toBe(SEVERITIES.length);
  });
});

describe("SeverityCounts", () => {
  it("lists only the severities that have findings, most severe first", () => {
    render(<SeverityCounts counts={{ low: 3, critical: 1, high: 0 }} />);
    const chips = screen.getAllByTitle(/./).map((el) => el.textContent);
    expect(chips).toEqual(["1 Critical", "3 Low"]);
  });

  it("says so when there are no findings", () => {
    render(<SeverityCounts counts={{}} />);
    expect(screen.getByText("No findings")).toBeInTheDocument();
  });
});
