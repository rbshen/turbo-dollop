"use client";

// Styleguide reference for the Watchlist page controls and the two shared
// buttons (session 11): the real WatchlistNameEditor, WatchlistDeleteButton,
// ExportMenu and RefreshButton, with mock data and mock requests only. Each
// takes an optional seam (a swappable request and a starting state) that the
// real pages never pass, so nothing here can reach the backend. See "Watchlist
// page and shared buttons" in docs/design-system.md.
import type { ReactNode } from "react";

import { RefreshButton } from "@/components/ticker/RefreshButton";
import { UniverseControlView } from "@/components/ticker/UniverseControl";
import { ExportMenu } from "@/components/watchlist/ExportMenu";
import { MultiExportPanel } from "@/components/watchlist/MultiExportPanel";
import { WatchlistDeleteButton } from "@/components/watchlist/WatchlistDeleteButton";
import { WatchlistNameEditor } from "@/components/watchlist/WatchlistNameEditor";
import type { UniverseAddOut, UniverseRemoveOut, UniverseStatusOut, WatchlistExportListOut, WatchlistOut } from "@/lib/api/types";

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

// The multi-list export panel's mock lists, created out of name order on purpose (the panel sorts E2 before E10), and the
// payload a mock export "fetches": one duplicate (AAPL), one ticker with no cached exchange, one empty list.
const mockList = (id: number, name: string, count: number): WatchlistOut => ({
  ...MOCK_WATCHLIST,
  id: -id,
  name,
  tickers: Array.from({ length: count }, (_, i) => ({ ticker: `MOCK${i}`, added_at: "2026-01-01T00:00:00Z" })),
});
const MOCK_EXPORT_WATCHLISTS: WatchlistOut[] = [mockList(1, "E10", 4), mockList(2, "E2", 3), mockList(3, "Growth", 0), mockList(4, "ETF", 2)];
const MOCK_EXPORT_PAYLOAD: Record<number, WatchlistExportListOut> = {
  [-1]: { id: -1, name: "E10", tickers: [{ ticker: "AAPL", exchange: "NASDAQ", sector: "Technology" }, { ticker: "NEWCO", exchange: null, sector: null }] },
  [-2]: { id: -2, name: "E2", tickers: [{ ticker: "AAPL", exchange: "NASDAQ", sector: "Technology" }, { ticker: "XOM", exchange: "NYSE", sector: "Energy" }] },
  [-3]: { id: -3, name: "Growth", tickers: [] },
  [-4]: { id: -4, name: "ETF", tickers: [{ ticker: "SPY", exchange: "AMEX", sector: null }] },
};
const mockLoadLists = (ids: number[]) => later(ids.map((id) => MOCK_EXPORT_PAYLOAD[id]), 400);
const mockLoadListsRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("GET /watchlists/export-data failed: 404 - No watchlist with id 9")), 400));

// Mock requests: resolve (or reject) after a beat, never touch the network.
const later = <T,>(value: T, ms = 600) => new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));
const mockRename = () => later(undefined);
const mockRenameRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("PUT /watchlists/-1 failed: 409 - Watchlist name already exists")), 600));
const mockRemove = () => later(undefined);
const mockRemoveRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("DELETE failed: 500")), 600));
const mockRefresh = () => later(undefined, 1200);
const mockRefreshRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("POST failed: 503")), 800));
const noop = () => {};

