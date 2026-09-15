import { describe, expect, it } from "vitest";

import { currencyPrefix, fmtAxisMoney, fmtCompactMoney, fmtMoney, fmtSignedMoney, pickAxisMoneyUnit } from "@/lib/format";

describe("currencyPrefix", () => {
  it("maps known currencies to their unambiguous prefix", () => {
    expect(currencyPrefix("USD")).toBe("$");
    expect(currencyPrefix("HKD")).toBe("HK$");
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
    expect(fmtMoney(1234.5, "HKD")).toBe("HK$1,234.50");
    expect(fmtMoney(-1234.5, "CNY")).toBe("-CN¥1,234.50");
  });
});

describe("fmtSignedMoney", () => {
  it("keeps the sign prefix ahead of a non-USD currency prefix", () => {
    expect(fmtSignedMoney(1.5, "HKD")).toBe("+HK$1.50");
    expect(fmtSignedMoney(-1.5, "HKD")).toBe("-HK$1.50");
  });
});

describe("fmtCompactMoney", () => {
  it("applies the currency prefix at every magnitude tier", () => {
    expect(fmtCompactMoney(4_900_000_000_000, "HKD")).toBe("HK$4.90T");
    expect(fmtCompactMoney(482_000_000, "HKD")).toBe("HK$482.00M");
    expect(fmtCompactMoney(500, "HKD")).toBe("HK$500.00");
  });
});

describe("fmtAxisMoney", () => {
  it("applies the currency prefix to an axis tick", () => {
    const unit = pickAxisMoneyUnit(4_900_000_000_000);
    expect(fmtAxisMoney(4_900_000_000_000, unit, "HKD")).toBe("HK$5T");
  });
});
