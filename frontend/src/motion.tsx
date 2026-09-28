import { useEffect } from "react";
import { motion, useSpring, useTransform, type Variants } from "framer-motion";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

export const tabMotion = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT },
};

export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.05 } },
};

export const rise: Variants = {
  hidden: { opacity: 0, y: 18, scale: 0.98 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: EASE_OUT } },
};

export const hoverLift = {
  whileHover: { y: -4, transition: { type: "spring", stiffness: 380, damping: 24 } },
};

export const listItem = (index: number) => ({
  initial: { opacity: 0, x: -12 },
  animate: { opacity: 1, x: 0 },
  transition: { duration: 0.35, ease: EASE_OUT, delay: Math.min(index, 12) * 0.035 },
});

export const overlayMotion = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.2 },
};

export const modalMotion = {
  initial: { opacity: 0, y: 26, scale: 0.95 },
  animate: { opacity: 1, y: 0, scale: 1, transition: { type: "spring", stiffness: 340, damping: 28 } },
  exit: { opacity: 0, y: 14, scale: 0.97, transition: { duration: 0.16 } },
};

export const bannerMotion = {
  initial: { opacity: 0, y: -8, height: 0 },
  animate: { opacity: 1, y: 0, height: "auto" },
  exit: { opacity: 0, y: -6, height: 0 },
  transition: { duration: 0.28, ease: EASE_OUT },
};

export function AnimatedNumber({ value }: { value: number }) {
  const spring = useSpring(0, { stiffness: 90, damping: 20 });
  const text = useTransform(spring, (latest) => Math.round(latest).toString());
  useEffect(() => { spring.set(value); }, [spring, value]);
  return <motion.span>{text}</motion.span>;
}

/** Material-style ink ripple on every button press (pure DOM, no re-renders). */
export function useButtonRipples() {
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const button = (event.target as Element | null)?.closest?.("button");
      if (!button || button.disabled) return;
      const rect = button.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height) * 2.2;
      const ink = document.createElement("span");
      ink.className = "btn-ripple";
      ink.setAttribute("aria-hidden", "true");
      ink.style.width = ink.style.height = size + "px";
      ink.style.left = event.clientX - rect.left - size / 2 + "px";
      ink.style.top = event.clientY - rect.top - size / 2 + "px";
      button.appendChild(ink);
      window.setTimeout(() => ink.remove(), 700);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, []);
}