const MOCK_UNIVERSE: UniverseStatusOut = {
  ticker: "MOCK",
  kind: "stock",
  in_universe: false,
  classification: "browsed",
  state: "browsed",
  reasons: [],
  can_add: true,
  can_remove: false,
  added_at: null,
  added_source: null,
  delisted: false,
};
const MOCK_UNIVERSE_ADDED: UniverseStatusOut = { ...MOCK_UNIVERSE, in_universe: true, classification: "added", state: "added", can_add: false, can_remove: true };
const mockUniverseAdd = () => later({ changed: true } as UniverseAddOut, 1500);
const mockUniverseAddRejected = () => new Promise<never>((_, reject) => setTimeout(() => reject(new Error("POST /tickers/MOCK/universe failed: 400 - MOCK is not US-listed.")), 800));
const mockUniverseRemove = () => later({ changed: true } as UniverseRemoveOut, 800);

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
          <div className="min-h-36">
            <Case caption="Open with the multi-list item" testId="export-open-multi">
              <ExportMenu defaultOpen onExportTradingView={noop} onExportThinkorswim={noop} onExportMultiple={noop} />
            </Case>
          </div>
          <div className="min-h-36">
            <Case caption="Open, active list empty: only the multi-list item is live" testId="export-open-multi-only">
              <ExportMenu defaultOpen singleDisabled onExportTradingView={noop} onExportThinkorswim={noop} onExportMultiple={noop} />
            </Case>
          </div>
        </div>
      </Frame>

      <Frame
        title="Export multiple lists"
        testId="multi-export-section"
        note="The real MultiExportPanel, shown inline under the page header when the Export menu's third item is chosen. Tick lists, pick ONE format, Export writes ONE file: TradingView merges the lists' sectors (no list names), thinkorswim writes bare symbols one per line; both de-duplicate. The result line names what was left out (skipped for a missing exchange in the caution tone, never red). Lists are in natural name order. The request and the download are mocks; nothing is sent or saved."
      >
        <div className="flex flex-col gap-8">
          <Case caption="Idle: nothing ticked, Export disabled (tick two and press Export for a live mock run)" testId="multi-export-idle">
            <MultiExportPanel watchlists={MOCK_EXPORT_WATCHLISTS} onClose={noop} loadLists={mockLoadLists} download={noop} />
          </Case>
          <Case caption="Result with every note" testId="multi-export-result">
            <MultiExportPanel
              watchlists={MOCK_EXPORT_WATCHLISTS}
              onClose={noop}
              loadLists={mockLoadLists}
              download={noop}
              defaultSelected={[-1, -2, -3]}
              defaultResult={{
                summary: "Exported 2 symbols from 3 lists",
                notes: ["1 duplicate removed", "1 empty list skipped"],
                skippedNote: "1 skipped (no cached exchange)",
              }}
            />
          </Case>
          <Case caption="thinkorswim chosen, request failed (Export to see another one live)" testId="multi-export-error">
            <MultiExportPanel
              watchlists={MOCK_EXPORT_WATCHLISTS}
              onClose={noop}
              loadLists={mockLoadListsRejected}
              download={noop}
              defaultSelected={[-4]}
              defaultFormat="thinkorswim"
              defaultError="No watchlist with id 9"
            />
          </Case>
          <Case caption="At a phone's content width" testId="multi-export-narrow" width={311}>
            <MultiExportPanel watchlists={MOCK_EXPORT_WATCHLISTS} onClose={noop} loadLists={mockLoadLists} download={noop} defaultSelected={[-2]} />
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

      <Frame
        title="Universe control"
        testId="universe-section"
        note="The real UniverseControlView, the control the stock and ETF ticker headers share, drawn from a mock status with mock requests. It is deliberately quieter than the primary Add to watchlist button beside it: an outline Add, a ghost Remove with an inline two-step confirm, and a small note or error line under the button. There is no label saying the ticker is in the universe. Every other state (loading, a failed status, protected, delisted, non-US, kind unknown) renders nothing. In the real headers the note sits under the whole action cluster, not in the row."
      >
        <div className="flex flex-wrap items-start gap-x-12 gap-y-8">
          <Case caption="Browsed: Add (click for the live cycle)" testId="universe-add">
            <UniverseControlView status={MOCK_UNIVERSE} add={mockUniverseAdd} remove={mockUniverseRemove} />
          </Case>
          <Case caption="Adding" testId="universe-adding">
            <UniverseControlView status={MOCK_UNIVERSE} add={mockUniverseAdd} remove={mockUniverseRemove} defaultPhase="adding" />
          </Case>
          <Case caption="Add rejected (click for a live failure)" testId="universe-add-error">
            <UniverseControlView status={MOCK_UNIVERSE} add={mockUniverseAddRejected} remove={mockUniverseRemove} defaultMessage={{ tone: "error", text: "MOCK is not US-listed." }} />
          </Case>
          <Case caption="Added, score not computed (note under the button)" testId="universe-note">
            <UniverseControlView
              status={MOCK_UNIVERSE_ADDED}
              add={mockUniverseAdd}
              remove={mockUniverseRemove}
              defaultMessage={{ tone: "note", text: "Added. The score will be filled in by the nightly run." }}
            />
          </Case>
          <Case caption="Added: Remove only" testId="universe-added">
            <UniverseControlView status={MOCK_UNIVERSE_ADDED} add={mockUniverseAdd} remove={mockUniverseRemove} />
          </Case>
          <Case caption="Remove: confirming" testId="universe-confirming">
            <UniverseControlView status={MOCK_UNIVERSE_ADDED} add={mockUniverseAdd} remove={mockUniverseRemove} defaultPhase="confirming" />
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
                <td className="py-0.5 pr-4 font-sans">Add to Universe (outline sm), Remove from Universe (ghost sm)</td>
                <td className="py-0.5">32px high as an outline, 28px as a ghost, both quieter than the 32px primary Add to watchlist beside them</td>
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
