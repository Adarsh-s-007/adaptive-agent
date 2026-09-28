import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, ThreeEvent, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { AnimatePresence, motion, useSpring } from "framer-motion";
import * as THREE from "three";

import type { Memory } from "../api";
import { MEMORY_TYPES, memoryColor, prefersReducedMotion } from "./support";

const MAX_NODES = 80;
const TRAIL_STEPS = 24;
const TRAIL_ARC = 1.1;
const PACKETS_PER_NODE = 2;
const DUST_PER_RING = 90;
const SPAWN_SECONDS = 1.6;

// Memories already shown in the constellation (survives tab switches). Anything new "materializes":
// it launches out of the core and settles onto its ring.
const seenMemoryIds = new Set<string>();
let constellationPrimed = false;

function easeOutBack(t: number): number {
  const c = 1.4;
  return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2;
}

type Hover = { memory: Memory; x: number; y: number };

type Props = {
  memories: Memory[];
  highlighted: Set<string>;
  onSelect: (memory: Memory) => void;
  focusType?: string | null;
};

type Interaction = {
  hovering: boolean;
  dragging: boolean;
  lastX: number;
  lastY: number;
  moved: number;
  velocity: number;
  yaw: number;
  pitch: number;
};

type Ref<T> = React.MutableRefObject<T>;

let glowTexture: THREE.Texture | null = null;

/** Soft round sprite so point particles render as glowing orbs instead of squares. */
function getGlowTexture(): THREE.Texture {
  if (glowTexture) return glowTexture;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d");
  if (context) {
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.35, "rgba(255,255,255,0.55)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
  }
  glowTexture = new THREE.CanvasTexture(canvas);
  return glowTexture;
}

function ringIndex(type: string): number {
  const index = MEMORY_TYPES.indexOf(type);
  return index === -1 ? MEMORY_TYPES.length : index;
}

function ringRadius(index: number): number {
  return 1.45 + index * 0.4;
}

function ringSpeed(index: number): number {
  return (0.22 - index * 0.025) * (index % 2 ? -1 : 1);
}

function ringTilt(index: number): THREE.Euler {
  return new THREE.Euler(Math.PI / 2 - 0.42 + index * 0.07, 0, (index % 2 ? 1 : -1) * (0.12 + index * 0.05));
}

function ringColor(index: number): string {
  return memoryColor(MEMORY_TYPES[index] || "");
}

/** Shared orbit clock: eases almost to a stop while the pointer is over the view. */
function OrbitClock({ time, interaction, reduced }: {
  time: Ref<number>;
  interaction: Ref<Interaction>;
  reduced: boolean;
}) {
  const rate = useRef(1);
  useFrame((_, delta) => {
    const target = reduced ? 0 : interaction.current.hovering ? 0.08 : 1;
    rate.current = THREE.MathUtils.damp(rate.current, target, 3, delta);
    time.current += Math.min(delta, 0.05) * rate.current;
  });
  return null;
}

