import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

import { prefersReducedMotion } from "./support";

/*
 * Full-viewport decorative layer that sits behind the dashboard:
 *  - a tilted point field that ripples wherever the user clicks (plus soft ambient ripples)
 *  - small agent models that travel left -> right along horizontal lanes the DOM leaves empty,
 *    fading out whenever they would pass behind real content.
 */

const RIPPLE_SLOTS = 8;
const RIPPLE_LIFETIME = 4.2;
const FIELD_COLS = 200;
const FIELD_ROWS = 125;
const FIELD_W = 80;
const FIELD_H = 50;

const OBSTACLE_SELECTOR = [
  "header .brand", "header .head-actions", ".topbar > *", ".hero > *", ".empty > *",
  ".landing-actions > *", ".section-nav", ".panel", ".feature-strip", ".section-title",
  ".filter-row", ".memory-list li", ".empty-panel", ".audit-mini", ".activity-item",
  ".proof-panel", ".setup-footer", ".error", ".notice", ".overlay",
].join(",");
const OBSTACLE_PAD = 14;

type Rect = { left: number; top: number; right: number; bottom: number };

// ---------------------------------------------------------------------------
// DOM obstacle tracking (screen-space rects of real content)
// ---------------------------------------------------------------------------

function useObstacles() {
  const rects = useRef<Rect[]>([]);
  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const height = window.innerHeight;
      const next: Rect[] = [];
      document.querySelectorAll(OBSTACLE_SELECTOR).forEach((element) => {
        const box = element.getBoundingClientRect();
        if (!box.width || !box.height || box.bottom < 0 || box.top > height) return;
        next.push({
          left: box.left - OBSTACLE_PAD,
          top: box.top - OBSTACLE_PAD,
          right: box.right + OBSTACLE_PAD,
          bottom: box.bottom + OBSTACLE_PAD,
        });
      });
      rects.current = next;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    const interval = window.setInterval(schedule, 350);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return rects;
}

function overlaps(rects: Rect[], box: Rect): boolean {
  return rects.some((rect) => rect.left < box.right && rect.right > box.left &&
    rect.top < box.bottom && rect.bottom > box.top);
}

/** Free horizontal length (px) of a screen band after subtracting every obstacle crossing it. */
function freeWidth(rects: Rect[], top: number, bottom: number, width: number): number {
  const spans = rects
    .filter((rect) => rect.top < bottom && rect.bottom > top)
    .map((rect) => [Math.max(0, rect.left), Math.min(width, rect.right)] as const)
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0]);
  let covered = 0;
  let cursor = 0;
  for (const [start, end] of spans) {
    if (end <= cursor) continue;
    covered += end - Math.max(start, cursor);
    cursor = end;
  }
  return width - covered;
}

class LaneRegistry {
  private claims = new Map<number, number>();

  release(id: number) { this.claims.delete(id); }

  /** Picks a lane (feet y, px) with plenty of empty horizontal space, away from other agents. */
  claim(id: number, rects: Rect[], agentHeight: number): number | null {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const others = [...this.claims.entries()].filter(([key]) => key !== id).map(([, y]) => y);
    const candidates: { y: number; score: number }[] = [];
    for (let y = 96 + agentHeight; y < height - 18; y += 14) {
      if (others.some((other) => Math.abs(other - y) < agentHeight * 1.4)) continue;
      const score = freeWidth(rects, y - agentHeight - 6, y + 8, width) / width;
      if (score > 0.34) candidates.push({ y, score });
    }
    if (!candidates.length) return null;
    candidates.sort((a, b) => b.score - a.score);
    const pool = candidates.slice(0, Math.max(3, Math.ceil(candidates.length * 0.35)));
    const lane = pool[Math.floor(Math.random() * pool.length)].y;
    this.claims.set(id, lane);
    return lane;
  }
}

// ---------------------------------------------------------------------------
// Ripple field
// ---------------------------------------------------------------------------

