import { describe, expect, it } from "vitest";

import { checkNumber, formatNumberInput, isIncompleteNumberPrefix, stepNumber } from "@/lib/numberInput";

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

const SUFFIXES = { T: 1e12, B: 1e9, M: 1e6 };

describe("checkNumber: optional", () => {
  it("treats an empty or blank field as valid with a null value", () => {
    expect(checkNumber("", { optional: true })).toEqual({ value: null, error: null });
    expect(checkNumber("   ", { optional: true })).toEqual({ value: null, error: null });
  });

  it("still reports text that is not a number, and keeps the default (empty is an error) without it", () => {
    expect(checkNumber("abc", { optional: true })).toEqual({ value: null, error: "Enter a number." });
    expect(checkNumber("", {})).toEqual({ value: null, error: "Enter a number." });
    expect(checkNumber("")).toEqual({ value: null, error: "Enter a number." });
  });
});

describe("checkNumber: suffixes", () => {
  it.each([
    ["500M", 500_000_000],
    ["2B", 2_000_000_000],
    ["1T", 1_000_000_000_000],
    ["5T", 5_000_000_000_000],
    ["1.5t", 1_500_000_000_000],
    ["2 m", 2_000_000],
    ["1 B", 1_000_000_000],
    ["1.", 1],
    [".5", 0.5],
    ["12.", 12],
    [".5B", 500_000_000],
    ["12.B", 12_000_000_000],
    ["3000000000", 3_000_000_000],
  ])("reads %s as %d in base units", (text, expected) => {
    expect(checkNumber(text, { suffixes: SUFFIXES })).toEqual({ value: expected, error: null });
  });

  it.each([["5e"], ["1x"], ["1BX"], ["1BB"], ["abc"], ["1e5"], ["M"], ["1 gazillion"], ["--1"], ["1.2.3B"]])(
    "rejects %s",
    (text) => {
      expect(checkNumber(text, { suffixes: SUFFIXES })).toEqual({ value: null, error: "Enter a number." });
    },
  );

  it("applies min, max and integer to the value in base units", () => {
    expect(checkNumber("-5B", { suffixes: SUFFIXES, min: 0 })).toEqual({
      value: -5_000_000_000,
      error: "Enter a value of at least 0.",
    });
    expect(checkNumber("3B", { suffixes: SUFFIXES, max: 2_000_000_000 }).error).toBe("Enter a value of at most 2000000000.");
  });

  it("makes any letter invalid when no suffixes are given", () => {
    expect(checkNumber("5M")).toEqual({ value: null, error: "Enter a number." });
  });

  it("combines with optional", () => {
    expect(checkNumber("", { suffixes: SUFFIXES, optional: true })).toEqual({ value: null, error: null });
  });
});

describe("isIncompleteNumberPrefix", () => {
  it("is true only for -, . and -.", () => {
    for (const text of ["-", ".", "-.", " - ", " . "]) expect(isIncompleteNumberPrefix(text)).toBe(true);
    for (const text of ["", "1", "-1", "1.", ".5", "--", "..", "-.5", "1x", "a"]) {
      expect(isIncompleteNumberPrefix(text)).toBe(false);
    }
  });
});

describe("formatNumberInput", () => {
  it("returns an empty string for null and plain digits without suffixes", () => {
    expect(formatNumberInput(null)).toBe("");
    expect(formatNumberInput(1_000_000_000)).toBe("1000000000");
    expect(formatNumberInput(0.5)).toBe("0.5");
  });

  it.each([
    [1e9, "1B"],
    [5e12, "5T"],
    [1.5e9, "1.5B"],
    [2.5e12, "2.5T"],
    [2e6, "2M"],
    [1.5e6, "1.5M"],
    [1e12, "1T"],
    [1_234_567, "1234567"],
    [999_999, "999999"],
    [500, "500"],
    [0, "0"],
  ])("formats %d as the shortest exact form %s", (value, expected) => {
    expect(formatNumberInput(value, SUFFIXES)).toBe(expected);
  });

  it("only accepts a form that parses back to exactly the same number", () => {
    for (const value of [1e9, 1.5e9, 2.5e12, 7e6, 123_456_789, 12_345_678_901]) {
      expect(checkNumber(formatNumberInput(value, SUFFIXES), { suffixes: SUFFIXES }).value).toBe(value);
    }
  });
});