function Core({ active }: { active: boolean }) {
  const shell = useRef<THREE.Mesh>(null);
  const inner = useRef<THREE.Mesh>(null);
  const gyroA = useRef<THREE.Mesh>(null);
  const gyroB = useRef<THREE.Mesh>(null);
  const pulses = useRef<(THREE.Mesh | null)[]>([]);
  const energy = useRef(0);

  useFrame(({ clock }, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    const t = clock.elapsedTime;
    energy.current = THREE.MathUtils.damp(energy.current, active ? 1 : 0, 2, delta);
    if (shell.current) {
      shell.current.rotation.y += delta * 0.22;
      shell.current.rotation.x += delta * 0.08;
    }
    if (inner.current) {
      inner.current.scale.setScalar(1 + Math.sin(t * 1.6) * (0.03 + energy.current * 0.05));
      (inner.current.material as THREE.MeshStandardMaterial).emissiveIntensity = 1 + energy.current * 0.8;
    }
    if (gyroA.current) gyroA.current.rotation.x += delta * 0.6;
    if (gyroB.current) gyroB.current.rotation.y += delta * 0.45;
    pulses.current.forEach((pulse, index) => {
      if (!pulse) return;
      const cycle = (t * 0.32 + index / pulses.current.length) % 1;
      pulse.scale.setScalar(0.75 + cycle * 1.5);
      const eased = Math.sin(cycle * Math.PI) * (1 - cycle);
      (pulse.material as THREE.MeshBasicMaterial).opacity = eased * (0.03 + energy.current * 0.07);
    });
  });

  return (
    <group>
      <mesh ref={shell}>
        <icosahedronGeometry args={[0.62, 1]} />
        <meshBasicMaterial color="#a597ff" wireframe transparent opacity={0.5} />
      </mesh>
      <mesh ref={inner}>
        <icosahedronGeometry args={[0.36, 3]} />
        <meshStandardMaterial color="#6f5cf0" emissive="#7b68ff" emissiveIntensity={1.1} roughness={0.3} />
      </mesh>
      <mesh ref={gyroA} rotation={[0, 0.6, 0]}>
        <torusGeometry args={[0.82, 0.008, 6, 90]} />
        <meshBasicMaterial color="#c3bbff" transparent opacity={0.45} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <mesh ref={gyroB} rotation={[1.1, 0, 0.4]}>
        <torusGeometry args={[0.9, 0.006, 6, 90]} />
        <meshBasicMaterial color="#7fe6dc" transparent opacity={0.35} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      {[0, 1, 2].map((index) => (
        <mesh key={index} ref={(el) => { pulses.current[index] = el; }}>
          <sphereGeometry args={[0.6, 32, 32]} />
          <meshBasicMaterial color="#8f80ff" transparent opacity={0} side={THREE.BackSide}
            blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      ))}
      <mesh>
        <sphereGeometry args={[1, 32, 32]} />
        <meshBasicMaterial color="#7b68ff" transparent opacity={0.07} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
    </group>
  );
}

/** A tilted ring: its path plus a band of dust drifting along it at the ring's orbital speed. */
function Ring({ index, time, focusType }: { index: number; time: Ref<number>; focusType: string | null }) {
  const dust = useRef<THREE.Points>(null);
  const line = useRef<THREE.LineBasicMaterial>(null);
  const dustMaterial = useRef<THREE.PointsMaterial>(null);
  const radius = ringRadius(index);
  const type = MEMORY_TYPES[index] || "";

  const path = useMemo(() => new THREE.BufferGeometry().setFromPoints(
    Array.from({ length: 129 }, (_, step) => {
      const angle = (step / 128) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    }),
  ), [radius]);
  const dustGeometry = useMemo(() => {
    const positions = new Float32Array(DUST_PER_RING * 3);
    for (let step = 0; step < DUST_PER_RING; step++) {
      const angle = Math.random() * Math.PI * 2;
      const spread = radius + (Math.random() - 0.5) * 0.16;
      positions.set([Math.cos(angle) * spread, Math.sin(angle) * spread, (Math.random() - 0.5) * 0.08], step * 3);
    }
    return new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(positions, 3));
  }, [radius]);
  useEffect(() => () => { path.dispose(); dustGeometry.dispose(); }, [path, dustGeometry]);

  useFrame((_, delta) => {
    if (dust.current) dust.current.rotation.z = time.current * ringSpeed(index) * 0.6;
    const emphasis = !focusType ? 1 : focusType === type ? 2.2 : 0.3;
    if (line.current) line.current.opacity = THREE.MathUtils.damp(line.current.opacity, 0.2 * emphasis, 6, delta);
    if (dustMaterial.current) {
      dustMaterial.current.opacity = THREE.MathUtils.damp(dustMaterial.current.opacity, 0.35 * emphasis, 6, delta);
    }
  });

  const color = ringColor(index);
  return (
    <group rotation={ringTilt(index)}>
      <lineLoop geometry={path}>
        <lineBasicMaterial ref={line} color={color} transparent opacity={0.2} depthWrite={false} />
      </lineLoop>
      <points ref={dust} geometry={dustGeometry}>
        <pointsMaterial ref={dustMaterial} map={getGlowTexture()} color={color} size={0.06} transparent opacity={0.35}
          depthWrite={false} blending={THREE.AdditiveBlending} sizeAttenuation />
      </points>
    </group>
  );
}

