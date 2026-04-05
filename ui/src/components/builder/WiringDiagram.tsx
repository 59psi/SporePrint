/**
 * Color-coded SVG wiring diagrams for each hardware tier.
 * Each diagram shows ESP32 pinout, sensor/actuator modules, and labeled connections.
 */

interface WiringDiagramProps {
  tierId: string
}

const COLORS = {
  power3v3: '#ef4444',   // red — 3.3V
  power5v: '#f97316',    // orange — 5V
  power12v: '#eab308',   // yellow — 12V
  gnd: '#1e1e1e',        // near-black — ground
  sda: '#3b82f6',        // blue — I2C data
  scl: '#22c55e',        // green — I2C clock
  gpio: '#a855f7',       // purple — GPIO control
  signal: '#06b6d4',     // cyan — signal lines
  board: '#1e293b',      // dark slate — board fill
  boardStroke: '#475569', // slate border
  label: '#e2e8f0',      // light text
  sublabel: '#94a3b8',   // muted text
  wire: '#334155',       // default wire
}

function Board({ x, y, w, h, label, sublabel }: { x: number; y: number; w: number; h: number; label: string; sublabel?: string }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={COLORS.board} stroke={COLORS.boardStroke} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + 18} textAnchor="middle" fill={COLORS.label} fontSize={11} fontWeight="bold">{label}</text>
      {sublabel && <text x={x + w / 2} y={y + 32} textAnchor="middle" fill={COLORS.sublabel} fontSize={9}>{sublabel}</text>}
    </g>
  )
}

function Pin({ x, y, label, color, side = 'right' }: { x: number; y: number; label: string; color: string; side?: 'left' | 'right' }) {
  return (
    <g>
      <circle cx={x} cy={y} r={4} fill={color} stroke={color} strokeWidth={1} />
      <text
        x={side === 'right' ? x + 8 : x - 8}
        y={y + 3.5}
        textAnchor={side === 'right' ? 'start' : 'end'}
        fill={COLORS.sublabel}
        fontSize={8}
      >
        {label}
      </text>
    </g>
  )
}

function Wire({ x1, y1, x2, y2, color, label, labelPos = 0.5 }: { x1: number; y1: number; x2: number; y2: number; color: string; label?: string; labelPos?: number }) {
  const mx = x1 + (x2 - x1) * 0.4
  const path = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
  const lx = x1 + (x2 - x1) * labelPos
  const ly = y1 + (y2 - y1) * labelPos - 6
  return (
    <g>
      <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" />
      {label && <text x={lx} y={ly} textAnchor="middle" fill={color} fontSize={7} fontWeight="bold">{label}</text>}
    </g>
  )
}

function Legend({ x, y }: { x: number; y: number }) {
  const items = [
    { color: COLORS.power3v3, label: '3.3V' },
    { color: COLORS.power5v, label: '5V' },
    { color: COLORS.power12v, label: '12V' },
    { color: COLORS.gnd, label: 'GND' },
    { color: COLORS.sda, label: 'SDA (I2C Data)' },
    { color: COLORS.scl, label: 'SCL (I2C Clock)' },
    { color: COLORS.gpio, label: 'GPIO Control' },
  ]
  return (
    <g>
      <text x={x} y={y} fill={COLORS.sublabel} fontSize={9} fontWeight="bold">LEGEND</text>
      {items.map((item, i) => (
        <g key={i}>
          <line x1={x} y1={y + 12 + i * 14} x2={x + 16} y2={y + 12 + i * 14} stroke={item.color} strokeWidth={2.5} strokeLinecap="round" />
          <text x={x + 22} y={y + 15 + i * 14} fill={COLORS.sublabel} fontSize={8}>{item.label}</text>
        </g>
      ))}
    </g>
  )
}

