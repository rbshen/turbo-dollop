import { describe, expect, it } from "vitest";

import BreadthSectorPage, { generateMetadata } from "@/app/breadth/[sector]/page";
import { BreadthSectorView } from "@/components/breadth/BreadthSectorView";

// A thin test for the async server-component wrapper only -- BreadthSectorView's own rendered
// behavior (tabs, fetch, empty/error/unknown states) is covered by BreadthSectorView.test.tsx.
describe("BreadthSectorPage", () => {
  it("uppercases a lowercase sector param before handing it to the view", async () => {
    const element = await BreadthSectorPage({ params: Promise.resolve({ sector: "xlk" }) });
    expect(element.type).toBe(BreadthSectorView);
    expect(element.props.sector).toBe("XLK");
  });

  it("passes an already-uppercase param through unchanged", async () => {
    const element = await BreadthSectorPage({ params: Promise.resolve({ sector: "XLF" }) });
    expect(element.props.sector).toBe("XLF");
  });

  it("titles the page with the uppercased sector", async () => {
    const metadata = await generateMetadata({ params: Promise.resolve({ sector: "xlk" }) });
    expect(metadata.title).toBe("XLK Breadth");
  });
});
