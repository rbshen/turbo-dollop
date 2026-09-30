import { describe, expect, it } from "vitest";

import { FIELD_SIZE_CLASS, FIELD_SIZES, joinIds } from "@/lib/formControl";

describe("size tokens", () => {
  it("defines exactly short, medium, wide and full", () => {
    expect([...FIELD_SIZES]).toEqual(["short", "medium", "wide", "full"]);
  });

  it("maps to 96px, 176px and 320px, each capped at the container, and full fills it", () => {
    expect(FIELD_SIZE_CLASS.short).toBe("w-24 max-w-full");
    expect(FIELD_SIZE_CLASS.medium).toBe("w-44 max-w-full");
    expect(FIELD_SIZE_CLASS.wide).toBe("w-80 max-w-full");
    expect(FIELD_SIZE_CLASS.full).toBe("w-full");
  });
});

describe("joinIds", () => {
  it("joins the present ids and returns undefined when there are none", () => {
    expect(joinIds("a", undefined, "b", false, null)).toBe("a b");
    expect(joinIds(undefined, false)).toBeUndefined();
  });
});
