// Kept free of three.js imports so the main bundle can decide whether to load the 3D chunks.

export const MEMORY_TYPE_COLORS: Record<string, string> = {
  architecture_decision: "#8d7cff",
  security_rule: "#ff7a9c",
  api_contract: "#52d9ca",
  incident_fix: "#eab96a",
  coding_convention: "#6aa8ff",
};

export const MEMORY_TYPES = Object.keys(MEMORY_TYPE_COLORS);

export function memoryColor(type: string): string {
  return MEMORY_TYPE_COLORS[type] || "#a9a1ff";
}

let cachedSupport: boolean | null = null;

export function hasWebGL(): boolean {
  if (cachedSupport !== null) return cachedSupport;
  if (typeof window === "undefined" || !("WebGLRenderingContext" in window)) {
    cachedSupport = false;
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    cachedSupport = !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    cachedSupport = false;
  }
  return cachedSupport;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
