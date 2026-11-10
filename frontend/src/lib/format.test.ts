import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { codeHref, fmtNum, fmtScore, formatDate, gradeOf, repoName, tabHref, timeAgo, worstSeverity } from "./format";

describe("gradeOf", () => {
  it.each([
    [100, "A"],
    [90, "A"],
    [89.9, "B"],
    [80, "B"],
    [79.9, "C"],
    [70, "C"],
    [69.9, "D"],
    [55, "D"],
    [54.9, "F"],
    [0, "F"],
  ])("score %s is grade %s", (score, grade) => {
    expect(gradeOf(score)).toBe(grade);
  });
});

describe("number formatting", () => {
  it("shows one decimal place for scores and a dash for missing values", () => {
    expect(fmtScore(72.345)).toBe("72.3");
    expect(fmtScore(88)).toBe("88.0");
    expect(fmtScore(null)).toBe("-");
    expect(fmtScore(undefined)).toBe("-");
  });

  it("uses locale grouping for counts and a dash for missing values", () => {
    expect(fmtNum(1234)).toBe((1234).toLocaleString());
    expect(fmtNum(null)).toBe("-");
  });
});

describe("repoName", () => {
  it("strips the GitHub host and a trailing .git", () => {
    expect(repoName("https://github.com/pallets/flask.git")).toBe("pallets/flask");
    expect(repoName("https://www.github.com/pallets/flask")).toBe("pallets/flask");
  });

  it("returns an empty string for upload projects", () => {
    expect(repoName(null)).toBe("");
  });
});

describe("worstSeverity", () => {
  it("returns the most severe level present", () => {
    expect(worstSeverity([{ severity: "low" }, { severity: "critical" }, { severity: "medium" }])).toBe("critical");
  });

  it("returns info for an empty list", () => {
    expect(worstSeverity([])).toBe("info");
  });
});

describe("links", () => {
  it("builds a code-tab link with an encoded id, encoded file path, and optional line", () => {
    expect(codeHref("a/1", "server/app.py", 21)).toBe("/audits/a%2F1?tab=code&file=server%2Fapp.py&line=21");
    expect(codeHref("abc", "README.md")).toBe("/audits/abc?tab=code&file=README.md");
  });

  it("omits the line when it is zero or missing", () => {
    expect(codeHref("abc", "x.py", 0)).not.toContain("line=");
    expect(codeHref("abc", "x.py", null)).not.toContain("line=");
  });

  it("builds a tab link", () => {
    expect(tabHref("abc", "findings")).toBe("/audits/abc?tab=findings");
  });
});

describe("dates", () => {
  it("shows a dash for missing dates and returns unparseable input unchanged", () => {
    expect(formatDate(null)).toBe("-");
    expect(timeAgo(undefined)).toBe("-");
    expect(formatDate("not a date")).toBe("not a date");
    expect(timeAgo("not a date")).toBe("not a date");
  });

  describe("timeAgo", () => {
    const now = new Date("2026-11-05T12:00:00Z").getTime();
    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(now);
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    const ago = (ms: number) => new Date(now - ms).toISOString();

    it("uses coarse buckets", () => {
      expect(timeAgo(ago(10 * 1000))).toBe("just now");
      expect(timeAgo(ago(5 * 60 * 1000))).toBe("5m ago");
      expect(timeAgo(ago(3 * 60 * 60 * 1000))).toBe("3h ago");
      expect(timeAgo(ago(4 * 24 * 60 * 60 * 1000))).toBe("4d ago");
    });

    it("falls back to an absolute date after about a month", () => {
      const old = ago(45 * 24 * 60 * 60 * 1000);
      expect(timeAgo(old)).toBe(formatDate(old));
    });

    it("treats a timestamp in the future as just now", () => {
      expect(timeAgo(new Date(now + 60 * 1000).toISOString())).toBe("just now");
    });
  });
});
