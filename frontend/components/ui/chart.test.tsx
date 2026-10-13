// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { buildChartCss, chartCssKey, ChartContainer, type ChartConfig } from "@/components/ui/chart";

afterEach(cleanup);

// Raw FMP segment names that would break out of a generated <style> if used as-is.
const HOSTILE = [
  "Data Center}",
  "a;b",
  'say "hi"',
  "it's",
  "</style><script>alert(1)</script>",
  "x{color:red}",
  "back\\slash",
  "new\nline",
  "Revenue (Products & Services)",
  "日本",
  "",
];

describe("chartCssKey", () => {
  it("leaves a safe name alone", () => {
    expect(chartCssKey("value")).toBe("value");
    expect(chartCssKey("Segment-1")).toBe("Segment-1");
  });

  it.each(HOSTILE)("maps %j to [A-Za-z0-9_-] only", (name) => {
    expect(chartCssKey(name)).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("escapes the underscore too, so two different names never share a key", () => {
    const names = ["a_5f_", "a_", "a ", "a;", "a}", "a,", "A", "a", "", "_", "_5f_", "__", "a b", "a_b", "a-b", "ab"];
    const keys = names.map(chartCssKey);
    expect(new Set(keys).size).toBe(names.length);
  });

  it("is stable: the same name always gives the same key", () => {
    expect(chartCssKey("Data Center}")).toBe(chartCssKey("Data Center}"));
    expect(chartCssKey("Data Center}")).toBe("Data_20_Center_7d_");
  });

  it("handles a code point outside the BMP as one escape", () => {
    expect(chartCssKey("a😀b")).toBe("a_1f600_b");
  });
});

describe("buildChartCss", () => {
  it("emits one variable per series for both themes", () => {
    const css = buildChartCss("chart-x", { value: { label: "V", color: "#fff" }, other: { color: "oklch(0.7 0.1 200 / 50%)" } });
    expect(css).toContain("[data-chart=chart-x] {");
    expect(css).toContain("--color-value: #fff;");
    expect(css).toContain("--color-other: oklch(0.7 0.1 200 / 50%);");
    expect(css).toContain(".dark [data-chart=chart-x] {");
  });

  it("returns empty when no series has a colour", () => {
    expect(buildChartCss("c", { a: { label: "A" } })).toBe("");
  });

  it("never lets a hostile name break out of the rule or the element", () => {
    const config: ChartConfig = Object.fromEntries(HOSTILE.map((name) => [name, { color: "#123456" }]));
    const css = buildChartCss("chart-y", config);
    expect(css).not.toContain("<");
    expect(css).not.toContain("</style>");
    // Only the two rule blocks (light + dark) may contain braces: exactly 2 "{" and 2 "}".
    expect(css.match(/{/g)).toHaveLength(2);
    expect(css.match(/}/g)).toHaveLength(2);
    // Every declaration line is a single custom property with a safe name.
    const declarations = css.split("\n").filter((line) => line.startsWith("  --"));
    expect(declarations).toHaveLength(HOSTILE.length * 2);
    for (const line of declarations) expect(line).toMatch(/^ {2}--color-[A-Za-z0-9_-]+: #123456;$/);
  });

  it("keeps two different hostile names as two different variables", () => {
    const css = buildChartCss("c", { "a}": { color: "#111111" }, "a;": { color: "#222222" }, a_7d_: { color: "#333333" } });
    const names = css.split("\n").filter((l) => l.startsWith("  --")).map((l) => l.split(":")[0]);
    expect(new Set(names).size).toBe(3);
  });

  it.each([
    "red; } body { display:none",
    "red}",
    "url('x')",
    'url("x")',
    "red</style>",
    "red\;",
    "red\nblue",
  ])("drops a colour value that could end the declaration: %j", (color) => {
    const css = buildChartCss("c", { ok: { color: "#abc" }, bad: { color } });
    expect(css).toContain("--color-ok: #abc;");
    expect(css).not.toContain("--color-bad");
  });

  it("sanitises the chart id used in the selector", () => {
    const css = buildChartCss("x] { } </style> [", { a: { color: "#abc" } });
    expect(css).not.toContain("<");
    expect(css.match(/{/g)).toHaveLength(2);
  });
});

describe("ChartContainer", () => {
  it("renders the style element with only safe text for hostile series names", () => {
    const config: ChartConfig = Object.fromEntries(HOSTILE.map((name) => [name, { color: "#123456" }]));
    const { container } = render(
      <ChartContainer config={config} id={'bad"id</style>'}>
        <div />
      </ChartContainer>
    );
    const styles = container.querySelectorAll("style");
    expect(styles).toHaveLength(1);
    const text = styles[0].textContent ?? "";
    expect(text).not.toContain("<");
    // The wrapper carries the same sanitised id the selector targets.
    const wrapper = container.querySelector("[data-slot=chart]") as HTMLElement;
    const id = wrapper.getAttribute("data-chart") ?? "";
    expect(id).toMatch(/^chart-[A-Za-z0-9_-]+$/);
    expect(text).toContain(`[data-chart=${id}]`);
    // No script element was created from the "</style><script>" name.
    expect(container.querySelector("script")).toBeNull();
  });
});
