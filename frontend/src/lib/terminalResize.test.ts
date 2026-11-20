import { describe, expect, it, vi } from "vitest";
import {
  clampSize,
  createSizeSync,
  MAX_COLS,
  MAX_ROWS,
  MIN_COLS,
  MIN_ROWS,
  resizeMessage,
  scheduleSettledSync,
  sizeQuery,
} from "./terminalResize";

describe("clampSize", () => {
  it("keeps a usable size", () => {
    expect(clampSize(120, 40)).toEqual({ cols: 120, rows: 40 });
  });

  it("rejects sizes that cannot be a real terminal", () => {
    // 0x0 / 1x1 is what a minimized panel measures; sending it would give the
    // PTY a 1-column shell.
    expect(clampSize(0, 0)).toBeNull();
    expect(clampSize(5, 3)).toBeNull();
    expect(clampSize(NaN, 40)).toBeNull();
    expect(clampSize(undefined, undefined)).toBeNull();
    expect(clampSize("wide", 40)).toBeNull();
  });

  it("caps absurd sizes instead of rejecting them", () => {
    expect(clampSize(100000, 100000)).toEqual({ cols: MAX_COLS, rows: MAX_ROWS });
  });

  it("accepts the minimum", () => {
    expect(clampSize(MIN_COLS, MIN_ROWS)).toEqual({ cols: MIN_COLS, rows: MIN_ROWS });
  });
});

describe("wire format", () => {
  it("builds the resize frame the backend parses", () => {
    expect(resizeMessage({ cols: 100, rows: 30 })).toBe(
      '{"type":"resize","cols":100,"rows":30}',
    );
  });

  it("carries the initial size in the connect URL", () => {
    expect(sizeQuery({ cols: 132, rows: 43 })).toBe("&cols=132&rows=43");
  });

  it("omits the query when the size is unknown", () => {
    expect(sizeQuery(null)).toBe("");
    expect(sizeQuery({ cols: 0, rows: 0 })).toBe("");
  });
});

describe("createSizeSync", () => {
  const harness = (initial: { cols: number; rows: number } | null, fitImpl?: () => void) => {
    const sent: Array<{ cols: number; rows: number }> = [];
    let current = initial;
    let fitCalls = 0;
    const sizeSync = createSizeSync({
      fit: () => {
        fitCalls += 1;
        if (fitImpl) fitImpl();
      },
      getSize: () => current,
      send: (s) => sent.push(s),
    });
    return {
      sizeSync,
      sent,
      setSize: (s: { cols: number; rows: number } | null) => {
        current = s;
      },
      fitCalls: () => fitCalls,
    };
  };

  it("sends the fitted size once", () => {
    const h = harness({ cols: 120, rows: 40 });
    h.sizeSync.sync();
    expect(h.sent).toEqual([{ cols: 120, rows: 40 }]);
  });

  it("does not repeat an unchanged size", () => {
    const h = harness({ cols: 120, rows: 40 });
    h.sizeSync.sync();
    h.sizeSync.sync();
    h.sizeSync.sync();
    expect(h.sent).toHaveLength(1);
  });

  it("sends again after the panel is resized", () => {
    const h = harness({ cols: 120, rows: 40 });
    h.sizeSync.sync();
    h.setSize({ cols: 80, rows: 24 });
    h.sizeSync.sync();
    expect(h.sent).toEqual([
      { cols: 120, rows: 40 },
      { cols: 80, rows: 24 },
    ]);
  });

  it("survives fit() throwing before the container is laid out", () => {
    // The minimized-panel case: xterm is not open yet, fit() throws. A naive
    // implementation loses the size forever because nothing retries.
    const h = harness({ cols: 0, rows: 0 }, () => {
      throw new Error("not laid out");
    });
    expect(() => h.sizeSync.sync()).not.toThrow();
    expect(h.sent).toHaveLength(0);
    h.setSize({ cols: 100, rows: 30 });
    h.sizeSync.sync();
    expect(h.sent).toEqual([{ cols: 100, rows: 30 }]);
  });

  it("flushes the last size for a socket that was not open yet", () => {
    // The first ResizeObserver callback opens the socket in the same tick, so its
    // send is dropped while CONNECTING; onopen must be able to re-deliver it.
    let open = false;
    const sent: Array<{ cols: number; rows: number }> = [];
    const sizeSync = createSizeSync({
      fit: () => undefined,
      getSize: () => ({ cols: 90, rows: 25 }),
      send: (s) => {
        if (open) sent.push(s);
      },
    });
    sizeSync.sync();
    expect(sent).toHaveLength(0);
    open = true;
    sizeSync.flush();
    expect(sent).toEqual([{ cols: 90, rows: 25 }]);
    expect(sizeSync.last()).toEqual({ cols: 90, rows: 25 });
  });

  it("never sends a size it cannot vouch for", () => {
    const h = harness(null);
    h.sizeSync.sync();
    h.sizeSync.flush();
    expect(h.sent).toHaveLength(0);
    expect(h.sizeSync.last()).toBeNull();
  });
});

describe("scheduleSettledSync", () => {
  it("runs once immediately and again as layout and fonts settle", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const fonts: { ready: Promise<void> } = { ready: Promise.resolve() };
    const cancel = scheduleSettledSync(fn, {
      setTimeout: (cb, ms) => setTimeout(cb, ms) as unknown as number,
      clearTimeout: (id) => clearTimeout(id),
    }, fonts);

    expect(fn).toHaveBeenCalled(); // immediate
    vi.runAllTimers();
    expect(fn.mock.calls.length).toBeGreaterThan(1); // settle passes
    cancel();
    vi.useRealTimers();
  });

  it("stops calling back after cancel", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const cancel = scheduleSettledSync(fn, {
      setTimeout: (cb, ms) => setTimeout(cb, ms) as unknown as number,
      clearTimeout: (id) => clearTimeout(id),
    }, undefined);
    const before = fn.mock.calls.length;
    cancel();
    vi.runAllTimers();
    expect(fn.mock.calls.length).toBe(before);
    vi.useRealTimers();
  });

  it("works when document.fonts is unavailable", () => {
    const fn = vi.fn();
    expect(() =>
      scheduleSettledSync(fn, { setTimeout: () => 0, clearTimeout: () => undefined }, undefined),
    ).not.toThrow();
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
