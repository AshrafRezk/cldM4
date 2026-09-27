const FINE = "(pointer: fine)";
const REDUCE = "(prefers-reduced-motion: reduce)";

export function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia(REDUCE).matches;
}

export function haptic(kind = "tap") {
  if (typeof window === "undefined" || prefersReducedMotion()) return;
  const pattern = kind === "success" ? [10, 24, 16] : kind === "warn" ? [18, 32, 18] : kind === "select" ? [6] : [9];
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* desktop browsers throw or no-op */
  }
}

export function magneticProps(strength = 0.16) {
  return {
    onPointerMove(event) {
      if (prefersReducedMotion()) return;
      if (!window.matchMedia(FINE).matches) return;
      const node = event.currentTarget;
      const box = node.getBoundingClientRect();
      const x = (event.clientX - box.left - box.width / 2) * strength;
      const y = (event.clientY - box.top - box.height / 2) * strength;
      node.style.setProperty("--tx", `${x.toFixed(1)}px`);
      node.style.setProperty("--ty", `${y.toFixed(1)}px`);
    },
    onPointerLeave(event) {
      event.currentTarget.style.setProperty("--tx", "0px");
      event.currentTarget.style.setProperty("--ty", "0px");
    },
  };
}
