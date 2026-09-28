import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, ThreeEvent, useFrame } from "@react-three/fiber";
import { AnimatePresence, motion } from "framer-motion";
import * as THREE from "three";

import type { Memory } from "../api";
import { MEMORY_TYPES, memoryColor, prefersReducedMotion } from "./support";

const MAX_NODES = 80;

type Hover = { memory: Memory; x: number; y: number };

type Props = {
  memories: Memory[];
  highlighted: Set<string>;
  onSelect: (memory: Memory) => void;
};

function ringIndex(type: string): number {
  const index = MEMORY_TYPES.indexOf(type);
  return index === -1 ? MEMORY_TYPES.length : index;
}

function ringRadius(index: number): number {
  return 1.45 + index * 0.4;
}

function ringTilt(index: number): [number, number, number] {
  return [Math.PI / 2 - 0.42 + index * 0.07, 0, (index % 2 ? 1 : -1) * (0.12 + index * 0.05)];
}

function Core({ active }: { active: boolean }) {
  const shell = useRef<THREE.Mesh>(null);
  const inner = useRef<THREE.Mesh>(null);
  useFrame(({ clock }, delta) => {
    const t = clock.elapsedTime;
    if (shell.current) {
      shell.current.rotation.y += delta * 0.25;
      shell.current.rotation.x += delta * 0.1;
    }
    if (inner.current) inner.current.scale.setScalar(1 + Math.sin(t * 2) * (active ? 0.07 : 0.03));
  });
  return (
    <group>
      <mesh ref={shell}>
        <icosahedronGeometry args={[0.62, 1]} />
        <meshBasicMaterial color="#9d8fff" wireframe transparent opacity={0.55} />
      </mesh>
      <mesh ref={inner}>
        <icosahedronGeometry args={[0.36, 2]} />
        <meshStandardMaterial color="#6f5cf0" emissive="#7b68ff" emissiveIntensity={1.1} flatShading />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.95, 24, 24]} />
        <meshBasicMaterial color="#7b68ff" transparent opacity={0.06} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
    </group>
  );
}

function Ring({ index }: { index: number }) {
  const points = useMemo(() => {
    const radius = ringRadius(index);
    return new THREE.BufferGeometry().setFromPoints(
      Array.from({ length: 97 }, (_, step) => {
        const angle = (step / 96) * Math.PI * 2;
        return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
      }),
    );
  }, [index]);
  const color = memoryColor(MEMORY_TYPES[index] || "");
  return (
    <group rotation={ringTilt(index)}>
      <lineLoop geometry={points}>
        <lineBasicMaterial color={color} transparent opacity={0.22} />
      </lineLoop>
    </group>
  );
}

type NodeSpec = { memory: Memory; ring: number; angle: number; speed: number };

function Nodes({
  nodes, highlighted, hoveredId, setHover, onSelect, focused,
}: {
  focused: React.MutableRefObject<boolean>;
  nodes: NodeSpec[];
  highlighted: Set<string>;
  hoveredId: string | null;
  setHover: (hover: Hover | null) => void;
  onSelect: (memory: Memory) => void;
}) {
  const meshes = useRef<(THREE.Mesh | null)[]>([]);
  const halos = useRef<(THREE.Mesh | null)[]>([]);
  const links = useRef<THREE.LineSegments>(null);
  const linkGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(nodes.length * 6), 3));
    const colors = new Float32Array(nodes.length * 6);
    const color = new THREE.Color();
    nodes.forEach((node, index) => {
      color.set(memoryColor(node.memory.type));
      colors.set([0.55, 0.5, 1, color.r, color.g, color.b], index * 6);
    });
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geometry;
  }, [nodes]);
  useEffect(() => () => linkGeometry.dispose(), [linkGeometry]);

  const tilts = useMemo(() => nodes.map((node) => new THREE.Euler(...ringTilt(node.ring))), [nodes]);
  const scratch = useMemo(() => new THREE.Vector3(), []);
  const orbitTime = useRef(0);
  const orbitRate = useRef(1);

  useFrame(({ clock }, delta) => {
    // Orbits ease almost to a stop while the pointer is over the view so nodes are easy to hit.
    orbitRate.current = THREE.MathUtils.damp(orbitRate.current, focused.current ? 0.08 : 1, 4, delta);
    orbitTime.current += Math.min(delta, 0.05) * orbitRate.current;
    const t = clock.elapsedTime;
    const positions = linkGeometry.getAttribute("position") as THREE.BufferAttribute;
    nodes.forEach((node, index) => {
      const mesh = meshes.current[index];
      if (!mesh) return;
      const angle = node.angle + orbitTime.current * node.speed;
      const radius = ringRadius(node.ring);
      scratch.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0).applyEuler(tilts[index]);
      mesh.position.copy(scratch);
      const isHighlighted = highlighted.has(node.memory.id);
      const isHovered = hoveredId === node.memory.id;
      const pulse = isHighlighted ? 1.25 + Math.sin(t * 4 + index) * 0.2 : 1;
      const target = (isHovered ? 1.7 : 1) * pulse;
      mesh.scale.setScalar(THREE.MathUtils.lerp(mesh.scale.x, target, 0.18));
      const halo = halos.current[index];
      if (halo) {
        halo.position.copy(scratch);
        halo.scale.setScalar(mesh.scale.x * (isHighlighted ? 2.6 + Math.sin(t * 4 + index) * 0.4 : 1.9));
        (halo.material as THREE.MeshBasicMaterial).opacity = isHighlighted || isHovered ? 0.35 : 0.12;
      }
      positions.setXYZ(index * 2, 0, 0, 0);
      positions.setXYZ(index * 2 + 1, scratch.x, scratch.y, scratch.z);
    });
    positions.needsUpdate = true;
  });

  const hoverFrom = (event: ThreeEvent<PointerEvent>, memory: Memory) => {
    event.stopPropagation();
    setHover({ memory, x: event.nativeEvent.offsetX, y: event.nativeEvent.offsetY });
  };

  return (
    <>
      <lineSegments ref={links} geometry={linkGeometry}>
        <lineBasicMaterial vertexColors transparent opacity={0.28} depthWrite={false} />
      </lineSegments>
      {nodes.map((node, index) => {
        const color = memoryColor(node.memory.type);
        return (
          <group key={node.memory.id}>
            <mesh ref={(el) => { halos.current[index] = el; }}>
              <sphereGeometry args={[0.13, 16, 16]} />
              <meshBasicMaterial color={color} transparent opacity={0.12} depthWrite={false} blending={THREE.AdditiveBlending} />
            </mesh>
            <mesh
              ref={(el) => { meshes.current[index] = el; }}
              onPointerOver={(event) => { hoverFrom(event, node.memory); document.body.style.cursor = "pointer"; }}
              onPointerMove={(event) => hoverFrom(event, node.memory)}
              onPointerOut={() => { setHover(null); document.body.style.cursor = ""; }}
              onClick={(event) => { event.stopPropagation(); onSelect(node.memory); }}
            >
              <icosahedronGeometry args={[0.14, 1]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.9} flatShading />
            </mesh>
          </group>
        );
      })}
    </>
  );
}