const fieldVertex = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  uniform vec4 uRipples[${RIPPLE_SLOTS}];
  varying float vHeight;
  varying float vFade;

  void main() {
    vec3 p = position;
    float h = sin(p.x * 0.42 + uTime * 0.55) * 0.07 + cos(p.y * 0.5 + uTime * 0.4) * 0.07;
    for (int i = 0; i < ${RIPPLE_SLOTS}; i++) {
      vec4 r = uRipples[i];
      float age = uTime - r.z;
      if (age > 0.0 && age < ${RIPPLE_LIFETIME.toFixed(1)}) {
        float d = distance(p.xy, r.xy);
        float front = age * 3.4;
        float band = exp(-pow((d - front) * 1.25, 2.0));
        float life = 1.0 - age / ${RIPPLE_LIFETIME.toFixed(1)};
        h += sin((d - front) * 4.2) * band * r.w * life * life * 0.75;
      }
    }
    p.z += h;
    vHeight = h;

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    float depth = -mv.z;
    float edge = min(1.0 - abs(position.x) / ${(FIELD_W / 2).toFixed(1)}, 1.0 - abs(position.y) / ${(FIELD_H / 2).toFixed(1)});
    vFade = smoothstep(0.0, 0.18, edge) * smoothstep(46.0, 13.0, depth);
    gl_PointSize = 2.7 * uPixelRatio * (12.0 / depth) * (1.0 + clamp(abs(h) * 2.4, 0.0, 1.6));
    gl_Position = projectionMatrix * mv;
  }
`;

const fieldFragment = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  varying float vHeight;
  varying float vFade;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float soft = smoothstep(0.5, 0.05, d);
    vec3 color = mix(uColorA, uColorB, clamp(vHeight * 2.6 + 0.45, 0.0, 1.0));
    float alpha = soft * vFade * (0.2 + clamp(abs(vHeight) * 2.0, 0.0, 0.75));
    gl_FragColor = vec4(color, alpha);
  }
`;

