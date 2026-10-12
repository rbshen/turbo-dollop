"use client";

import { Component, type ReactNode } from "react";

import { MoatCheckFrame, MoatCheckHeading } from "@/components/ticker/MoatCheckCard";

// An error boundary around ONLY the Independent check card: a stored row the readers did not expect (or a bug in drawing it) must not take
// the whole Moat tab down, and the rating selector above it keeps working. A plain React boundary on purpose: Next's component-level
// `unstable_catchError` is marked unstable, and this needs no framework API. Keyed by ticker by the caller, so moving to another ticker
// tries again.
export class MoatCheckBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Independent check card failed to render", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <MoatCheckFrame>
          <MoatCheckHeading />
          <p className="text-sm text-text-secondary">This check can&apos;t be displayed.</p>
        </MoatCheckFrame>
      );
    }
    return this.props.children;
  }
}