function ClimateNodeDiagram() {
  // ESP32 on left, sensors on right
  const espX = 30, espY = 30, espW = 130, espH = 180
  const sensorX = 300
  return (
    <svg viewBox="0 0 520 280" className="w-full max-w-2xl">
      <rect width="520" height="280" fill="#0f172a" rx={8} />
      <text x={260} y={18} textAnchor="middle" fill={COLORS.label} fontSize={12} fontWeight="bold">Climate Node — I2C Sensor Hub</text>

      {/* ESP32 */}
      <Board x={espX} y={espY} w={espW} h={espH} label="ESP32-WROOM-32" sublabel="Climate Node" />
      <Pin x={espX + espW} y={espY + 55} label="3.3V" color={COLORS.power3v3} />
      <Pin x={espX + espW} y={espY + 75} label="GND" color={COLORS.gnd} />
      <Pin x={espX + espW} y={espY + 100} label="GPIO 21 (SDA)" color={COLORS.sda} />
      <Pin x={espX + espW} y={espY + 120} label="GPIO 22 (SCL)" color={COLORS.scl} />

      {/* SHT31 */}
      <Board x={sensorX} y={30} w={110} h={60} label="SHT31-D" sublabel="Temp + Humidity" />
      <Pin x={sensorX} y={55} label="VIN" color={COLORS.power3v3} side="left" />
      <Pin x={sensorX} y={70} label="GND" color={COLORS.gnd} side="left" />
      <Pin x={sensorX + 110} y={55} label="SDA" color={COLORS.sda} />
      <Pin x={sensorX + 110} y={70} label="SCL" color={COLORS.scl} />
      <text x={sensorX + 110 + 8} y={88} fill={COLORS.sublabel} fontSize={7}>addr: 0x44</text>

      {/* SCD40 */}
      <Board x={sensorX} y={105} w={110} h={60} label="SCD40" sublabel="CO2 Sensor" />
      <Pin x={sensorX} y={130} label="VIN" color={COLORS.power3v3} side="left" />
      <Pin x={sensorX} y={145} label="GND" color={COLORS.gnd} side="left" />
      <Pin x={sensorX + 110} y={130} label="SDA" color={COLORS.sda} />
      <Pin x={sensorX + 110} y={145} label="SCL" color={COLORS.scl} />
      <text x={sensorX + 110 + 8} y={163} fill={COLORS.sublabel} fontSize={7}>addr: 0x62</text>

      {/* BH1750 */}
      <Board x={sensorX} y={180} w={110} h={60} label="BH1750" sublabel="Light (Lux)" />
      <Pin x={sensorX} y={205} label="VCC" color={COLORS.power3v3} side="left" />
      <Pin x={sensorX} y={220} label="GND" color={COLORS.gnd} side="left" />
      <Pin x={sensorX + 110} y={205} label="SDA" color={COLORS.sda} />
      <Pin x={sensorX + 110} y={220} label="SCL" color={COLORS.scl} />
      <text x={sensorX + 110 + 8} y={238} fill={COLORS.sublabel} fontSize={7}>addr: 0x23</text>

      {/* Wires — 3.3V */}
      <Wire x1={espX + espW + 4} y1={espY + 55} x2={sensorX - 4} y2={55} color={COLORS.power3v3} label="3.3V" />
      <Wire x1={espX + espW + 4} y1={espY + 55} x2={sensorX - 4} y2={130} color={COLORS.power3v3} />
      <Wire x1={espX + espW + 4} y1={espY + 55} x2={sensorX - 4} y2={205} color={COLORS.power3v3} />

      {/* Wires — GND */}
      <Wire x1={espX + espW + 4} y1={espY + 75} x2={sensorX - 4} y2={70} color="#64748b" label="GND" />
      <Wire x1={espX + espW + 4} y1={espY + 75} x2={sensorX - 4} y2={145} color="#64748b" />
      <Wire x1={espX + espW + 4} y1={espY + 75} x2={sensorX - 4} y2={220} color="#64748b" />

      {/* Wires — SDA (shared bus) */}
      <Wire x1={espX + espW + 4} y1={espY + 100} x2={sensorX - 4} y2={55} color={COLORS.sda} label="SDA" labelPos={0.3} />
      <line x1={sensorX - 12} y1={55} x2={sensorX - 12} y2={205} stroke={COLORS.sda} strokeWidth={2} strokeDasharray="4 2" />

      {/* Wires — SCL (shared bus) */}
      <Wire x1={espX + espW + 4} y1={espY + 120} x2={sensorX - 20} y2={70} color={COLORS.scl} label="SCL" labelPos={0.3} />
      <line x1={sensorX - 28} y1={70} x2={sensorX - 28} y2={220} stroke={COLORS.scl} strokeWidth={2} strokeDasharray="4 2" />

      <Legend x={10} y={240} />
      <text x={260} y={270} textAnchor="middle" fill={COLORS.sublabel} fontSize={8}>All 3 sensors share the I2C bus (SDA + SCL). Power from ESP32 3.3V pin.</text>
    </svg>
  )
}

