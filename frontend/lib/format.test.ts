import { describe, expect, it } from "vitest";

import {
  currencyPrefix,
  fmtAxisMoney,
  fmtCompactMoney,
  fmtMoney,
  fmtSignedCompactMoneyTooltip,
  fmtSignedDaysTooltip,
  fmtSignedMoney,
  fmtSignedPctTooltip,
  fmtSignedRatioTooltip,
  joinNatural,
  pickAxisMoneyUnit,
} from "@/lib/format";

describe("currencyPrefix", () => {
  it("maps known currencies to their unambiguous prefix", () => {
    expect(currencyPrefix("USD")).toBe("$");
    expect(currencyPrefix("CNY")).toBe("CN¥");
    expect(currencyPrefix("JPY")).toBe("¥");
    expect(currencyPrefix("EUR")).toBe("€");
    expect(currencyPrefix("GBP")).toBe("£");
  });

  it("falls back to '<CODE> ' for an unmapped currency rather than guessing a symbol", () => {
    expect(currencyPrefix("TWD")).toBe("TWD ");
  });
});

describe("fmtMoney", () => {
  it("defaults to USD, byte-identical to before the currency parameter existed", () => {
    expect(fmtMoney(1234.5)).toBe("$1,234.50");
    expect(fmtMoney(-1234.5)).toBe("-$1,234.50");
  });

  it("uses the given currency's prefix", () => {
    expect(fmtMoney(1234.5, "CNY")).toBe("CN¥1,234.50");
    expect(fmtMoney(-1234.5, "CNY")).toBe("-CN¥1,234.50");
  });
});

describe("fmtSignedMoney", () => {
  it("keeps the sign prefix ahead of a non-USD currency prefix", () => {
    expect(fmtSignedMoney(1.5, "CNY")).toBe("+CN¥1.50");
    expect(fmtSignedMoney(-1.5, "CNY")).toBe("-CN¥1.50");
  });
});

describe("fmtCompactMoney", () => {
  it("applies the currency prefix at every magnitude tier", () => {
    expect(fmtCompactMoney(4_900_000_000_000, "CNY")).toBe("CN¥4.90T");
    expect(fmtCompactMoney(482_000_000, "CNY")).toBe("CN¥482.00M");
    expect(fmtCompactMoney(500, "CNY")).toBe("CN¥500.00");
  });
});

describe("fmtAxisMoney", () => {
  it("applies the currency prefix to an axis tick", () => {
    const unit = pickAxisMoneyUnit(4_900_000_000_000);
    expect(fmtAxisMoney(4_900_000_000_000, unit, "CNY")).toBe("CN¥5T");
  });
});

describe("fmtSignedPctTooltip", () => {
  it("uses a true minus sign (U+2212) for negatives and a plus for positives", () => {
    expect(fmtSignedPctTooltip(12.345)).toBe("+12.35%");
    expect(fmtSignedPctTooltip(-3.2)).toBe("−3.20%");
  });

  it("shows no sign for a display-zero value", () => {
    expect(fmtSignedPctTooltip(0)).toBe("0.00%");
    expect(fmtSignedPctTooltip(0.001)).toBe("0.00%");
  });
});

describe("fmtSignedCompactMoneyTooltip", () => {
  it("signs every magnitude tier with a true minus sign for negatives", () => {
    expect(fmtSignedCompactMoneyTooltip(1_200_000_000)).toBe("+$1.20B");
    expect(fmtSignedCompactMoneyTooltip(-1_200_000_000)).toBe("−$1.20B");
    expect(fmtSignedCompactMoneyTooltip(1_200_000)).toBe("+$1.20M");
    expect(fmtSignedCompactMoneyTooltip(-500)).toBe("−$500.00");
  });

  it("applies the currency prefix ahead of the sign-formatted magnitude", () => {
    expect(fmtSignedCompactMoneyTooltip(1_200_000_000, "CNY")).toBe("+CN¥1.20B");
  });

  it("shows no sign for zero", () => {
    expect(fmtSignedCompactMoneyTooltip(0)).toBe("$0.00");
  });
});

describe("fmtSignedDaysTooltip", () => {
  it("uses a true minus sign and 2 decimals by default (matches the CCC tooltip's precedent)", () => {
    expect(fmtSignedDaysTooltip(63.4)).toBe("+63.40 days");
    expect(fmtSignedDaysTooltip(-3.2)).toBe("−3.20 days");
  });

  it("shows no sign for a display-zero value", () => {
    expect(fmtSignedDaysTooltip(0)).toBe("0.00 days");
  });
});

describe("fmtSignedRatioTooltip", () => {
  it("uses a true minus sign for negatives and a plus for positives", () => {
    expect(fmtSignedRatioTooltip(1.25)).toBe("+1.25x");
    expect(fmtSignedRatioTooltip(-0.4)).toBe("−0.40x");
  });

  it("shows no sign for a display-zero value", () => {
    expect(fmtSignedRatioTooltip(0)).toBe("0.00x");
  });
});

describe("joinNatural", () => {
  it("joins step names as prose", () => {
    expect(joinNatural([])).toBe("");
    expect(joinNatural(["Debt"])).toBe("Debt");
    expect(joinNatural(["Debt", "Growth Rate"])).toBe("Debt and Growth Rate");
    expect(joinNatural(["Financials", "Debt", "Growth Rate"])).toBe("Financials, Debt and Growth Rate");
  });
});
