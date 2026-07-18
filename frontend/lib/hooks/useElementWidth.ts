"use client";

import { useCallback, useEffect, useState } from "react";

/** Measures an element's actual rendered width via ResizeObserver — the only
 * reliable way to make an SVG chart span its real container width, since a
 * hand-computed estimate can't know the container's true rendered size (it
 * depends on viewport, card padding, sidebar presence, etc). Returns 0 until
 * the first measurement lands.
 *
 * Uses a callback ref rather than useRef + useEffect(fn, []): the target
 * element here is gated behind a loading/error branch, so it doesn't exist
 * on this component's first mount — an empty-deps effect would attach to a
 * null ref once and never run again once the real element finally renders.
 * A callback ref fires exactly when the DOM node attaches, whenever that is. */
export function useElementWidth<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(0);

  const ref = useCallback((el: T | null) => {
    setNode(el);
  }, []);

  useEffect(() => {
    if (!node) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(node);

    return () => observer.disconnect();
  }, [node]);

  return [ref, width] as const;
}