function RippleField({ reduced }: { reduced: boolean }) {
  const points = useRef<THREE.Points>(null);
  const slot = useRef(0);
  const time = useRef(0);
  const { camera } = useThree();

  const geometry = useMemo(() => {
    const positions = new Float32Array(FIELD_COLS * FIELD_ROWS * 3);
    let offset = 0;
    for (let row = 0; row < FIELD_ROWS; row++) {
      for (let col = 0; col < FIELD_COLS; col++) {
        positions[offset++] = (col / (FIELD_COLS - 1) - 0.5) * FIELD_W;
        positions[offset++] = (row / (FIELD_ROWS - 1) - 0.5) * FIELD_H;
        positions[offset++] = 0;
      }
    }
    const next = new THREE.BufferGeometry();
    next.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return next;
  }, []);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 1.5) },
    uRipples: { value: Array.from({ length: RIPPLE_SLOTS }, () => new THREE.Vector4(0, 0, -100, 0)) },
    uColorA: { value: new THREE.Color("#7c6cf5") },
    uColorB: { value: new THREE.Color("#52d9ca") },
  }), []);

  useEffect(() => {
    const raycaster = new THREE.Raycaster();
    const plane = new THREE.Plane();
    const normal = new THREE.Vector3();
    const hit = new THREE.Vector3();

    const rippleAt = (clientX: number, clientY: number, strength: number) => {
      const field = points.current;
      if (!field) return;
      const ndc = new THREE.Vector2(
        (clientX / window.innerWidth) * 2 - 1,
        -(clientY / window.innerHeight) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, camera);
      normal.set(0, 0, 1).transformDirection(field.matrixWorld);
      plane.setFromNormalAndCoplanarPoint(normal, field.getWorldPosition(new THREE.Vector3()));
      if (!raycaster.ray.intersectPlane(plane, hit)) return;
      const local = field.worldToLocal(hit.clone());
      uniforms.uRipples.value[slot.current].set(local.x, local.y, time.current, strength);
      slot.current = (slot.current + 1) % RIPPLE_SLOTS;
    };

    const onPointerDown = (event: PointerEvent) => rippleAt(event.clientX, event.clientY, 1);
    window.addEventListener("pointerdown", onPointerDown, { passive: true });

    const ambient = reduced ? 0 : window.setInterval(() => {
      if (document.hidden) return;
      rippleAt(
        window.innerWidth * (0.1 + Math.random() * 0.8),
        window.innerHeight * (0.35 + Math.random() * 0.6),
        0.45 + Math.random() * 0.3,
      );
    }, 3400);

    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      if (ambient) window.clearInterval(ambient);
    };
  }, [camera, reduced, uniforms]);

  useFrame((_, delta) => {
    time.current += Math.min(delta, 0.05) * (reduced ? 0.15 : 1);
    uniforms.uTime.value = time.current;
  });

  return (
    <points ref={points} geometry={geometry} position={[0, -1, -4]} rotation={[-0.78, 0, 0]}>
      <shaderMaterial
        vertexShader={fieldVertex}
        fragmentShader={fieldFragment}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

type AgentKind = "walker" | "drone" | "rover";

type AgentSpec = { kind: AgentKind; color: string; speed: number };

const AGENT_SPECS: AgentSpec[] = [
  { kind: "walker", color: "#8d7cff", speed: 62 },
  { kind: "drone", color: "#52d9ca", speed: 88 },
  { kind: "rover", color: "#eab96a", speed: 54 },
  { kind: "walker", color: "#6aa8ff", speed: 70 },
  { kind: "drone", color: "#ff7a9c", speed: 80 },
];

type AgentMaterials = {
  shell: THREE.MeshStandardMaterial;
  accent: THREE.MeshStandardMaterial;
  glow: THREE.MeshBasicMaterial;
  halo: THREE.MeshBasicMaterial;
  ping: THREE.MeshBasicMaterial;
};

function useAgentMaterials(color: string): AgentMaterials {
  const materials = useMemo(() => ({
    shell: new THREE.MeshStandardMaterial({
      color: "#dfe2ff", roughness: 0.38, metalness: 0.35, flatShading: true, transparent: true,
    }),
    accent: new THREE.MeshStandardMaterial({
      color, emissive: color, emissiveIntensity: 0.35, roughness: 0.45, metalness: 0.2,
      flatShading: true, transparent: true,
    }),
    glow: new THREE.MeshBasicMaterial({ color, transparent: true, toneMapped: false }),
    halo: new THREE.MeshBasicMaterial({
      color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
    }),
    ping: new THREE.MeshBasicMaterial({
      color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
      side: THREE.DoubleSide,
    }),
  }), [color]);
  useEffect(() => () => Object.values(materials).forEach((material) => material.dispose()), [materials]);
  return materials;
}

type RigRefs = {
  a: React.MutableRefObject<THREE.Object3D | null>;
  b: React.MutableRefObject<THREE.Object3D | null>;
  c: React.MutableRefObject<THREE.Object3D | null>;
  d: React.MutableRefObject<THREE.Object3D | null>;
};

function WalkerModel({ m, rig }: { m: AgentMaterials; rig: RigRefs }) {
  return (
    <group ref={(o) => { rig.d.current = o; }}>
      <group ref={(o) => { rig.a.current = o; }} position={[-0.1, 0.34, 0]}>
        <mesh position={[0, -0.16, 0]} material={m.shell}><boxGeometry args={[0.1, 0.32, 0.12]} /></mesh>
        <mesh position={[0, -0.33, 0.03]} material={m.accent}><boxGeometry args={[0.12, 0.04, 0.18]} /></mesh>
      </group>
      <group ref={(o) => { rig.b.current = o; }} position={[0.1, 0.34, 0]}>
        <mesh position={[0, -0.16, 0]} material={m.shell}><boxGeometry args={[0.1, 0.32, 0.12]} /></mesh>
        <mesh position={[0, -0.33, 0.03]} material={m.accent}><boxGeometry args={[0.12, 0.04, 0.18]} /></mesh>
      </group>
      <mesh position={[0, 0.56, 0]} material={m.shell}><capsuleGeometry args={[0.18, 0.2, 4, 10]} /></mesh>
      <mesh position={[0, 0.58, 0.16]} material={m.accent}><boxGeometry args={[0.16, 0.12, 0.04]} /></mesh>
      <group ref={(o) => { rig.c.current = o; }} position={[0, 0.72, 0]}>
        <mesh position={[-0.25, -0.14, 0]} material={m.accent}><capsuleGeometry args={[0.05, 0.18, 3, 8]} /></mesh>
        <mesh position={[0.25, -0.14, 0]} material={m.accent}><capsuleGeometry args={[0.05, 0.18, 3, 8]} /></mesh>
      </group>
      <mesh position={[0, 0.93, 0]} material={m.shell}><icosahedronGeometry args={[0.17, 1]} /></mesh>
      <mesh position={[0, 0.94, 0.135]} material={m.glow}><boxGeometry args={[0.22, 0.065, 0.05]} /></mesh>
      <mesh position={[0, 1.12, 0]} material={m.shell}><cylinderGeometry args={[0.012, 0.012, 0.16, 6]} /></mesh>
      <mesh position={[0, 1.21, 0]} material={m.glow}><sphereGeometry args={[0.035, 10, 10]} /></mesh>
    </group>
  );
}

function DroneModel({ m, rig }: { m: AgentMaterials; rig: RigRefs }) {
  return (
    <group ref={(o) => { rig.d.current = o; }}>
      <mesh position={[0, 0.72, 0]} material={m.shell}><icosahedronGeometry args={[0.22, 1]} /></mesh>
      <mesh position={[0, 0.74, 0.17]} material={m.glow}><sphereGeometry args={[0.07, 14, 14]} /></mesh>
      <group ref={(o) => { rig.a.current = o; }} position={[0, 0.72, 0]} rotation={[Math.PI / 2 - 0.35, 0, 0]}>
        <mesh material={m.accent}><torusGeometry args={[0.36, 0.028, 8, 40]} /></mesh>
        <mesh position={[0.36, 0, 0]} material={m.glow}><sphereGeometry args={[0.035, 8, 8]} /></mesh>
        <mesh position={[-0.36, 0, 0]} material={m.glow}><sphereGeometry args={[0.035, 8, 8]} /></mesh>
      </group>
      <mesh ref={(o) => { rig.b.current = o; }} position={[0, 0.4, 0]} rotation={[Math.PI, 0, 0]} material={m.halo}>
        <coneGeometry args={[0.1, 0.34, 14, 1, true]} />
      </mesh>
      <mesh ref={(o) => { rig.c.current = o; }} position={[0, 0.72, 0]} material={m.ping}>
        <ringGeometry args={[0.42, 0.46, 40]} />
      </mesh>
    </group>
  );
}

function RoverModel({ m, rig }: { m: AgentMaterials; rig: RigRefs }) {
  const wheel = (x: number, z: number) => (
    <mesh position={[x, 0.1, z]} rotation={[0, 0, Math.PI / 2]} material={m.accent}>
      <cylinderGeometry args={[0.1, 0.1, 0.07, 12]} />
    </mesh>
  );
  return (
    <group ref={(o) => { rig.d.current = o; }}>
      <group ref={(o) => { rig.a.current = o; }}>{wheel(-0.2, 0.15)}{wheel(0.2, 0.15)}</group>
      <group ref={(o) => { rig.b.current = o; }}>{wheel(-0.2, -0.15)}{wheel(0.2, -0.15)}</group>
      <mesh position={[0, 0.25, 0]} material={m.shell}><boxGeometry args={[0.38, 0.17, 0.5]} /></mesh>
      <mesh position={[0, 0.25, 0.26]} material={m.glow}><boxGeometry args={[0.26, 0.05, 0.02]} /></mesh>
      <mesh position={[0, 0.45, -0.1]} material={m.shell}><cylinderGeometry args={[0.02, 0.02, 0.26, 6]} /></mesh>
      <group ref={(o) => { rig.c.current = o; }} position={[0, 0.6, -0.1]}>
        <mesh material={m.accent}><boxGeometry args={[0.22, 0.12, 0.13]} /></mesh>
        <mesh position={[-0.05, 0.01, 0.07]} material={m.glow}><sphereGeometry args={[0.03, 8, 8]} /></mesh>
        <mesh position={[0.05, 0.01, 0.07]} material={m.glow}><sphereGeometry args={[0.03, 8, 8]} /></mesh>
      </group>
    </group>
  );
}

const MODEL_HEIGHT: Record<AgentKind, number> = { walker: 1.25, drone: 1.0, rover: 0.72 };

type AgentProps = {
  id: number;
  spec: AgentSpec;
  obstacles: React.MutableRefObject<Rect[]>;
  lanes: LaneRegistry;
};

function Agent({ id, spec, obstacles, lanes }: AgentProps) {
  const root = useRef<THREE.Group>(null);
  const shadow = useRef<THREE.Mesh>(null);
  const rig: RigRefs = { a: useRef(null), b: useRef(null), c: useRef(null), d: useRef(null) };
  const m = useAgentMaterials(spec.color);
  const shadowMaterial = useMemo(() => new THREE.MeshBasicMaterial({
    color: spec.color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }), [spec.color]);
  useEffect(() => () => shadowMaterial.dispose(), [shadowMaterial]);

  const state = useRef({
    x: -80 - id * 260,
    lane: null as number | null,
    wait: 0.4 + id * 0.9,
    opacity: 0,
    hiddenFor: 0,
    phase: Math.random() * Math.PI * 2,
    speed: spec.speed * (0.85 + Math.random() * 0.3),
  });

  useFrame(({ size, viewport, clock }, rawDelta) => {
    const group = root.current;
    if (!group) return;
    const delta = Math.min(rawDelta, 0.05);
    const s = state.current;
    const heightPx = THREE.MathUtils.clamp(size.height * 0.07, 40, 62) * (spec.kind === "rover" ? 0.72 : 1);
    const widthPx = heightPx * 0.8;

    if (s.lane === null) {
      s.wait -= delta;
      group.visible = false;
      if (s.wait <= 0) {
        s.lane = lanes.claim(id, obstacles.current, heightPx);
        if (s.lane === null) s.wait = 1.2;
      }
      return;
    }

    s.x += s.speed * delta;
    s.phase += delta * s.speed * 0.12;
    if (s.x > size.width + 90) {
      lanes.release(id);
      s.lane = null;
      s.x = -90;
      s.opacity = 0;
      s.wait = 0.6 + Math.random() * 2.8;
      group.visible = false;
      return;
    }

    const box = { left: s.x - widthPx / 2, right: s.x + widthPx / 2, top: s.lane - heightPx, bottom: s.lane + 4 };
    const blocked = overlaps(obstacles.current, box);
    s.hiddenFor = blocked ? s.hiddenFor + delta : 0;
    // Content moved over this lane (scroll, tab change): hop to a free lane while invisible.
    if (s.hiddenFor > 1.1 && s.opacity < 0.02) {
      lanes.release(id);
      const next = lanes.claim(id, obstacles.current, heightPx);
      if (next !== null) s.lane = next;
      s.hiddenFor = 0;
    }
    s.opacity = THREE.MathUtils.damp(s.opacity, blocked ? 0 : 1, blocked ? 14 : 5, delta);

    const unitsPerPx = viewport.height / size.height;
    const scale = (heightPx * unitsPerPx) / MODEL_HEIGHT[spec.kind];
    const pop = 0.82 + 0.18 * s.opacity;
    group.visible = s.opacity > 0.01;
    group.position.set(
      (s.x / size.width - 0.5) * viewport.width,
      (0.5 - s.lane / size.height) * viewport.height,
      0,
    );
    group.scale.setScalar(scale * pop);

    for (const material of [m.shell, m.accent, m.glow]) material.opacity = s.opacity;
    const t = clock.elapsedTime;
    const body = rig.d.current;

    if (spec.kind === "walker") {
      const swing = Math.sin(s.phase);
      if (rig.a.current) rig.a.current.rotation.x = swing * 0.6;
      if (rig.b.current) rig.b.current.rotation.x = -swing * 0.6;
      if (rig.c.current) rig.c.current.rotation.x = -swing * 0.08;
      if (body) body.position.y = Math.abs(Math.cos(s.phase)) * 0.04;
      m.halo.opacity = 0;
    } else if (spec.kind === "drone") {
      if (body) {
        body.position.y = Math.sin(t * 2.3 + id) * 0.08;
        body.rotation.z = -0.12 + Math.sin(t * 1.7 + id) * 0.04;
      }
      if (rig.a.current) rig.a.current.rotation.z += delta * 3.2;
      m.halo.opacity = s.opacity * (0.35 + Math.sin(t * 12 + id) * 0.12);
      const ping = rig.c.current;
      if (ping) {
        const cycle = (t * 0.45 + id * 0.3) % 1;
        ping.scale.setScalar(0.6 + cycle * 2.2);
        m.ping.opacity = s.opacity * (1 - cycle) * 0.55;
      }
    } else {
      const spin = s.phase * 1.6;
      rig.a.current?.children.forEach((w) => { w.rotation.x = spin; });
      rig.b.current?.children.forEach((w) => { w.rotation.x = spin; });
      if (rig.c.current) rig.c.current.rotation.y = Math.sin(t * 1.3 + id) * 0.5;
      if (body) body.position.y = Math.abs(Math.sin(s.phase * 2)) * 0.012;
      m.halo.opacity = 0;
    }
    if (shadow.current) {
      shadowMaterial.opacity = s.opacity * 0.28;
      shadow.current.scale.set(1, 0.18, 1);
    }
  });

  const Model = spec.kind === "walker" ? WalkerModel : spec.kind === "drone" ? DroneModel : RoverModel;
  return (
    <group ref={root} visible={false}>
      <group rotation={[0.08, 0.95, 0]}>
        <Model m={m} rig={rig} />
      </group>
      <mesh ref={shadow} position={[0, 0.01, -0.2]} material={shadowMaterial}>
        <circleGeometry args={[0.34, 24]} />
      </mesh>
    </group>
  );
}

function Agents() {
  const obstacles = useObstacles();
  const lanes = useMemo(() => new LaneRegistry(), []);
  const { size } = useThree();
  const count = size.width < 700 ? 3 : AGENT_SPECS.length;
  return (
    <>
      {AGENT_SPECS.slice(0, count).map((spec, index) => (
        <Agent key={index} id={index} spec={spec} obstacles={obstacles} lanes={lanes} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------

export default function SceneBackground() {
  const reduced = useMemo(prefersReducedMotion, []);
  return (
    <Canvas
      className="scene-background"
      dpr={[1, 1.5]}
      camera={{ fov: 50, position: [0, 0, 10], near: 0.1, far: 80 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
      aria-hidden
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 5, 7]} intensity={1.6} />
      <pointLight position={[-7, 3, 5]} intensity={40} color="#8d7cff" />
      <pointLight position={[7, -3, 5]} intensity={30} color="#52d9ca" />
      <RippleField reduced={reduced} />
      {!reduced && <Agents />}
    </Canvas>
  );
}