type NodeSpec = { memory: Memory; ring: number; angle: number; speed: number; tilt: THREE.Euler };

function Nodes({
  nodes, highlighted, hoveredId, setHover, onSelect, time, interaction, focusType,
}: {
  nodes: NodeSpec[];
  highlighted: Set<string>;
  hoveredId: string | null;
  setHover: (hover: Hover | null) => void;
  onSelect: (memory: Memory) => void;
  time: Ref<number>;
  interaction: Ref<Interaction>;
  focusType: string | null;
}) {
  const meshes = useRef<(THREE.Mesh | null)[]>([]);
  const halos = useRef<(THREE.Mesh | null)[]>([]);
  const scratch = useMemo(() => new THREE.Vector3(), []);
  const prev = useMemo(() => new THREE.Vector3(), []);
  const next = useMemo(() => new THREE.Vector3(), []);
  const spawnAt = useRef(new Map<string, number>());

  const links = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(nodes.length * 6), 3));
    const colors = new Float32Array(nodes.length * 6);
    const color = new THREE.Color();
    nodes.forEach((node, index) => {
      color.set(memoryColor(node.memory.type));
      colors.set([0.35, 0.3, 0.7, color.r, color.g, color.b], index * 6);
    });
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geometry;
  }, [nodes]);

  // Comet trails: segments along the ring behind each node, fading to black (additive = transparent).
  const trails = useMemo(() => {
    const segments = TRAIL_STEPS - 1;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(nodes.length * segments * 6), 3));
    const colors = new Float32Array(nodes.length * segments * 6);
    const color = new THREE.Color();
    nodes.forEach((node, index) => {
      color.set(memoryColor(node.memory.type));
      for (let step = 0; step < segments; step++) {
        const head = Math.pow(1 - step / segments, 1.6) * 0.9;
        const tail = Math.pow(1 - (step + 1) / segments, 1.6) * 0.9;
        colors.set([
          color.r * head, color.g * head, color.b * head,
          color.r * tail, color.g * tail, color.b * tail,
        ], (index * segments + step) * 6);
      }
    });
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geometry;
  }, [nodes]);

  // Data packets flowing from recalled memories into the bank.
  const packets = useMemo(() => new THREE.BufferGeometry().setAttribute(
    "position", new THREE.BufferAttribute(new Float32Array(nodes.length * PACKETS_PER_NODE * 3), 3),
  ), [nodes]);

  useEffect(() => () => { links.dispose(); trails.dispose(); packets.dispose(); }, [links, trails, packets]);

  useFrame(({ clock }, rawDelta) => {
    const delta = Math.min(rawDelta, 0.05);
    const t = clock.elapsedTime;
    const linkPositions = links.getAttribute("position") as THREE.BufferAttribute;
    const trailPositions = trails.getAttribute("position") as THREE.BufferAttribute;
    const packetPositions = packets.getAttribute("position") as THREE.BufferAttribute;
    const segments = TRAIL_STEPS - 1;
    let reach = 1;
    const point = (node: NodeSpec, angle: number, target: THREE.Vector3) => {
      const radius = ringRadius(node.ring) * reach;
      return target.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0).applyEuler(node.tilt);
    };

    nodes.forEach((node) => {
      const id = node.memory.id;
      if (seenMemoryIds.has(id)) return;
      seenMemoryIds.add(id);
      if (constellationPrimed) spawnAt.current.set(id, t);
    });
    constellationPrimed = true;

    nodes.forEach((node, index) => {
      const mesh = meshes.current[index];
      if (!mesh) return;
      const spawnStart = spawnAt.current.get(node.memory.id);
      const spawn = spawnStart === undefined ? 1 : Math.min(1, (t - spawnStart) / SPAWN_SECONDS);
      if (spawn >= 1) spawnAt.current.delete(node.memory.id);
      reach = easeOutBack(spawn);
      const angle = node.angle + time.current * node.speed - (1 - spawn) * 2.2 * Math.sign(node.speed || 1);
      point(node, angle, scratch);
      mesh.position.copy(scratch);

      const isHighlighted = highlighted.has(node.memory.id);
      const isHovered = hoveredId === node.memory.id;
      const dimmed = !!focusType && focusType !== node.memory.type;
      const pulse = isHighlighted ? 1.25 + Math.sin(t * 3 + index) * 0.15 : 1;
      const target = (isHovered ? 1.8 : dimmed ? 0.7 : 1) * pulse;
      mesh.scale.setScalar(THREE.MathUtils.damp(mesh.scale.x, target, 8, delta) * Math.min(1, 0.2 + spawn * 1.2));
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.emissiveIntensity = THREE.MathUtils.damp(
        material.emissiveIntensity, dimmed ? 0.15 : isHovered ? 1.8 : isHighlighted ? 1.4 : 0.85, 6, delta,
      );
      material.opacity = THREE.MathUtils.damp(material.opacity, dimmed ? 0.35 : 1, 6, delta);

      const halo = halos.current[index];
      if (halo) {
        halo.position.copy(scratch);
        halo.scale.setScalar(mesh.scale.x * (isHighlighted ? 2.1 + Math.sin(t * 3 + index) * 0.25 : 1.8));
        const haloMaterial = halo.material as THREE.MeshBasicMaterial;
        const haloTarget = dimmed ? 0.02 : isHovered ? 0.3 : isHighlighted ? 0.2 : 0.08;
        haloMaterial.opacity = THREE.MathUtils.damp(haloMaterial.opacity, haloTarget, 6, delta) +
          (spawn < 1 ? (1 - spawn) * 0.5 : 0);
      }

      linkPositions.setXYZ(index * 2, 0, 0, 0);
      linkPositions.setXYZ(index * 2 + 1, scratch.x, scratch.y, scratch.z);

      const direction = Math.sign(node.speed) || 1;
      prev.copy(scratch);
      for (let step = 0; step < segments; step++) {
        point(node, angle - direction * ((step + 1) / segments) * TRAIL_ARC, next);
        const offset = (index * segments + step) * 2;
        trailPositions.setXYZ(offset, prev.x, prev.y, prev.z);
        trailPositions.setXYZ(offset + 1, next.x, next.y, next.z);
        prev.copy(next);
      }

      for (let packet = 0; packet < PACKETS_PER_NODE; packet++) {
        const slot = index * PACKETS_PER_NODE + packet;
        if (!isHighlighted) {
          packetPositions.setXYZ(slot, 0, 0, 0);
          continue;
        }
        const progress = (t * 0.55 + packet / PACKETS_PER_NODE + index * 0.13) % 1;
        const eased = progress * progress * (3 - 2 * progress);
        packetPositions.setXYZ(slot, scratch.x * (1 - eased), scratch.y * (1 - eased), scratch.z * (1 - eased));
      }
    });
    linkPositions.needsUpdate = true;
    trailPositions.needsUpdate = true;
    packetPositions.needsUpdate = true;
  });

  const hoverFrom = (event: ThreeEvent<PointerEvent>, memory: Memory) => {
    event.stopPropagation();
    if (interaction.current.dragging) return;
    setHover({ memory, x: event.nativeEvent.offsetX, y: event.nativeEvent.offsetY });
  };

  return (
    <>
      <lineSegments geometry={links}>
        <lineBasicMaterial vertexColors transparent opacity={0.22} depthWrite={false} blending={THREE.AdditiveBlending} />
      </lineSegments>
      <lineSegments geometry={trails}>
        <lineBasicMaterial vertexColors transparent opacity={0.9} depthWrite={false} blending={THREE.AdditiveBlending} />
      </lineSegments>
      <points geometry={packets}>
        <pointsMaterial map={getGlowTexture()} color="#eef0ff" size={0.2} transparent opacity={0.95} depthWrite={false}
          blending={THREE.AdditiveBlending} sizeAttenuation />
      </points>
      {nodes.map((node, index) => {
        const color = memoryColor(node.memory.type);
        return (
          <group key={node.memory.id}>
            <mesh ref={(el) => { halos.current[index] = el; }}>
              <sphereGeometry args={[0.13, 20, 20]} />
              <meshBasicMaterial color={color} transparent opacity={0.1} depthWrite={false} blending={THREE.AdditiveBlending} />
            </mesh>
            <mesh
              ref={(el) => { meshes.current[index] = el; }}
              onPointerOver={(event) => { hoverFrom(event, node.memory); document.body.style.cursor = "pointer"; }}
              onPointerMove={(event) => hoverFrom(event, node.memory)}
              onPointerOut={() => { setHover(null); document.body.style.cursor = ""; }}
              onClick={(event) => {
                event.stopPropagation();
                if (interaction.current.moved < 6) onSelect(node.memory);
              }}
            >
              <sphereGeometry args={[0.13, 24, 24]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.85}
                roughness={0.35} metalness={0.1} transparent />
            </mesh>
          </group>
        );
      })}
    </>
  );
}

