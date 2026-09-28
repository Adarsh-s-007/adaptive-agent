// Tiny pub/sub so dashboard state can drive the WebGL layer without importing three.js.

export type HealthState = "connected" | "demo" | "offline" | "unknown";

export type SceneEvent =
  | { type: "ripple"; x: number; y: number; color?: string; strength?: number }
  | { type: "wave"; x: number; y: number; color: string }
  | { type: "tint"; color: string | null }
  | { type: "busy"; value: boolean }
  | { type: "health"; value: HealthState }
  | { type: "logo-hover" };

type Listener = (event: SceneEvent) => void;

const listeners = new Set<Listener>();
// Last value of each state-like event, replayed to late subscribers (the scene loads lazily).
const sticky = new Map<string, SceneEvent>();

export function emitScene(event: SceneEvent) {
  if (event.type === "tint" || event.type === "busy" || event.type === "health") sticky.set(event.type, event);
  listeners.forEach((listener) => listener(event));
}

export function onScene(listener: Listener): () => void {
  listeners.add(listener);
  sticky.forEach((event) => listener(event));
  return () => { listeners.delete(listener); };
}
