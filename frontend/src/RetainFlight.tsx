import { motion } from "framer-motion";

export type Point = { x: number; y: number };

export type Flight = { id: number; from: Point; to: Point; color: string; onLand: () => void };

const SAMPLES = 16;
const DURATION = 1.05;
const TRAIL = 6;

/** Samples a quadratic bezier that bows upward, so the orb arcs instead of sliding. */
function arc(from: Point, to: Point) {
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  const control = {
    x: (from.x + to.x) / 2 + (to.y - from.y) * 0.15,
    y: Math.min(from.y, to.y) - Math.max(80, distance * 0.35),
  };
  const xs: number[] = [];
  const ys: number[] = [];
  for (let step = 0; step <= SAMPLES; step++) {
    // Ease along the curve itself so the linear keyframe timing stays perfectly smooth.
    const linear = step / SAMPLES;
    const t = linear < 0.5 ? 4 * linear ** 3 : 1 - (-2 * linear + 2) ** 3 / 2;
    const u = 1 - t;
    xs.push(u * u * from.x + 2 * u * t * control.x + t * t * to.x);
    ys.push(u * u * from.y + 2 * u * t * control.y + t * t * to.y);
  }
  return { xs, ys };
}

function FlightPath({ flight, onDone }: { flight: Flight; onDone: (id: number) => void }) {
  const { xs, ys } = arc(flight.from, flight.to);
  return (
    <>
      {Array.from({ length: TRAIL }, (_, index) => {
        const head = index === 0;
        const size = head ? 16 : Math.max(4, 11 - index * 1.4);
        return (
          <motion.span
            key={index}
            className={"flight-orb" + (head ? " head" : "")}
            style={{
              width: size,
              height: size,
              marginLeft: -size / 2,
              marginTop: -size / 2,
              ["--orb" as string]: flight.color,
            }}
            initial={{ x: xs[0], y: ys[0], opacity: 0, scale: 0.2 }}
            animate={{
              x: xs,
              y: ys,
              opacity: head ? [0, 1, 1, 1, 0] : [0, 0.7 - index * 0.1, 0.5 - index * 0.07, 0],
              scale: head ? [0.2, 1.4, 1, 1, 0.6] : [0.2, 1, 0.8, 0.3],
            }}
            transition={{
              x: { duration: DURATION, ease: "linear", delay: index * 0.035 },
              y: { duration: DURATION, ease: "linear", delay: index * 0.035 },
              opacity: { duration: DURATION, ease: "easeInOut", delay: index * 0.035 },
              scale: { duration: DURATION, ease: "easeInOut", delay: index * 0.035 },
            }}
            onAnimationComplete={head ? () => {
              flight.onLand();
              // Leave time for the landing burst before unmounting.
              window.setTimeout(() => onDone(flight.id), 900);
            } : undefined}
          />
        );
      })}
    </>
  );
}

function Landing({ flight }: { flight: Flight }) {
  return (
    <motion.span
      className="flight-burst"
      style={{ left: flight.to.x, top: flight.to.y, ["--orb" as string]: flight.color }}
      initial={{ scale: 0.2, opacity: 0 }}
      animate={{ scale: [0.2, 2.6], opacity: [0, 0.9, 0] }}
      transition={{ duration: 0.8, delay: DURATION - 0.05, ease: [0.22, 1, 0.36, 1] }}
    />
  );
}

export function RetainFlights({ flights, onDone }: { flights: Flight[]; onDone: (id: number) => void }) {
  if (!flights.length) return null;
  return (
    <div className="flight-layer" aria-hidden="true">
      {flights.map((flight) => (
        <div key={flight.id}>
          <FlightPath flight={flight} onDone={onDone} />
          <Landing flight={flight} />
        </div>
      ))}
    </div>
  );
}
