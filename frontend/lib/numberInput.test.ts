import { describe, expect, it } from "vitest";

import { checkNumber, stepNumber } from "@/lib/numberInput";

describe("checkNumber", () => {
  it("accepts plain integers, decimals and negatives", () => {
    for (const text of ["30", "0.5", ".5", "12.", "-3", "-0.25", " 7 "]) {
      expect(checkNumber(text).error).toBeNull();
    }
    expect(checkNumber("0.5").value).toBe(0.5);
  });

  it("rejects text that is not a number, including exponents and comma decimals", () => {
    for (const text of ["", " ", "abc", "1e5", "1e", "3,5", "+4", "--1", "1.2.3", "-"]) {
      expect(checkNumber(text)).toEqual({ value: null, error: "Enter a number." });
    }
  });

  it("requires a whole number when integer is set", () => {
    expect(checkNumber("2.5", { integer: true })).toEqual({ value: 2.5, error: "Enter a whole number." });
    expect(checkNumber("2", { integer: true }).error).toBeNull();
    expect(checkNumber("2.0", { integer: true }).error).toBeNull();
  });

  it("checks min and max, inclusive, with a message naming the bounds", () => {
    const rules = { min: 2, max: 200 };
    expect(checkNumber("2", rules).error).toBeNull();
    expect(checkNumber("200", rules).error).toBeNull();
    expect(checkNumber("1", rules).error).toBe("Enter a value between 2 and 200.");
    expect(checkNumber("201", rules).error).toBe("Enter a value between 2 and 200.");
    expect(checkNumber("-1", { min: 0 }).error).toBe("Enter a value of at least 0.");
    expect(checkNumber("51", { max: 50 }).error).toBe("Enter a value of at most 50.");
  });

  it("does not invent bounds when none are given", () => {
    expect(checkNumber("-99999.5").error).toBeNull();
    expect(checkNumber("1000000").error).toBeNull();
  });

  it("returns the parsed value even when out of range (never clamps it)", () => {
    expect(checkNumber("500", { max: 200 }).value).toBe(500);
  });
});

describe("stepNumber", () => {
  it("steps by step, and by ten times step when big", () => {
    expect(stepNumber(30, 1, 1, false)).toBe(31);
    expect(stepNumber(30, -1, 1, false)).toBe(29);
    expect(stepNumber(30, 1, 1, true)).toBe(40);
    expect(stepNumber(30, -1, 5, true)).toBe(-20);
  });

  it("does not leak float error", () => {
    expect(stepNumber(0.1, 1, 0.2, false)).toBe(0.3);
    expect(stepNumber(1.1, 1, 0.1, false)).toBe(1.2);
    expect(stepNumber(0.7, -1, 0.1, true)).toBe(-0.3);
  });

  it("stops at min and max", () => {
    expect(stepNumber(49, 1, 1, true, { max: 50 })).toBe(50);
    expect(stepNumber(2, -1, 1, false, { min: 2 })).toBe(2);
    expect(stepNumber(3, -1, 1, true, { min: 2 })).toBe(2);
  });
});