function Stars() {
  const geometry = useMemo(() => {
    const positions = new Float32Array(420 * 3);
    for (let index = 0; index < 420; index++) {
      const radius = 5 + Math.random() * 6;
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
  return (
    <points geometry={geometry}>
      <pointsMaterial size={0.035} color="#98a2d8" transparent opacity={0.6} sizeAttenuation depthWrite={false} />
    </points>
  );
}

function Scene({ memories, highlighted, onSelect, hoveredId, setHover, focused }: Props & {
  focused: React.MutableRefObject<boolean>;
  hoveredId: string | null;
  setHover: (hover: Hover | null) => void;
}) {
  const system = useRef<THREE.Group>(null);
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
      speed: reduced ? 0 : (0.22 - ring * 0.025) * (ring % 2 ? -1 : 1),
    })));
  }, [memories, reduced]);
  const rings = useMemo(() => [...new Set(nodes.map((node) => node.ring))], [nodes]);

  const spinTime = useRef(0);
  useFrame(({ pointer }, delta) => {
    const group = system.current;
    // Hold the camera angle while the pointer is inside, otherwise parallax makes nodes chase the cursor.
    if (!group || focused.current) return;
    spinTime.current += Math.min(delta, 0.05);
    const spin = reduced ? 0 : spinTime.current * 0.06;
    group.rotation.y = THREE.MathUtils.damp(group.rotation.y, pointer.x * 0.45 + spin, 3, delta);
    group.rotation.x = THREE.MathUtils.damp(group.rotation.x, -pointer.y * 0.2, 3, delta);
  });

  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[0, 0, 0]} intensity={8} color="#8d7cff" />
      <directionalLight position={[4, 5, 6]} intensity={1.2} />
      <Stars />
      <group ref={system}>
        <Core active={highlighted.size > 0} />
        {rings.map((ring) => <Ring key={ring} index={ring} />)}
        <Nodes nodes={nodes} highlighted={highlighted} hoveredId={hoveredId}
          setHover={setHover} onSelect={onSelect} focused={focused} />
      </group>
    </>
  );
}

export default function MemoryOrbit(props: Props) {
  const [hover, setHover] = useState<Hover | null>(null);
  const focused = useRef(false);
  useEffect(() => () => { document.body.style.cursor = ""; }, []);
  return (
    <div
      className="orbit-canvas"
      onPointerEnter={() => { focused.current = true; }}
      onPointerLeave={() => { focused.current = false; setHover(null); }}
    >
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 40, position: [0, 3.1, 6.3] }}
        gl={{ antialias: true, alpha: true }}
        onPointerMissed={() => setHover(null)}
      >
        <Scene {...props} hoveredId={hover?.memory.id || null} setHover={setHover} focused={focused} />
      </Canvas>
      <AnimatePresence>
        {hover && (
          <motion.div
            key={hover.memory.id}
            className="orbit-tooltip"
            initial={{ opacity: 0, y: 6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={{ duration: 0.16 }}
            style={{ left: hover.x, top: hover.y }}
          >
            <span style={{ color: memoryColor(hover.memory.type) }}>
              {hover.memory.type.replace(/_/g, " ")}
              {props.highlighted.has(hover.memory.id) ? " · recalled" : ""}
            </span>
            <p>{hover.memory.text}</p>
            <small>Click to inspect</small>
          </motion.div>
        )}
      </AnimatePresence>
      {!props.memories.length && (
        <p className="orbit-empty">The bank is empty. Retained memories will start orbiting here.</p>
      )}
    </div>
  );
}