function RelayNodeDiagram() {
  const espX = 20, espY = 20
  return (
    <svg viewBox="0 0 560 260" className="w-full max-w-2xl">
      <rect width="560" height="260" fill="#0f172a" rx={8} />
      <text x={280} y={16} textAnchor="middle" fill={COLORS.label} fontSize={12} fontWeight="bold">Relay Node — MOSFET Fan Control (4 Channels)</text>

      <Board x={espX} y={espY} w={120} h={170} label="ESP32-WROOM-32" sublabel="Relay Node" />

      {/* Channels */}
      {[
        { gpio: 'GPIO 25', name: 'FAE Fan', y: 50 },
        { gpio: 'GPIO 26', name: 'Exhaust', y: 100 },
        { gpio: 'GPIO 27', name: 'Circulation', y: 150 },
        { gpio: 'GPIO 14', name: 'Aux', y: 200 },
      ].map((ch, i) => {
        const mosfetX = 230, fanX = 420
        const cy = ch.y
        return (
          <g key={i}>
            {/* ESP32 pin */}
            <Pin x={espX + 120} y={cy} label={ch.gpio} color={COLORS.gpio} />

            {/* 100R resistor + 10K pulldown */}
            <rect x={190} y={cy - 5} width={24} height={10} rx={2} fill="#374151" stroke={COLORS.gpio} strokeWidth={1} />
            <text x={202} y={cy + 3} textAnchor="middle" fill={COLORS.sublabel} fontSize={6}>100R</text>

            {/* MOSFET */}
            <Board x={mosfetX} y={cy - 18} w={70} h={36} label="IRLZ44N" />
            <text x={mosfetX + 35} y={cy + 12} textAnchor="middle" fill={COLORS.sublabel} fontSize={6}>G  D  S</text>

            {/* Flyback diode */}
            <rect x={320} y={cy - 8} width={30} height={16} rx={2} fill="#374151" stroke="#f97316" strokeWidth={1} />
            <text x={335} y={cy + 3} textAnchor="middle" fill="#f97316" fontSize={6}>1N4007</text>

            {/* Fan/Load */}
            <Board x={fanX} y={cy - 15} w={100} h={30} label={ch.name} sublabel="12V" />

            {/* Wires */}
            <Wire x1={espX + 124} y1={cy} x2={190} y2={cy} color={COLORS.gpio} />
            <line x1={214} y1={cy} x2={mosfetX} y2={cy} stroke={COLORS.gpio} strokeWidth={2} />
            <line x1={mosfetX + 70} y1={cy} x2={fanX} y2={cy} stroke={COLORS.power12v} strokeWidth={2} />

            {/* 10K pulldown to GND */}
            <line x1={202} y1={cy + 5} x2={202} y2={cy + 15} stroke="#64748b" strokeWidth={1} strokeDasharray="2 1" />
            <text x={210} y={cy + 14} fill={COLORS.sublabel} fontSize={5}>10K→GND</text>
          </g>
        )
      })}

      {/* 12V supply */}
      <text x={480} y={240} textAnchor="middle" fill={COLORS.power12v} fontSize={9} fontWeight="bold">+12V Supply</text>
      <line x1={520} y1={50} x2={520} y2={230} stroke={COLORS.power12v} strokeWidth={2} />

      <Legend x={10} y={210} />
    </svg>
  )
}

function LightingNodeDiagram() {
  const espX = 20, espY = 20
  return (
    <svg viewBox="0 0 560 220" className="w-full max-w-2xl">
      <rect width="560" height="220" fill="#0f172a" rx={8} />
      <text x={280} y={16} textAnchor="middle" fill={COLORS.label} fontSize={12} fontWeight="bold">Lighting Node — 10-bit PWM LED Dimming</text>

      <Board x={espX} y={espY} w={120} h={150} label="ESP32-WROOM-32" sublabel="Lighting Node" />

      {[
        { gpio: 'GPIO 25', name: '6500K White', y: 50, color: '#f8fafc' },
        { gpio: 'GPIO 26', name: '450nm Blue', y: 90, color: '#3b82f6' },
        { gpio: 'GPIO 27', name: '660nm Red', y: 130, color: '#ef4444' },
        { gpio: 'GPIO 14', name: '730nm Far-Red', y: 170, color: '#991b1b' },
      ].map((ch, i) => {
        const stripX = 380
        return (
          <g key={i}>
            <Pin x={espX + 120} y={ch.y} label={ch.gpio} color={COLORS.gpio} />

            {/* MOSFET block */}
            <rect x={200} y={ch.y - 10} width={60} height={20} rx={3} fill="#374151" stroke={COLORS.gpio} strokeWidth={1} />
            <text x={230} y={ch.y + 3} textAnchor="middle" fill={COLORS.sublabel} fontSize={7}>IRLZ44N</text>

            {/* LED strip */}
            <rect x={stripX} y={ch.y - 10} width={120} height={20} rx={3} fill={ch.color} fillOpacity={0.15} stroke={ch.color} strokeWidth={1.5} />
            <text x={stripX + 60} y={ch.y + 3} textAnchor="middle" fill={ch.color} fontSize={8} fontWeight="bold">{ch.name}</text>

            {/* Wires */}
            <line x1={espX + 124} y1={ch.y} x2={200} y2={ch.y} stroke={COLORS.gpio} strokeWidth={2} />
            <line x1={260} y1={ch.y} x2={stripX} y2={ch.y} stroke={COLORS.power12v} strokeWidth={2} />
          </g>
        )
      })}

      <text x={540} y={115} textAnchor="middle" fill={COLORS.power12v} fontSize={9} fontWeight="bold" transform="rotate(90,540,115)">+12V Supply</text>
      <text x={280} y={205} textAnchor="middle" fill={COLORS.sublabel} fontSize={8}>PWM Resolution: 10-bit (0-1023) at 25kHz — smooth, flicker-free dimming</text>
    </svg>
  )
}

