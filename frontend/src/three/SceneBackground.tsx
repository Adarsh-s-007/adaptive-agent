import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";

import { HealthState, onScene } from "./bus";
import { prefersReducedMotion } from "./support";

/*
 * Full-viewport WebGL layer behind the dashboard (opaque, so bloom can glow over it):
 *  - backdrop gradient (replaces the CSS body gradient) that tints toward the data in focus
 *  - a dense, misty field of tiny orbs: cursor wake, click ripples, colored data ripples/waves
 *  - the 3D brand crystal and the health beacon, pinned over their header elements
 */

const RIPPLE_SLOTS = 16;
const RIPPLE_LIFETIME = 3.6;
const FIELD_COLS = 300;
const FIELD_ROWS = 190;
const FIELD_W = 64;
const FIELD_H = 40;
const MIST_COUNT = 160;

const HOVER_MIN_DISTANCE = 64;
const HOVER_MIN_INTERVAL = 0.09;
const HOVER_STRENGTH = 0.45;
const CLICK_STRENGTH = 1;
const DEFAULT_RIPPLE = "#c9c2ff";

const HEALTH_COLORS: Record<HealthState, string> = {
  connected: "#4be0af",
  demo: "#eab96a",
  offline: "#ff6b7d",
  unknown: "#8790ae",
};

// Shared scene state written by bus events, read inside frame loops.
type SceneState = {
  tint: THREE.Color;
  tintTarget: number;
  flash: THREE.Color;
  flashAmount: number;
  busy: boolean;
  health: HealthState;
  logoKick: number;
};

// ---------------------------------------------------------------------------
// Backdrop
// ---------------------------------------------------------------------------

const backdropVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const backdropFragment = /* glsl */ `
  uniform vec2 uResolution;
  uniform vec3 uBase;
  uniform vec3 uViolet;
  uniform vec3 uTeal;
  uniform vec3 uTint;
  uniform float uTintAmount;
  uniform vec3 uFlash;
  uniform float uFlashAmount;
  varying vec2 vUv;

  // Mirrors CSS "radial-gradient(circle at X Y, color 0, transparent STOP)" (farthest-corner size).
  float radial(vec2 center, float stop) {
    vec2 px = vec2(vUv.x, 1.0 - vUv.y) * uResolution;
    vec2 c = center * uResolution;
    float far = max(max(length(c), length(c - vec2(uResolution.x, 0.0))),
                    max(length(c - vec2(0.0, uResolution.y)), length(c - uResolution)));
    return clamp(1.0 - length(px - c) / (far * stop), 0.0, 1.0);
  }

  float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

  void main() {
    vec3 color = uBase;
    color = mix(color, uTeal, radial(vec2(0.1, 1.1), 0.38));
    color = mix(color, uViolet, radial(vec2(0.68, -0.1), 0.34));
    color = mix(color, uTint * 0.3, radial(vec2(0.5, 1.0), 0.55) * uTintAmount * 0.3);
    color += uFlash * radial(vec2(0.5, 0.45), 0.9) * uFlashAmount * 0.12;
    color += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    gl_FragColor = vec4(color, 1.0);
    #include <colorspace_fragment>
  }
`;

