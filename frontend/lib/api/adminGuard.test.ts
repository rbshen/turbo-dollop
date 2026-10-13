import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// The UI hides admin controls from a viewer (the backend is what refuses them: 403). This test keeps a NEW control from shipping
// unguarded. It is a file-level static check, not a proof: a file that calls a write (apiPost / apiPut / apiPatch / apiDelete), calls
// one of the admin-only reads, or imports a function that does, must either contain a guard itself (`AdminOnly`, `isAdmin`, or the
// `SettingsFooter` that hides Save for a viewer) or be rendered only from files that do. An unguarded chain that reaches a page
// fails here. What it cannot see: a guard in the file that is not wrapped around the right control. Review the diff for that.
//
// Admin-only reads (core/route_roles.py): cron-health, data-source-health, data-groups, cash-flow-cell-check.
const ROOT = join(__dirname, "..", "..");
const SCAN_DIRS = ["app", "components", "lib"];
const SKIP = [/^lib\/api\/client\.ts$/, /^lib\/auth\//, /^app\/styleguide\//]; // the client itself; sign-in/out (allowed for a viewer); the admin-only styleguide page

const MARKER = /\b(AdminOnly|isAdmin|SettingsFooter)\b/;
const WRITE_CALL = /\bapi(?:Post|Put|Patch|Delete)\b/;
const ADMIN_READ = /cash-flow-cell-check|\/config\/cron-health|\/config\/data-source-health|\/config\/data-groups/;

// Files that write but whose guard lives in a component they render, so the marker is not in the file itself.
const GUARDED_ELSEWHERE: Record<string, string> = {
  "components/etf-screener/SavedEtfFiltersBar.tsx": "renders SavedFiltersBarView, which hides Save view and Delete view for a viewer (isAdmin)",
};

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

const files = new Map<string, string>(); // repo-relative path -> source without comments
for (const dir of SCAN_DIRS) {
  for (const path of sourceFiles(join(ROOT, dir))) {
    const rel = relative(ROOT, path).split("\\").join("/");
    if (!SKIP.some((re) => re.test(rel))) files.set(rel, withoutComments(readFileSync(path, "utf8")));
  }
}

function resolveImport(from: string, spec: string): string | null {
  const base = spec.startsWith("@/") ? spec.slice(2) : spec.startsWith(".") ? join(dirname(from), spec).split("\\").join("/") : null;
  if (base === null) return null;
  for (const candidate of [`${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`]) {
    if (existsSync(join(ROOT, candidate))) return candidate;
  }
  return null;
}

function imports(rel: string): { target: string; names: string[] }[] {
  const src = files.get(rel) ?? "";
  const out: { target: string; names: string[] }[] = [];
  for (const m of src.matchAll(/(?:import|export)\s*(?:type\s+)?(?:\{([^}]*)\}|\*\s+as\s+\w+|\w+)?\s*(?:,\s*\{([^}]*)\})?\s*from\s*"([^"]+)"/g)) {
    const target = resolveImport(rel, m[3]);
    if (!target) continue;
    const names = [m[1], m[2]]
      .filter(Boolean)
      .flatMap((list) => list!.split(","))
      .map((n) => n.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0].trim())
      .filter(Boolean);
    out.push({ target, names });
  }
  return out;
}

// The exports of a hook module that write or read admin-only data: every non-`use*` export of a module that calls a write (they are
// the mutators), plus the `use*` hooks of a module that reads an admin-only endpoint (such a module has no other kind).
function mutatorExports(rel: string): Set<string> {
  const src = files.get(rel) ?? "";
  const names = new Set<string>();
  const exportRe = /export\s+(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+))/g;
  for (const m of src.matchAll(exportRe)) {
    const name = m[1] ?? m[2];
    if (!name.startsWith("use") || ADMIN_READ.test(src)) names.add(name);
  }
  return names;
}

const hookModules = [...files.keys()].filter((rel) => rel.startsWith("lib/") && (WRITE_CALL.test(files.get(rel)!) || ADMIN_READ.test(files.get(rel)!)));
const mutatorsByModule = new Map(hookModules.map((rel) => [rel, mutatorExports(rel)]));

// Callers: a non-lib file that makes the call itself, or imports a mutator of a lib module.
const callers = [...files.keys()].filter((rel) => {
  const src = files.get(rel)!;
  if (!rel.startsWith("lib/") && (WRITE_CALL.test(src) || ADMIN_READ.test(src))) return true;
  return imports(rel).some(({ target, names }) => {
    const muts = mutatorsByModule.get(target);
    return muts !== undefined && !(target === rel) && names.some((n) => muts.has(n));
  });
});

const importersOf = (target: string) => [...files.keys()].filter((rel) => imports(rel).some((i) => i.target === target));
const isGuarded = (rel: string) => MARKER.test(files.get(rel)!) || rel in GUARDED_ELSEWHERE;
const isRoute = (rel: string) => /^app\/.*\/?(page|layout)\.tsx$/.test(rel);

describe("admin controls are behind a guard", () => {
  it("finds the write-capable files it is meant to police (so it cannot pass by finding nothing)", () => {
    for (const expected of [
      "components/ticker/RefreshButton.tsx",
      "components/screener/RecomputeButton.tsx",
      "components/watchlist/WatchlistDeleteButton.tsx",
      "components/watchlist/WatchlistNameEditor.tsx",
      "components/settings/MoatSettingsForm.tsx",
      "components/settings/FmpDataGroupsSection.tsx",
      "components/settings/ScheduledJobsSection.tsx",
      "components/ticker/SecCellCheckButton.tsx",
      "components/ticker/EconomicMoatTab.tsx",
      "components/step3/ManualCalculationPanel.tsx",
      "components/step5/BankCapitalMetricsForm.tsx",
      "components/ticker/AddToWatchlistButton.tsx",
      "components/ticker/UniverseControl.tsx",
      "components/screener/SavedFiltersBar.tsx",
      "components/etf-screener/SavedEtfFiltersBar.tsx",
    ]) {
      expect(callers, expected).toContain(expected);
    }
  });

  it("no page reaches a write or an admin-only read through files that carry no guard", () => {
    const unguardedPages: string[] = [];
    const seen = new Set<string>();
    const walk = (rel: string, chain: string[]) => {
      if (seen.has(rel)) return;
      seen.add(rel);
      if (isGuarded(rel)) return;
      if (isRoute(rel)) {
        unguardedPages.push([...chain, rel].reverse().join(" <- "));
        return;
      }
      for (const importer of importersOf(rel)) walk(importer, [...chain, rel]);
    };
    for (const rel of callers) {
      if (rel.startsWith("lib/")) continue; // a hook module is only reached through the files that import it
      walk(rel, []);
    }
    expect(unguardedPages).toEqual([]);
  });

  it("every file in the allowlist still exists and still writes", () => {
    for (const rel of Object.keys(GUARDED_ELSEWHERE)) {
      expect(callers).toContain(rel);
    }
  });
});