function Stars() {
  const points = useRef<THREE.Points>(null);
  const geometry = useMemo(() => {
    const positions = new Float32Array(520 * 3);
    for (let index = 0; index < 520; index++) {
      const radius = 5 + Math.random() * 7;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions.set([
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
      ], index * 3);
    }
    return new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(positions, 3));
  }, []);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useFrame((_, delta) => { if (points.current) points.current.rotation.y += Math.min(delta, 0.05) * 0.012; });
  return (
    <points ref={points} geometry={geometry}>
      <pointsMaterial map={getGlowTexture()} size={0.07} color="#a4acdf" transparent opacity={0.6}
        sizeAttenuation depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

function Scene({ memories, highlighted, onSelect, hoveredId, setHover, interaction, focusType }: Props & {
  interaction: Ref<Interaction>;
  hoveredId: string | null;
  setHover: (hover: Hover | null) => void;
}) {
  const system = useRef<THREE.Group>(null);
  const time = useRef(0);
  const reduced = useMemo(prefersReducedMotion, []);

  const nodes = useMemo<NodeSpec[]>(() => {
    const byRing = new Map<number, Memory[]>();
    memories.slice(0, MAX_NODES).forEach((memory) => {
      const ring = ringIndex(memory.type);
      byRing.set(ring, [...(byRing.get(ring) || []), memory]);
    });
    return [...byRing.entries()].flatMap(([ring, items]) => items.map((memory, index) => ({
      memory,
      ring,
      angle: (index / items.length) * Math.PI * 2 + ring * 0.9,
      speed: ringSpeed(ring),
      tilt: ringTilt(ring),
    })));
  }, [memories]);
  const rings = useMemo(() => [...new Set(nodes.map((node) => node.ring))], [nodes]);

  useFrame(({ pointer }, rawDelta) => {
    const group = system.current;
    if (!group) return;
    const delta = Math.min(rawDelta, 0.05);
    const state = interaction.current;
    if (!state.dragging) {
      // Inertia after a drag, plus a slow idle spin when nobody is looking closely.
      state.yaw += state.velocity * delta * 60;
      state.velocity = THREE.MathUtils.damp(state.velocity, 0, 2.5, delta);
      if (!state.hovering && !reduced) state.yaw += delta * 0.05;
    }
    const tiltFromPointer = state.hovering || state.dragging ? 0 : -pointer.y * 0.12;
    group.rotation.y = THREE.MathUtils.damp(group.rotation.y, state.yaw, 5, delta);
    group.rotation.x = THREE.MathUtils.damp(group.rotation.x, state.pitch + tiltFromPointer, 4, delta);
  });

  return (
    <>
      <OrbitClock time={time} interaction={interaction} reduced={reduced} />
      <ambientLight intensity={0.45} />
      <pointLight position={[0, 0, 0]} intensity={10} color="#8d7cff" />
      <directionalLight position={[4, 5, 6]} intensity={1.2} />
      <Stars />
      <group ref={system}>
        <Core active={highlighted.size > 0} />
        {rings.map((ring) => <Ring key={ring} index={ring} time={time} focusType={focusType || null} />)}
        <Nodes nodes={nodes} highlighted={highlighted} hoveredId={hoveredId} setHover={setHover}
          onSelect={onSelect} time={time} interaction={interaction} focusType={focusType || null} />
      </group>
    </>
  );
}

export default function MemoryOrbit(props: Props) {
  const [hover, setHover] = useState<Hover | null>(null);
  const [dragging, setDragging] = useState(false);
  const interaction = useRef<Interaction>({
    hovering: false, dragging: false, lastX: 0, lastY: 0, moved: 0, velocity: 0, yaw: 0, pitch: 0,
  });
  const tipX = useSpring(0, { stiffness: 420, damping: 34 });
  const tipY = useSpring(0, { stiffness: 420, damping: 34 });

  const tipVisible = useRef(false);
  useEffect(() => {
    if (!hover) {
      tipVisible.current = false;
      return;
    }
    // Appear in place, then glide while following the node.
    if (tipVisible.current) {
      tipX.set(hover.x);
      tipY.set(hover.y);
    } else {
      tipX.jump(hover.x);
      tipY.jump(hover.y);
      tipVisible.current = true;
    }
  }, [hover, tipX, tipY]);

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const state = interaction.current;
      if (!state.dragging) return;
      const dx = event.clientX - state.lastX;
      const dy = event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      state.moved += Math.abs(dx) + Math.abs(dy);
      state.yaw += dx * 0.007;
      state.pitch = THREE.MathUtils.clamp(state.pitch + dy * 0.004, -0.45, 0.6);
      state.velocity = dx * 0.007 * 0.25;
    };
    const onUp = () => {
      if (!interaction.current.dragging) return;
      interaction.current.dragging = false;
      setDragging(false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      document.body.style.cursor = "";
    };
  }, []);

  return (
    <div
      className={"orbit-canvas" + (dragging ? " dragging" : "")}
      onPointerEnter={() => { interaction.current.hovering = true; }}
      onPointerLeave={() => { interaction.current.hovering = false; setHover(null); }}
      onPointerDown={(event) => {
        const state = interaction.current;
        state.dragging = true;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        state.moved = 0;
        state.velocity = 0;
        setDragging(true);
        setHover(null);
      }}
    >
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 40, position: [0, 3.1, 6.3] }}
        gl={{ antialias: false, alpha: false }}
        onPointerMissed={() => setHover(null)}
      >
        {/* Opaque so bloom has something to glow over; CSS masks the edges into the panel. */}
        <color attach="background" args={["#0f1126"]} />
        <Scene {...props} hoveredId={hover?.memory.id || null} setHover={setHover} interaction={interaction} />
        <EffectComposer multisampling={4} enableNormalPass={false}>
          <Bloom mipmapBlur intensity={1.05} luminanceThreshold={0.28} luminanceSmoothing={0.3} radius={0.7} />
        </EffectComposer>
      </Canvas>
      <AnimatePresence>
        {hover && (
          <motion.div
            key="orbit-tooltip"
            className="orbit-tooltip"
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            style={{ x: tipX, y: tipY }}
          >
            <span style={{ color: memoryColor(hover.memory.type) }}>
              {hover.memory.type.replace(/_/g, " ")}
              {props.highlighted.has(hover.memory.id) ? " · recalled" : ""}
            </span>
            <p>{hover.memory.text}</p>
            <small>Click to inspect · drag to rotate</small>
          </motion.div>
        )}
      </AnimatePresence>
      <p className="orbit-hint">Drag to rotate</p>
      {!props.memories.length && (
        <p className="orbit-empty">The bank is empty. Retained memories will start orbiting here.</p>
      )}
    </div>
  );
}