function Backdrop({ scene }: { scene: SceneState }) {
  const { size } = useThree();
  const uniforms = useMemo(() => ({
    uResolution: { value: new THREE.Vector2(1, 1) },
    uBase: { value: new THREE.Color("#080b16") },
    uViolet: { value: new THREE.Color("#252059") },
    uTeal: { value: new THREE.Color("#0f2d33") },
    uTint: { value: new THREE.Color("#000000") },
    uTintAmount: { value: 0 },
    uFlash: { value: new THREE.Color("#000000") },
    uFlashAmount: { value: 0 },
  }), []);

  useFrame((_, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    uniforms.uResolution.value.set(size.width, size.height);
    uniforms.uTint.value.lerp(scene.tint, 1 - Math.exp(-4 * delta));
    uniforms.uTintAmount.value = THREE.MathUtils.damp(uniforms.uTintAmount.value, scene.tintTarget, 2.5, delta);
    uniforms.uFlash.value.copy(scene.flash);
    uniforms.uFlashAmount.value = scene.flashAmount;
  });

  return (
    <mesh frustumCulled={false} renderOrder={-10}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial vertexShader={backdropVertex} fragmentShader={backdropFragment}
        uniforms={uniforms} depthTest={false} depthWrite={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Orb field
// ---------------------------------------------------------------------------

const fieldVertex = /* glsl */ `
  attribute float aRand;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform vec4 uRipples[${RIPPLE_SLOTS}];
  uniform vec3 uRippleColors[${RIPPLE_SLOTS}];
  uniform vec3 uPointer;
  uniform vec3 uHighlight;
  varying float vEnergy;
  varying float vFade;
  varying float vTwinkle;
  varying float vRand;
  varying vec3 vEnergyColor;

  void main() {
    vec3 p = position;
    float swell = sin(p.x * 0.35 + uTime * 0.45) * 0.06 + cos(p.y * 0.42 + uTime * 0.33) * 0.06;
    float energy = 0.0;
    float lift = 0.0;
    vec3 tinted = vec3(0.0);
    for (int i = 0; i < ${RIPPLE_SLOTS}; i++) {
      vec4 r = uRipples[i];
      float age = uTime - r.z;
      if (age > 0.0 && age < ${RIPPLE_LIFETIME.toFixed(1)}) {
        float d = distance(p.xy, r.xy);
        float front = age * 2.6;
        float band = exp(-pow((d - front) * 0.95, 2.0));
        float life = 1.0 - age / ${RIPPLE_LIFETIME.toFixed(1)};
        life *= life;
        float e = band * r.w * life;
        lift += sin((d - front) * 3.2) * e * 0.5;
        energy += e;
        tinted += uRippleColors[i] * e;
      }
    }
    float glow = exp(-pow(distance(p.xy, uPointer.xy), 2.0) / 11.0) * uPointer.z;
    lift += glow * 0.22;
    energy += glow * 0.85;
    tinted += uHighlight * glow * 0.85;

    p.z += swell + lift;
    vEnergy = energy;
    vEnergyColor = energy > 0.001 ? tinted / energy : uHighlight;
    vRand = aRand;
    vTwinkle = 0.65 + 0.35 * sin(uTime * (0.6 + aRand * 1.6) + aRand * 40.0);

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    float depth = -mv.z;
    float edge = min(1.0 - abs(position.x) / ${(FIELD_W / 2).toFixed(1)}, 1.0 - abs(position.y) / ${(FIELD_H / 2).toFixed(1)});
    vFade = smoothstep(0.0, 0.22, edge) * smoothstep(40.0, 12.0, depth);
    gl_PointSize = (1.6 + aRand * 1.9) * uPixelRatio * (12.0 / depth) * (1.0 + clamp(energy, 0.0, 1.4) * 1.1);
    gl_Position = projectionMatrix * mv;
  }
`;

const fieldFragment = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform vec3 uTint;
  uniform float uTintAmount;
  varying float vEnergy;
  varying float vFade;
  varying float vTwinkle;
  varying float vRand;
  varying vec3 vEnergyColor;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    float soft = exp(-d * d * 14.0);
    vec3 color = mix(uColorA, uColorB, vRand);
    color = mix(color, uTint, uTintAmount * 0.45);
    color = mix(color, vEnergyColor, clamp(vEnergy * 0.9, 0.0, 0.9));
    float alpha = soft * vFade * (0.26 * vTwinkle * (1.0 + uTintAmount * 0.15) + clamp(vEnergy, 0.0, 1.2) * 0.8);
    gl_FragColor = vec4(color, alpha);
    #include <colorspace_fragment>
  }
`;

const mistVertex = /* glsl */ `
  attribute float aRand;
  uniform float uTime;
  uniform float uPixelRatio;
  varying float vRand;

  void main() {
    vec3 p = position;
    p.x += sin(uTime * 0.05 + aRand * 30.0) * 1.6;
    p.y += cos(uTime * 0.04 + aRand * 20.0) * 0.9;
    vRand = aRand;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = (90.0 + aRand * 160.0) * uPixelRatio * (10.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const mistFragment = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform vec3 uTint;
  uniform float uTintAmount;
  uniform float uTime;
  varying float vRand;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    float soft = exp(-d * d * 9.0) * smoothstep(0.5, 0.35, d);
    float breathe = 0.7 + 0.3 * sin(uTime * 0.3 + vRand * 12.0);
    vec3 color = mix(mix(uColorA, uColorB, vRand), uTint, uTintAmount * 0.4);
    gl_FragColor = vec4(color, soft * 0.03 * breathe);
    #include <colorspace_fragment>
  }
`;

function OrbField({ reduced, scene }: { reduced: boolean; scene: SceneState }) {
  const points = useRef<THREE.Points>(null);
  const slot = useRef(0);
  const time = useRef(0);
  const pointerTarget = useRef(new THREE.Vector3(0, 0, 0));
  const lastActive = useRef(-10);
  const { camera } = useThree();

  const geometry = useMemo(() => {
    const count = FIELD_COLS * FIELD_ROWS;
    const positions = new Float32Array(count * 3);
    const rand = new Float32Array(count);
    const stepX = FIELD_W / FIELD_COLS;
    const stepY = FIELD_H / FIELD_ROWS;
    let index = 0;
    for (let row = 0; row < FIELD_ROWS; row++) {
      for (let col = 0; col < FIELD_COLS; col++) {
        // Jitter breaks the grid up so it reads as mist rather than a lattice.
        positions[index * 3] = (col / (FIELD_COLS - 1) - 0.5) * FIELD_W + (Math.random() - 0.5) * stepX * 1.6;
        positions[index * 3 + 1] = (row / (FIELD_ROWS - 1) - 0.5) * FIELD_H + (Math.random() - 0.5) * stepY * 1.6;
        positions[index * 3 + 2] = (Math.random() - 0.5) * 0.35;
        rand[index] = Math.random();
        index++;
      }
    }
    const next = new THREE.BufferGeometry();
    next.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    next.setAttribute("aRand", new THREE.BufferAttribute(rand, 1));
    return next;
  }, []);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 1.5) },
    uRipples: { value: Array.from({ length: RIPPLE_SLOTS }, () => new THREE.Vector4(0, 0, -100, 0)) },
    uRippleColors: { value: Array.from({ length: RIPPLE_SLOTS }, () => new THREE.Color(DEFAULT_RIPPLE)) },
    uPointer: { value: new THREE.Vector3(0, 0, 0) },
    uHighlight: { value: new THREE.Color(DEFAULT_RIPPLE) },
    uColorA: { value: new THREE.Color("#6f63e8") },
    uColorB: { value: new THREE.Color("#3fb8c4") },
    uTint: { value: new THREE.Color("#000000") },
    uTintAmount: { value: 0 },
  }), []);

  useEffect(() => {
    const raycaster = new THREE.Raycaster();
    const plane = new THREE.Plane();
    const normal = new THREE.Vector3();
    const hit = new THREE.Vector3();
    const ndc = new THREE.Vector2();
    let lastX = -1000;
    let lastY = -1000;
    let lastHoverAt = -10;
    const timers: number[] = [];

    const toLocal = (clientX: number, clientY: number): THREE.Vector3 | null => {
      const field = points.current;
      if (!field) return null;
      ndc.set((clientX / window.innerWidth) * 2 - 1, -(clientY / window.innerHeight) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      normal.set(0, 0, 1).transformDirection(field.matrixWorld);
      plane.setFromNormalAndCoplanarPoint(normal, field.getWorldPosition(new THREE.Vector3()));
      if (!raycaster.ray.intersectPlane(plane, hit)) return null;
      return field.worldToLocal(hit.clone());
    };

    const ripple = (clientX: number, clientY: number, strength: number, color = DEFAULT_RIPPLE) => {
      const local = toLocal(clientX, clientY);
      if (!local) return;
      uniforms.uRipples.value[slot.current].set(local.x, local.y, time.current, strength);
      uniforms.uRippleColors.value[slot.current].set(color);
      slot.current = (slot.current + 1) % RIPPLE_SLOTS;
    };

    const onPointerMove = (event: PointerEvent) => {
      const local = toLocal(event.clientX, event.clientY);
      if (!local) return;
      pointerTarget.current.set(local.x, local.y, 1);
      lastActive.current = time.current;
      if (reduced) return;
      const moved = Math.hypot(event.clientX - lastX, event.clientY - lastY);
      if (moved > HOVER_MIN_DISTANCE && time.current - lastHoverAt > HOVER_MIN_INTERVAL) {
        ripple(event.clientX, event.clientY, HOVER_STRENGTH);
        lastX = event.clientX;
        lastY = event.clientY;
        lastHoverAt = time.current;
      }
    };
    const onPointerDown = (event: PointerEvent) => ripple(event.clientX, event.clientY, reduced ? 0.4 : CLICK_STRENGTH);
    const onLeave = () => { pointerTarget.current.z = 0; };

    const unsubscribe = onScene((event) => {
      if (event.type === "ripple") ripple(event.x, event.y, event.strength ?? 1, event.color);
      if (event.type === "wave") {
        // A recall/seed wave: a strong colored ripple, two echoes, and a brief backdrop flash.
        ripple(event.x, event.y, 1.6, event.color);
        timers.push(window.setTimeout(() => ripple(event.x, event.y, 1.05, event.color), 240));
        timers.push(window.setTimeout(() => ripple(event.x, event.y, 0.65, event.color), 480));
        scene.flash.set(event.color);
        scene.flashAmount = 1;
      }
    });

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerdown", onPointerDown, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      unsubscribe();
      timers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", onPointerDown);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, [camera, reduced, scene, uniforms]);

  useFrame((_, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    time.current += delta * (reduced ? 0.2 : 1);
    uniforms.uTime.value = time.current;
    const idle = time.current - lastActive.current > 1.4;
    const pointer = uniforms.uPointer.value;
    pointer.x = THREE.MathUtils.damp(pointer.x, pointerTarget.current.x, 6, delta);
    pointer.y = THREE.MathUtils.damp(pointer.y, pointerTarget.current.y, 6, delta);
    pointer.z = THREE.MathUtils.damp(pointer.z, idle ? 0 : pointerTarget.current.z, idle ? 1.5 : 4, delta);
    // The cursor glow and resting orbs lean toward whatever data is in focus.
    uniforms.uTint.value.lerp(scene.tint, 1 - Math.exp(-4 * delta));
    uniforms.uTintAmount.value = THREE.MathUtils.damp(uniforms.uTintAmount.value, scene.tintTarget, 2.5, delta);
    uniforms.uHighlight.value.set(DEFAULT_RIPPLE).lerp(scene.tint, uniforms.uTintAmount.value);
  });

  return (
    <points ref={points} geometry={geometry} position={[0, -1, -4]} rotation={[-0.78, 0, 0]}>
      <shaderMaterial vertexShader={fieldVertex} fragmentShader={fieldFragment} uniforms={uniforms}
        transparent depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

function Mist({ reduced, scene }: { reduced: boolean; scene: SceneState }) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(MIST_COUNT * 3);
    const rand = new Float32Array(MIST_COUNT);
    for (let index = 0; index < MIST_COUNT; index++) {
      positions.set([(Math.random() - 0.5) * 30, (Math.random() - 0.5) * 16 - 1, -2 - Math.random() * 10], index * 3);
      rand[index] = Math.random();
    }
    const next = new THREE.BufferGeometry();
    next.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    next.setAttribute("aRand", new THREE.BufferAttribute(rand, 1));
    return next;
  }, []);
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 1.5) },
    uColorA: { value: new THREE.Color("#7d6cf5") },
    uColorB: { value: new THREE.Color("#3fc1c9") },
    uTint: { value: new THREE.Color("#000000") },
    uTintAmount: { value: 0 },
  }), []);
  useFrame((_, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    uniforms.uTime.value += delta * (reduced ? 0.2 : 1);
    uniforms.uTint.value.lerp(scene.tint, 1 - Math.exp(-4 * delta));
    uniforms.uTintAmount.value = THREE.MathUtils.damp(uniforms.uTintAmount.value, scene.tintTarget, 2.5, delta);
  });
  return (
    <points geometry={geometry}>
      <shaderMaterial vertexShader={mistVertex} fragmentShader={mistFragment} uniforms={uniforms}
        transparent depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Objects pinned over DOM elements (brand crystal, health beacon)
// ---------------------------------------------------------------------------

function DomAnchor({ selector, sizeFactor, children }: {
  selector: string;
  sizeFactor: number;
  children: React.ReactNode;
}) {
  const group = useRef<THREE.Group>(null);
  const element = useRef<Element | null>(null);
  useFrame(({ size, viewport }) => {
    const anchor = group.current;
    if (!anchor) return;
    if (!element.current?.isConnected) element.current = document.querySelector(selector);
    const rect = element.current?.getBoundingClientRect();
    if (!rect || !rect.width || rect.bottom < -60 || rect.top > size.height + 60) {
      anchor.visible = false;
      return;
    }
    anchor.visible = true;
    const unitsPerPx = viewport.height / size.height;
    anchor.position.set(
      ((rect.left + rect.width / 2) / size.width - 0.5) * viewport.width,
      (0.5 - (rect.top + rect.height / 2) / size.height) * viewport.height,
      0,
    );
    anchor.scale.setScalar(rect.height * unitsPerPx * sizeFactor);
  });
  return <group ref={group} visible={false}>{children}</group>;
}

function BrandCrystal({ scene, reduced }: { scene: SceneState; reduced: boolean }) {
  const body = useRef<THREE.Group>(null);
  const gem = useRef<THREE.MeshStandardMaterial>(null);
  const heart = useRef<THREE.MeshBasicMaterial>(null);
  const orbit = useRef<THREE.Group>(null);
  const spin = useRef(0.6);

  useFrame(({ clock }, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    const t = clock.elapsedTime;
    const target = reduced ? 0.15 : scene.busy ? 4.2 : 0.7;
    spin.current = THREE.MathUtils.damp(spin.current, target, 2.5, delta) + scene.logoKick;
    scene.logoKick = THREE.MathUtils.damp(scene.logoKick, 0, 4, delta);
    if (body.current) {
      body.current.rotation.y += spin.current * delta;
      body.current.rotation.z = Math.sin(t * 0.8) * 0.12;
    }
    if (orbit.current) orbit.current.rotation.z -= (0.9 + spin.current * 0.6) * delta;
    const pulse = scene.busy ? 0.5 + Math.sin(t * 7) * 0.5 : 0.5 + Math.sin(t * 1.4) * 0.15;
    if (gem.current) gem.current.emissiveIntensity = 0.45 + pulse * (scene.busy ? 1.1 : 0.4);
    if (heart.current) heart.current.color.setRGB(0.55 + pulse * 0.6, 0.95, 1.1 + pulse * 0.4);
  });

  return (
    <group>
      <group ref={body}>
        <mesh scale={[0.46, 0.62, 0.46]}>
          <octahedronGeometry args={[1, 0]} />
          <meshStandardMaterial ref={gem} color="#9c8cff" emissive="#6e5cf2" emissiveIntensity={0.6}
            metalness={0.35} roughness={0.18} flatShading />
        </mesh>
        <mesh scale={[0.2, 0.3, 0.2]}>
          <octahedronGeometry args={[1, 0]} />
          <meshBasicMaterial ref={heart} color="#8ff5e8" toneMapped={false} />
        </mesh>
      </group>
      <group ref={orbit} rotation={[1.15, 0.2, 0]}>
        <mesh>
          <torusGeometry args={[0.62, 0.018, 6, 64]} />
          <meshBasicMaterial color="#52d9ca" transparent opacity={0.75} toneMapped={false} />
        </mesh>
        <mesh position={[0.62, 0, 0]}>
          <sphereGeometry args={[0.055, 12, 12]} />
          <meshBasicMaterial color="#d8fff9" toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

function HealthBeacon({ scene, reduced }: { scene: SceneState; reduced: boolean }) {
  const core = useRef<THREE.MeshBasicMaterial>(null);
  const halo = useRef<THREE.MeshBasicMaterial>(null);
  const rings = useRef<(THREE.Mesh | null)[]>([]);
  const color = useMemo(() => new THREE.Color(HEALTH_COLORS.unknown), []);
  const target = useMemo(() => new THREE.Color(), []);

  useFrame(({ clock }, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    const t = clock.elapsedTime;
    const state = scene.health;
    target.set(HEALTH_COLORS[state]);
    color.lerp(target, 1 - Math.exp(-3 * delta));
    // Calm when connected, slow amber breathing in demo mode, fast flicker when offline.
    const rate = reduced ? 0.15 : state === "offline" ? 1.3 : state === "demo" ? 0.55 : 0.35;
    const flicker = state === "offline" ? 0.75 + Math.abs(Math.sin(t * 11)) * 0.25 : 1;
    if (core.current) core.current.color.copy(color).multiplyScalar(1.5 * flicker);
    if (halo.current) {
      halo.current.color.copy(color);
      halo.current.opacity = (0.22 + Math.sin(t * rate * Math.PI * 2) * 0.1) * flicker;
    }
    rings.current.forEach((ring, index) => {
      if (!ring) return;
      const cycle = (t * rate + index / rings.current.length) % 1;
      ring.scale.setScalar(0.35 + cycle * 1.35);
      const material = ring.material as THREE.MeshBasicMaterial;
      material.color.copy(color);
      material.opacity = (1 - cycle) * (1 - cycle) * (state === "unknown" ? 0.25 : 0.7);
    });
  });

  return (
    <group>
      <mesh>
        <sphereGeometry args={[0.2, 20, 20]} />
        <meshBasicMaterial ref={core} toneMapped={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.42, 20, 20]} />
        <meshBasicMaterial ref={halo} transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </mesh>
      {[0, 1].map((index) => (
        <mesh key={index} ref={(el) => { rings.current[index] = el; }}>
          <ringGeometry args={[0.46, 0.52, 48]} />
          <meshBasicMaterial transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------

/** Drops bloom and pixel ratio if the device can't hold a smooth frame rate. */
function PerformanceGuard({ onLow }: { onLow: () => void }) {
  const sample = useRef({ time: 0, frames: 0, windows: 0, done: false });
  useFrame((_, delta) => {
    const s = sample.current;
    if (s.done) return;
    s.time += delta;
    s.frames++;
    if (s.time < 2) return;
    s.windows++;
    // Ignore the first window: lazy chunks and shader compilation make it unrepresentative.
    if (s.windows > 1 && s.frames / s.time < 42) {
      s.done = true;
      onLow();
    }
    if (s.windows > 5) s.done = true;
    s.time = 0;
    s.frames = 0;
  });
  return null;
}

function SceneDriver({ scene }: { scene: SceneState }) {
  useEffect(() => onScene((event) => {
    if (event.type === "tint") {
      if (event.color) scene.tint.set(event.color);
      scene.tintTarget = event.color ? 1 : 0;
    }
    if (event.type === "busy") scene.busy = event.value;
    if (event.type === "health") scene.health = event.value;
    if (event.type === "logo-hover") scene.logoKick = 0.35;
  }), [scene]);
  useFrame((_, delta) => {
    scene.flashAmount = THREE.MathUtils.damp(scene.flashAmount, 0, 1.4, Math.min(delta, 0.05));
  });
  return null;
}

export default function SceneBackground() {
  const reduced = useMemo(prefersReducedMotion, []);
  const [quality, setQuality] = useState<"high" | "low">("high");
  const scene = useMemo<SceneState>(() => ({
    tint: new THREE.Color("#8d7cff"),
    tintTarget: 0,
    flash: new THREE.Color("#000000"),
    flashAmount: 0,
    busy: false,
    health: "unknown",
    logoKick: 0,
  }), []);

  useEffect(() => () => document.documentElement.classList.remove("scene-3d"), []);

  return (
    <Canvas
      className="scene-background"
      dpr={quality === "high" ? [1, 1.5] : 1}
      camera={{ fov: 50, position: [0, 0, 10], near: 0.1, far: 80 }}
      gl={{ antialias: false, alpha: false, powerPreference: "high-performance" }}
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
      onCreated={({ gl }) => {
        gl.setClearColor("#080b16");
        document.documentElement.classList.add("scene-3d");
      }}
      aria-hidden
    >
      <SceneDriver scene={scene} />
      <PerformanceGuard onLow={() => setQuality("low")} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[3, 5, 7]} intensity={2} />
      <pointLight position={[-4, 4, 6]} intensity={30} color="#52d9ca" />
      <Backdrop scene={scene} />
      <Mist reduced={reduced} scene={scene} />
      <OrbField reduced={reduced} scene={scene} />
      <DomAnchor selector='[data-anchor="brand"]' sizeFactor={0.85}>
        <BrandCrystal scene={scene} reduced={reduced} />
      </DomAnchor>
      <DomAnchor selector='[data-anchor="beacon"]' sizeFactor={2.3}>
        <HealthBeacon scene={scene} reduced={reduced} />
      </DomAnchor>
      {quality === "high" && (
        <EffectComposer multisampling={4} enableNormalPass={false}>
          <Bloom mipmapBlur intensity={0.85} luminanceThreshold={0.22} luminanceSmoothing={0.35} radius={0.72} />
        </EffectComposer>
      )}
    </Canvas>
  );
}
