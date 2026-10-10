"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown until the placeholder scrolls near the viewport (the same shape as the content, so nothing jumps). */
  placeholder: ReactNode;
  /** How far outside the viewport counts as "in view", so the data is usually there by the time it is scrolled to. */
  rootMargin?: string;
}

/** Mounts its children (and so their data fetch) once the placeholder is scrolled into view, and keeps them mounted after. Without
 * IntersectionObserver (an old browser, jsdom) it mounts at once, so nothing is ever left unloaded. */
export function LazyMount({ children, placeholder, rootMargin = "200px" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (visible) return;
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible, rootMargin]);

  return <div ref={ref}>{visible ? children : placeholder}</div>;
}
