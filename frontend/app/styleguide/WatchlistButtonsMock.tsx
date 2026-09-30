"use client";

// Styleguide reference for the Watchlist page controls and the two shared
// buttons (session 11): the real WatchlistNameEditor, WatchlistDeleteButton,
// ExportMenu and RefreshButton, with mock data and mock requests only. Each
// takes an optional seam (a swappable request and a starting state) that the
// real pages never pass, so nothing here can reach the backend. See "Watchlist
// page and shared buttons" in docs/design-system.md.
import type { ReactNode } from "react";

import { RefreshButton } from "@/components/ticker/RefreshButton";
import { ExportMenu } from "@/components/watchlist/ExportMenu";
import { WatchlistDeleteButton } from "@/components/watchlist/WatchlistDeleteButton";
import { WatchlistNameEditor } from "@/components/watchlist/WatchlistNameEditor";
import type { WatchlistOut } from "@/lib/api/types";

const MOCK_WATCHLIST: WatchlistOut = {
  id: -1,
  name: "Growth",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: [
    { ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" },
    { ticker: "MSFT", added_at: "2026-01-01T00:00:00Z" },
    { ticker: "NVDA", added_at: "2026-01-01T00:00:00Z" },
  ],
};

// Mock requests: resolve (or reject) after a beat, never touch the network.
const later = <T,>(value: T, ms = 600) => new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));
const mockRename = () => later(undefined);
const mockRenameRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("PUT /watchlists/-1 failed: 409 - Watchlist name already exists")), 600));
const mockRemove = () => later(undefined);
const mockRemoveRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("DELETE failed: 500")), 600));
const mockRefresh = () => later(undefined, 1200);
const mockRefreshRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("POST failed: 503")), 800));
const noop = () => {};

function Frame({ title, note, children, testId }: { title: string; note?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId}>
      <h3 className="mb-1 text-xs font-semibold text-text-secondary">{title}</h3>
      {note && <p className="mb-3 max-w-3xl text-xs text-text-tertiary">{note}</p>}
      {children}
    </div>
  );
}

function Case({ caption, testId, width, children }: { caption: string; testId: string; width?: number; children: ReactNode }) {
  return (
    <div data-testid={testId}>
      <p className="mb-1 text-xs text-text-tertiary">
        {caption}
        {width ? <span className="font-mono"> ({width}px)</span> : null}
      </p>
      <div style={width ? { width } : undefined} className={width ? "box-content border-x border-dashed border-border-subtle" : undefined}>
        {children}
      </div>
    </div>
  );
}

