import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// The backend rejects a write without an allowed Origin or the X-Fathom-Request header, and lib/api/client.ts is
// what adds that header. A raw fetch() anywhere else would silently bypass it, so none may exist.
const ROOT = join(__dirname, "..", "..");
const SCAN_DIRS = ["app", "components", "lib", "hooks"];
const ALLOWED = new Set(["lib/api/client.ts"]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, "");
}

describe("API calls", () => {
  it("go through lib/api/client.ts, never a raw fetch()", () => {
    const offenders = SCAN_DIRS.flatMap((d) => {
      try {
        return sourceFiles(join(ROOT, d));
      } catch {
        return [];
      }
    })
      .map((path) => relative(ROOT, path))
      .filter((rel) => !ALLOWED.has(rel))
      .filter((rel) => /(^|[^\w.])fetch\s*\(/.test(withoutComments(readFileSync(join(ROOT, rel), "utf8"))));
    expect(offenders).toEqual([]);
  });
});
