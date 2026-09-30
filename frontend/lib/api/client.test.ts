import { afterEach, describe, expect, it, vi } from "vitest";

import { apiPut, errorDetail } from "@/lib/api/client";

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status < 400,
      status,
      json: async () => {
        if (body === undefined) throw new Error("no body");
        return body;
      },
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

async function failure(status: number, body: unknown): Promise<unknown> {
  respond(status, body);
  return apiPut("/config/weinstein", { a: 1 }).catch((e) => e);
}

describe("request errors", () => {
  it("keeps a string detail (an HTTPException) as before", async () => {
    const e = await failure(409, { detail: "Name already taken" });
    expect((e as Error).message).toBe("PUT /config/weinstein failed: 409 - Name already taken");
    expect(errorDetail(e)).toBe("Name already taken");
  });

  it("formats a FastAPI 422 (a list of {loc, msg}) into a readable detail", async () => {
    const e = await failure(422, {
      detail: [
        { type: "greater_than_equal", loc: ["body", "ma_length"], msg: "Input should be greater than or equal to 2", input: 1 },
        { type: "string_too_short", loc: ["body", "rs_benchmark"], msg: "String should have at least 1 character", input: "" },
      ],
    });
    expect((e as Error).message).toContain("failed: 422");
    expect(errorDetail(e)).toBe(
      "ma_length: Input should be greater than or equal to 2; rs_benchmark: String should have at least 1 character",
    );
  });

  it("uses the bare message when a list item has no loc", async () => {
    expect(errorDetail(await failure(422, { detail: [{ msg: "Field required" }] }))).toBe("Field required");
  });

  it.each([
    ["no detail", { other: 1 }],
    ["an empty list", { detail: [] }],
    ["a list without messages", { detail: [{ type: "x" }] }],
    ["a non-JSON body", undefined],
  ])("has no detail for %s, and still reports the status", async (_name, body) => {
    const e = await failure(422, body);
    expect((e as Error).message).toBe("PUT /config/weinstein failed: 422");
    expect(errorDetail(e)).toBeUndefined();
  });
});
