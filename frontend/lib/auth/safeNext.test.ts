import { describe, expect, it } from "vitest";

import { loginUrl, safeNextPath } from "@/lib/auth/safeNext";

describe("safeNextPath", () => {
  it.each(["/screener?x=1", "/tickers/AAPL", "/tickers/BRK.B", "/settings?section=score-weighting", "/watchlist#top", "/", "/a%2F%2Fb"])(
    "accepts the same-origin path %s",
    (p) => {
      expect(safeNextPath(p)).toBe(p);
    },
  );

  it.each([
    ["a protocol-relative URL", "//evil.com"],
    ["a protocol-relative URL with a path", "//evil.com/screener"],
    ["an absolute http URL", "http://evil.com"],
    ["an absolute https URL", "https://evil.com/x"],
    ["a javascript: URL", "javascript:alert(1)"],
    ["a data: URL", "data:text/html,x"],
    ["a slash-backslash host", "/\\evil.com"],
    ["a backslash anywhere", "/screener\\x"],
    ["a leading backslash", "\\\\evil.com"],
    ["a tab hidden between the slashes", "/\t/evil.com"],
    ["a newline hidden between the slashes", "/\n/evil.com"],
    ["a carriage return", "/\r/evil.com"],
    ["a relative path without a leading slash", "screener"],
    ["an empty string", ""],
    ["login itself", "/login"],
    ["login with a query", "/login?next=/screener"],
    ["a login sub-path", "/login/x"],
    ["a whitespace-led URL", " //evil.com"],
  ])("rejects %s", (_name, p) => {
    expect(safeNextPath(p)).toBeNull();
  });

  it.each([null, undefined])("rejects %s", (p) => {
    expect(safeNextPath(p)).toBeNull();
  });

  it("rejects an absurdly long value", () => {
    expect(safeNextPath(`/${"a".repeat(3000)}`)).toBeNull();
  });

  it("does not treat a path that merely starts with the letters login as the login page", () => {
    expect(safeNextPath("/loginfo")).toBe("/loginfo");
  });
});

describe("loginUrl", () => {
  it("carries the current page, encoded", () => {
    expect(loginUrl("/screener?x=1&y=2")).toBe("/login?next=%2Fscreener%3Fx%3D1%26y%3D2");
  });

  it("is plain /login for an unsafe or login page", () => {
    expect(loginUrl("//evil.com")).toBe("/login");
    expect(loginUrl("/login")).toBe("/login");
    expect(loginUrl(null)).toBe("/login");
  });
});