export function WatchlistButtonsMock() {
  return (
    <div className="space-y-10" data-testid="watchlist-buttons-mock">
      <Frame
        title="Rename"
        testId="rename-section"
        note="The real WatchlistNameEditor on the kit Input (wide, no overrides) with outline Save and Cancel. Every frame is live: type, press Enter to save or Escape to cancel. A save only pretends to succeed, nothing is sent."
      >
        <div className="flex flex-wrap items-start gap-x-12 gap-y-8">
          <Case caption="Idle" testId="rename-idle">
            <WatchlistNameEditor watchlist={MOCK_WATCHLIST} rename={mockRename} />
          </Case>
          <Case caption="Editing" testId="rename-editing">
            <WatchlistNameEditor watchlist={MOCK_WATCHLIST} rename={mockRename} defaultEditing />
          </Case>
          <Case caption="Invalid: empty name" testId="rename-invalid">
            <WatchlistNameEditor watchlist={MOCK_WATCHLIST} rename={mockRename} defaultEditing defaultValue="" defaultError="Name can't be empty" />
          </Case>
          <Case caption="Server error: duplicate name (Save to see one live)" testId="rename-server-error">
            <WatchlistNameEditor watchlist={MOCK_WATCHLIST} rename={mockRenameRejected} defaultEditing defaultValue="Value" defaultError={'"Value" already exists'} />
          </Case>
          <Case caption="Server error: the server's own message" testId="rename-server-message">
            <WatchlistNameEditor
              watchlist={MOCK_WATCHLIST}
              rename={mockRename}
              defaultEditing
              defaultError="name: String should have at most 100 characters"
            />
          </Case>
          <Case caption="Editing at a phone's content width: the buttons wrap below" testId="rename-narrow" width={311}>
            <WatchlistNameEditor watchlist={MOCK_WATCHLIST} rename={mockRename} defaultEditing />
          </Case>
        </div>
      </Frame>

      <Frame
        title="Delete watchlist"
        testId="delete-section"
        note="The real WatchlistDeleteButton: an icon trigger, an inline question with the destructive Confirm and an outline Cancel (no window.confirm). The request is a mock."
      >
        <div className="flex flex-wrap items-start gap-x-12 gap-y-8">
          <Case caption="Idle" testId="delete-idle">
            <WatchlistDeleteButton watchlist={MOCK_WATCHLIST} onDeleted={noop} remove={mockRemove} />
          </Case>
          <Case caption="Asking" testId="delete-confirming">
            <WatchlistDeleteButton watchlist={MOCK_WATCHLIST} onDeleted={noop} remove={mockRemove} defaultStatus="confirming" />
          </Case>
          <Case caption="After a failed delete (Confirm to see one live)" testId="delete-error">
            <WatchlistDeleteButton watchlist={MOCK_WATCHLIST} onDeleted={noop} remove={mockRemoveRejected} defaultStatus="error" />
          </Case>
        </div>
      </Frame>

      <Frame
        title="Export list"
        testId="export-section"
        note="The real ExportMenu: an outline sm trigger (32px) with a decorative caret. Escape closes it and returns focus to the trigger; so does a click outside."
      >
        <div className="flex flex-wrap items-start gap-x-12 gap-y-8">
          <Case caption="Closed" testId="export-closed">
            <ExportMenu onExportTradingView={noop} onExportThinkorswim={noop} />
          </Case>
          <div className="min-h-28">
            <Case caption="Open" testId="export-open">
              <ExportMenu defaultOpen onExportTradingView={noop} onExportThinkorswim={noop} />
            </Case>
          </div>
          <Case caption="Disabled (no rows)" testId="export-disabled">
            <ExportMenu disabled onExportTradingView={noop} onExportThinkorswim={noop} />
          </Case>
        </div>
      </Frame>

      <Frame
        title="Refresh"
        testId="refresh-section"
        note="The real RefreshButton, an outline sm Button. The first frame is live with a mock request (about a second, then it shows Refreshed and resets)."
      >
        <div className="flex flex-wrap items-start gap-x-12 gap-y-8">
          <Case caption="Idle (click for the live cycle)" testId="refresh-idle">
            <RefreshButton ticker="MOCK" request={mockRefresh} />
          </Case>
          <Case caption="Loading" testId="refresh-loading">
            <RefreshButton ticker="MOCK" request={mockRefresh} defaultStatus="loading" />
          </Case>
          <Case caption="Refreshed" testId="refresh-success">
            <RefreshButton ticker="MOCK" request={mockRefresh} defaultStatus="success" />
          </Case>
          <Case caption="Error (click for a live failure)" testId="refresh-error">
            <RefreshButton ticker="MOCK" request={mockRefreshRejected} defaultStatus="error" />
          </Case>
        </div>
      </Frame>

      <Frame title="Computed sizes" testId="watchlist-buttons-note">
        <div className="max-w-3xl text-xs text-text-secondary">
          <p className="mb-2 text-text-tertiary">Computed from the Button size tokens, not measured in a browser.</p>
          <table className="font-mono text-[11px]">
            <tbody>
              <tr>
                <td className="py-0.5 pr-4 font-sans">Rename input, Save, Cancel, Confirm (default size)</td>
                <td className="py-0.5">36px high; the input is 320px wide and wraps the buttons below it under about 480px</td>
              </tr>
              <tr>
                <td className="py-0.5 pr-4 font-sans">Export list, Refresh data (outline sm)</td>
                <td className="py-0.5">32px high, the same as before and the same as the Add to watchlist button beside Refresh</td>
              </tr>
              <tr>
                <td className="py-0.5 pr-4 font-sans">Rename and delete triggers (ghost icon-sm)</td>
                <td className="py-0.5">28px square</td>
              </tr>
              <tr>
                <td className="py-0.5 pr-4 font-sans">Table remove, confirm, cancel (outline icon-sm)</td>
                <td className="py-0.5">32px square, inside a 44px row</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Frame>
    </div>
  );
}
