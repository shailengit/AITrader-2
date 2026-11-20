/**
 * Terminal <-> PTY size synchronisation.
 *
 * The backend spawns the shell in a PTY whose size only ever changes when the
 * client tells it to. When that size disagrees with what xterm actually renders,
 * interactive programs (claude, vim, htop) wrap lines for the wrong width and
 * overwrite themselves at the right edge of the panel — the "long input lines
 * overwrite each other" bug.
 *
 * Three ways the two used to drift apart, all handled here:
 *   1. `fit()` is called before xterm has measured its cell size (right after
 *      `open()`, or before a web font finishes loading). It throws or proposes
 *      nothing, so no size was ever sent and the PTY stayed at its 24x80 default.
 *   2. The resize frame is sent while the socket is still CONNECTING, so it is
 *      dropped silently.
 *   3. The panel starts minimized at 1x1, so the first real size arrives from a
 *      ResizeObserver callback rather than from the initial mount.
 *
 * Deliberately free of DOM and xterm imports so it can be unit tested.
 */

export type TerminalSize = { cols: number; rows: number };

// Bounds shared with the manual dims box in TerminalHost and mirrored by the
// backend's own clamp, so neither side can push the PTY to a silly size.
export const MIN_COLS = 20;
export const MAX_COLS = 400;
export const MIN_ROWS = 10;
export const MAX_ROWS = 200;

/** Clamp a measured size. Returns null when it is not usable at all. */
export function clampSize(cols: unknown, rows: unknown): TerminalSize | null {
  const c = Math.trunc(Number(cols));
  const r = Math.trunc(Number(rows));
  if (!Number.isFinite(c) || !Number.isFinite(r)) return null;
  if (c < MIN_COLS || r < MIN_ROWS) return null;
  return { cols: Math.min(c, MAX_COLS), rows: Math.min(r, MAX_ROWS) };
}

/** The control frame the backend parses. */
export function resizeMessage(size: TerminalSize): string {
  return JSON.stringify({ type: "resize", cols: size.cols, rows: size.rows });
}

/**
 * Query-string fragment carrying the initial size, so the PTY is spawned at the
 * client's real dimensions instead of 24x80. Empty when the size is unknown.
 */
export function sizeQuery(size: TerminalSize | null | undefined): string {
  if (!size) return "";
  const clamped = clampSize(size.cols, size.rows);
  return clamped ? `&cols=${clamped.cols}&rows=${clamped.rows}` : "";
}

export interface SizeSync {
  /** Fit, read the terminal's size, and send it when it changed. */
  sync(): TerminalSize | null;
  /** Re-send the last known size regardless of dedupe (socket just opened). */
  flush(): TerminalSize | null;
  /** The last size successfully handed to `send`. */
  last(): TerminalSize | null;
}

/**
 * Wraps fit/measure/send with dedupe.
 *
 * `getSize` must read the terminal's own `cols`/`rows` *after* fitting: those are
 * exactly what xterm will render, whereas a pre-fit proposal can disagree.
 * `send` is expected to drop the frame when the socket is not open; the change is
 * still remembered so `flush()` can deliver it on connect.
 */
export function createSizeSync(opts: {
  fit: () => void;
  getSize: () => TerminalSize | null;
  send: (size: TerminalSize) => void;
}): SizeSync {
  let last: TerminalSize | null = null;

  const measure = (): TerminalSize | null => {
    try {
      opts.fit();
    } catch {
      // Container not laid out yet (panel minimized). Try again on the next tick.
    }
    const raw = opts.getSize();
    return raw ? clampSize(raw.cols, raw.rows) : null;
  };

  return {
    last: () => last,
    sync() {
      const size = measure();
      if (!size) return null;
      if (last && last.cols === size.cols && last.rows === size.rows) return last;
      last = size;
      try {
        opts.send(size);
      } catch {
        // Socket closing — the size is remembered and flushed on reconnect.
      }
      return last;
    },
    flush() {
      if (!last) return null;
      try {
        opts.send(last);
      } catch {
        // ignored
      }
      return last;
    },
  };
}

/**
 * Call `fn` now and again once layout, fonts and xterm's own cell measurement
 * have settled. xterm measures its cell size a frame after `open()` and again
 * when a web font swaps in; both change the column count without changing the
 * container, so no ResizeObserver event would fire.
 *
 * Returns a cancel function. `timers` and `fonts` are injectable for tests.
 */
export function scheduleSettledSync(
  fn: () => void,
  timers: { setTimeout: (cb: () => void, ms: number) => number; clearTimeout: (id: number) => void } =
    window,
  fonts: { ready?: Promise<unknown> } | undefined = typeof document === "undefined" ? undefined : document.fonts,
): () => void {
  fn();
  const ids = [0, 120, 350, 900].map((ms) => timers.setTimeout(fn, ms));
  if (fonts && fonts.ready) {
    Promise.resolve(fonts.ready).then(() => fn()).catch(() => undefined);
  }
  return () => ids.forEach((id) => timers.clearTimeout(id));
}