function CameraNodeDiagram() {
  return (
    <svg viewBox="0 0 440 180" className="w-full max-w-xl">
      <rect width="440" height="180" fill="#0f172a" rx={8} />
      <text x={220} y={16} textAnchor="middle" fill={COLORS.label} fontSize={12} fontWeight="bold">Camera Node — ESP32-CAM (AI-Thinker)</text>

      <Board x={30} y={30} w={140} h={120} label="ESP32-CAM" sublabel="OV2640 Camera" />

      {/* Camera icon */}
      <rect x={70} y={70} width={40} height={30} rx={4} fill="none" stroke={COLORS.sublabel} strokeWidth={1} />
      <circle cx={90} cy={85} r={8} fill="none" stroke={COLORS.sublabel} strokeWidth={1} />
      <text x={100} y={115} textAnchor="middle" fill={COLORS.sublabel} fontSize={7}>OV2640</text>

      {/* Flash LED */}
      <Pin x={30} y={130} label="GPIO 4 (Flash LED)" color="#eab308" side="right" />

      {/* USB-UART programmer */}
      <Board x={260} y={40} w={140} h={90} label="USB-UART" sublabel="CP2102 / CH340" />

      <Pin x={170} y={55} label="5V" color={COLORS.power5v} />
      <Pin x={170} y={75} label="GND" color="#64748b" />
      <Pin x={170} y={95} label="U0R (RX)" color={COLORS.signal} />
      <Pin x={170} y={115} label="U0T (TX)" color={COLORS.scl} />

      <Pin x={260} y={65} label="5V" color={COLORS.power5v} side="left" />
      <Pin x={260} y={80} label="GND" color="#64748b" side="left" />
      <Pin x={260} y={95} label="TX" color={COLORS.signal} side="left" />
      <Pin x={260} y={110} label="RX" color={COLORS.scl} side="left" />

      <Wire x1={174} y1={55} x2={256} y2={65} color={COLORS.power5v} label="5V" />
      <Wire x1={174} y1={75} x2={256} y2={80} color="#64748b" label="GND" />
      <Wire x1={174} y1={95} x2={256} y2={95} color={COLORS.signal} label="RX→TX" />
      <Wire x1={174} y1={115} x2={256} y2={110} color={COLORS.scl} label="TX→RX" />

      <text x={220} y={155} textAnchor="middle" fill={COLORS.sublabel} fontSize={8}>For flashing: hold GPIO 0 → GND, then upload.</text>
      <text x={220} y={168} textAnchor="middle" fill={COLORS.sublabel} fontSize={8}>After flashing: remove GPIO 0 jumper, power via 5V USB.</text>
    </svg>
  )
}

export default function WiringDiagram({ tierId }: WiringDiagramProps) {
  if (tierId === 'bare_bones') {
    return (
      <div className="space-y-6">
        <ClimateNodeDiagram />
      </div>
    )
  }

  if (tierId === 'recommended') {
    return (
      <div className="space-y-6">
        <ClimateNodeDiagram />
        <RelayNodeDiagram />
        <LightingNodeDiagram />
        <CameraNodeDiagram />
      </div>
    )
  }

  // all_the_things — same diagrams, note about second climate + camera node
  return (
    <div className="space-y-6">
      <ClimateNodeDiagram />
      <RelayNodeDiagram />
      <LightingNodeDiagram />
      <CameraNodeDiagram />
      <div className="p-4 rounded-lg bg-[var(--color-bg-primary)] text-sm text-[var(--color-text-secondary)]">
        <p className="font-medium text-[var(--color-text-primary)] mb-2">Additional for Tier 3:</p>
        <ul className="space-y-1 text-xs">
          <li>+ Second Climate Node — wire identically, set node_id to "climate-02"</li>
          <li>+ Second ESP32-CAM — wire identically, set node_id to "cam-02", mount top-down</li>
          <li>+ HX711 Load Cell — wire DOUT→GPIO 32, SCK→GPIO 33 on relay node</li>
          <li>+ Reed Switch — wire one leg to any ESP32 GPIO (INPUT_PULLUP), other to GND</li>
          <li>+ Peristaltic Pump — connect to relay node aux channel (GPIO 14) via IRLZ44N</li>
        </ul>
      </div>
    </div>
  )
}
