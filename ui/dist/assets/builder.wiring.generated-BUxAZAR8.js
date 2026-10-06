const t={bare_bones:{tierId:"bare_bones",filename:"wiring-tier1-bare-bones.svg",title:"Tier 1: Bare Bones Wiring Diagram",summary:"ESP32 + two I2C sensors on one STEMMA QT chain — no soldering, no breadboard. Power strip outside the chamber; the Pi and the smart plug connect over WiFi only.",width:1e3,height:850,bytes:19770,sha256:"d904242832d4c77dc5459573ce4e5b5751d913af6005b59087da7b2c53f91332",svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 850" width="1000" height="850">

  <!-- Background -->
  <rect width="1000" height="850" fill="#0a0a0f"/>

  <!-- ═══════════════════════ TITLE ═══════════════════════ -->
  <text x="500" y="30" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="700">Tier 1: Bare Bones Wiring Diagram</text>
  <text x="500" y="50" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="11">ESP32 + two I2C sensors on one STEMMA QT chain — no soldering, no breadboard. Power strip outside the chamber; the Pi and the smart plug connect over WiFi only.</text>

  <!-- ═══════ OUTSIDE THE CHAMBER (dry side) ═══════ -->
  <rect x="16" y="64" width="396" height="476" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="32" y="86" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">OUTSIDE THE CHAMBER — the dry side</text>

  <!-- ═══════ CHAMBER WALL ═══════ -->
  <rect x="420" y="64" width="26" height="476" rx="4" fill="#1f2937" stroke="#64748b" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="437" y="380" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" transform="rotate(-90 437 380)">CHAMBER WALL — grommet</text>

  <!-- ═══════ INSIDE THE GROW CHAMBER ═══════ -->
  <rect x="454" y="64" width="530" height="476" rx="6" fill="#0b1716" stroke="#2dd4bf" stroke-width="1.2" stroke-dasharray="6,4"/>
  <text x="470" y="86" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">INSIDE THE GROW CHAMBER (85-95 % RH)</text>
  <text x="32" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">power strip, Pi, USB charger and the smart plug</text>
  <text x="470" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">the climate node, its sensors and the humidifier</text>

  <!-- Power strip (mains, outside the chamber) -->
  <rect x="28" y="112" width="106" height="416" rx="8" fill="#1e293b" stroke="#f97316" stroke-width="1.5"/>
  <text x="81.0" y="132" text-anchor="middle" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">Power strip</text>
  <text x="81.0" y="146" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">UL-listed surge</text>
  <text x="81.0" y="158" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">protector</text>
  <text x="81.0" y="170" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">6</text>
  <text x="81.0" y="182" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">widely spaced</text>
  <text x="81.0" y="194" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">outlets</text>
  <text x="81.0" y="506" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cord to a</text>
  <text x="81.0" y="517" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">wall outlet</text>

  <!-- Pi + its PSU -->
  <rect x="116" y="131" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="124" y1="136" x2="124" y2="144" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="132" y1="136" x2="132" y2="144" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="140" y1="140" x2="150" y2="140" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="150" y="126" width="130" height="28" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="211" y="138" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Pi 27 W USB-C PSU</text>
  <text x="211" y="149" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">official, 5.1 V 5 A</text>
  <path d="M 280 140 L 300 140 L 300 168" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="150" y="168" width="250" height="44" rx="6" fill="#1e293b" stroke="#34d399" stroke-width="1.5"/>
  <text x="275" y="186" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">Raspberry Pi 5 + Active Cooler (pi_case)</text>
  <text x="275" y="202" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">SporePrint server + credentialed MQTT broker</text>
  <g>
  <rect x="150" y="218" width="250" height="18" rx="4" fill="#0f2418" stroke="#34d399" stroke-width="0.6"/>
  <text x="275.0" y="229.88" text-anchor="middle" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">WiFi / MQTT to the node and the plug — no wires</text>
  </g>

  <!-- USB charger → 6 ft USB-C cable through the grommet -->
  <rect x="116" y="271" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="124" y1="276" x2="124" y2="284" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="132" y1="276" x2="132" y2="284" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="140" y1="280" x2="150" y2="280" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="150" y="264" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="211.0" y="277" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="211.0" y="290" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">UL, one per board</text>
  <rect x="276" y="275" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 284 280 L 536 280" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="292" y="272" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">USB-A → USB-C, 6 ft (2 m)</text>
  <rect x="423" y="268" width="20" height="24" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>

  <!-- Tasmota plug → humidifier cord through the grommet -->
  <rect x="116" y="481" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="124" y1="486" x2="124" y2="494" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="132" y1="486" x2="132" y2="494" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="140" y="479" width="144" height="22" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1"/>
  <text x="212" y="493" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota plug · humidifier</text>
  <line x1="284" y1="490" x2="560" y2="490" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="423" y="480" width="20" height="20" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="150" y="452" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota MQTT: User sp-3p, Topic humidifier,</text>
  <text x="150" y="464" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Full Topic tasmota/%topic%/%prefix%/ (required)</text>
  <rect x="560" y="476" width="410" height="30" rx="4" fill="#1e293b" stroke="#fdba74" stroke-width="1"/>
  <text x="570" y="489" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Ultrasonic humidifier (inside, or piped in) — plug-humidifier</text>
  <text x="570" y="501" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">its cord runs out through the grommet to the plug on the strip</text>

  <!-- ═══════ ESP32-WROOM-32 DEVKIT (inside) ═══════ -->
  <rect x="540" y="150" width="170" height="270" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="625" y="172" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32-WROOM-32 DevKit</text>
  <text x="625" y="188" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">climate-01 (env node_esp32)</text>
  <text x="625" y="201" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <rect x="536" y="274" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="458" y="272" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">to USB-C</text>
  <rect x="692" y="206" width="14" height="196" rx="2" fill="#0f172a" stroke="#334155" stroke-width="0.5"/>
  <circle cx="699" cy="222" r="6" fill="#ef4444"/>
  <text x="684" y="219" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">3V3</text>
  <text x="684" y="233" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">red socket</text>
  <circle cx="699" cy="268" r="6" fill="#1e1e1e" stroke="#6b7280" stroke-width="1"/>
  <text x="684" y="265" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">GND</text>
  <text x="684" y="279" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">any GND (not EN)</text>
  <circle cx="699" cy="314" r="6" fill="#3b82f6"/>
  <text x="684" y="311" text-anchor="end" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">GPIO 21</text>
  <text x="684" y="325" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">SDA</text>
  <circle cx="699" cy="360" r="6" fill="#eab308"/>
  <text x="684" y="357" text-anchor="end" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">GPIO 22</text>
  <text x="684" y="371" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">SCL</text>

  <!-- SHT31-D + BH1750 -->
  <rect x="790" y="196" width="176" height="96" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="878" y="222" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="600">SHT31-D</text>
  <text x="878" y="240" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="10">Temperature + Humidity</text>
  <text x="878" y="256" text-anchor="middle" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="9">I2C address: 0x44</text>
  <text x="878" y="282" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">QT in (left) / QT out (bottom)</text>
  <rect x="778" y="222" width="14" height="34" rx="2" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <rect x="790" y="336" width="176" height="76" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="878" y="362" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="600">BH1750</text>
  <text x="878" y="380" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="10">Ambient Light (lux)</text>
  <text x="878" y="398" text-anchor="middle" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="9">I2C address: 0x23</text>
  <path d="M 705 222 L 722 222 L 722 228 L 778 228" fill="none" stroke="#ef4444" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 705 268 L 734 268 L 734 236 L 778 236" fill="none" stroke="#4b5563" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 705 314 L 746 314 L 746 244 L 778 244" fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 705 360 L 758 360 L 758 252 L 778 252" fill="none" stroke="#eab308" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="716" y="150" width="140" height="34" rx="4" fill="#0a0a0f" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="786" y="164" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Adafruit 4397 cable</text>
  <text x="786" y="177" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">female sockets → QT plug</text>
  <line x1="842" y1="292" x2="842" y2="336" stroke="#ef4444" stroke-width="3"/>
  <line x1="850" y1="292" x2="850" y2="336" stroke="#4b5563" stroke-width="3"/>
  <line x1="858" y1="292" x2="858" y2="336" stroke="#3b82f6" stroke-width="3"/>
  <line x1="866" y1="292" x2="866" y2="336" stroke="#eab308" stroke-width="3"/>
  <rect x="880" y="298" width="96" height="30" rx="4" fill="#0a0a0f" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="928" y="311" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Adafruit 4210</text>
  <text x="928" y="323" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">QT-QT cable</text>
  <text x="540" y="438" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">One chain, not a star: ESP32 → 4397 → SHT31-D → 4210 → BH1750 (different I2C addresses).</text>
  <text x="540" y="451" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">sensor_mount + sensor_bracket at the centre of the chamber, substrate level; vents open.</text>

  <!-- ═══════ LEGEND ═══════ -->
  <rect x="16" y="552" width="968" height="40" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <line x1="30" y1="572" x2="56" y2="572" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
  <text x="62" y="576" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="9">RED = 3V3</text>
  <line x1="128.6" y1="572" x2="154.6" y2="572" stroke="#4b5563" stroke-width="3" stroke-linecap="round"/>
  <text x="160.6" y="576" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLACK = GND</text>
  <line x1="238.0" y1="572" x2="264.0" y2="572" stroke="#3b82f6" stroke-width="3" stroke-linecap="round"/>
  <text x="270.0" y="576" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLUE = SDA</text>
  <line x1="342.0" y1="572" x2="368.0" y2="572" stroke="#eab308" stroke-width="3" stroke-linecap="round"/>
  <text x="374.0" y="576" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="9">YELLOW = SCL</text>
  <line x1="456.8" y1="572" x2="482.8" y2="572" stroke="#f97316" stroke-width="3" stroke-linecap="round"/>
  <text x="488.8" y="576" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="9">ORANGE = 120 V AC cord</text>
  <line x1="625.6" y1="572" x2="651.6" y2="572" stroke="#22d3ee" stroke-width="3" stroke-linecap="round"/>
  <text x="657.6" y="576" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">CYAN = USB 5 V cable</text>
  <rect x="783.6" y="566" width="26" height="12" rx="6.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="815.6" y="576" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">= through the chamber wall</text>

  <!-- ═══════ WIRING STEPS ═══════ -->
  <rect x="16" y="602" width="968" height="222" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="32" y="626" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="700">Wiring Steps (two cables, no soldering)</text>
  <text x="32" y="650" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">Adafruit 4397 (female sockets onto the ESP32 pins):</text>
  <circle cx="42" cy="668" r="5" fill="#ef4444"/>
  <text x="54" y="672" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">1. red socket  →  ESP32 3V3</text>
  <circle cx="42" cy="690" r="5" fill="#1e1e1e" stroke="#6b7280" stroke-width="1"/>
  <text x="54" y="694" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">2. black socket  →  ESP32 GND (any GND pin, never EN)</text>
  <circle cx="42" cy="712" r="5" fill="#3b82f6"/>
  <text x="54" y="716" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">3. blue socket  →  ESP32 GPIO 21 (SDA)</text>
  <circle cx="42" cy="734" r="5" fill="#eab308"/>
  <text x="54" y="738" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">4. yellow socket  →  ESP32 GPIO 22 (SCL)</text>
  <text x="480" y="650" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">STEMMA QT plugs, power, plug:</text>
  <text x="480" y="672" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">5. 4397 QT plug  →  SHT31-D STEMMA QT port</text>
  <text x="480" y="690" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">6. Adafruit 4210 QT-QT: SHT31-D second port  →  BH1750</text>
  <text x="480" y="708" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">7. 5 V charger on the strip  →  6 ft (2 m) USB-A → USB-C cable,</text>
  <text x="480" y="726" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">    through the grommet  →  the ESP32 (charger stays outside)</text>
  <text x="480" y="744" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10">8. Strip outside the chamber: Pi PSU, USB charger, Tasmota plug</text>
  <text x="32" y="772" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-style="italic">Tip: the sensors share one I2C bus at different addresses (0x44 and 0x23), so there is no conflict. Leave their loose header strips unsoldered.</text>
  <text x="32" y="790" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-style="italic">ESP32-S3 board? Different pins: SDA = GPIO 8, SCL = GPIO 9 (env node_esp32s3 / node_esp32s3_n32r16v). See the build guide, section 8a.</text>
  <text x="32" y="808" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-style="italic">The Pi and the Tasmota plug need zero wires to the node — they talk over WiFi. The 6 ft cable passes a 7/8 in. grommet; zip-tie the run.</text>

  <!-- ═══════════════════════ FOOTER ═══════════════════════ -->
  <text x="500" y="842" text-anchor="middle" fill="#334155" font-family="system-ui, -apple-system, sans-serif" font-size="9">SporePrint  |  Tier 1: Bare Bones  |  github.com/59psi/SporePrint</text>

</svg>
`},recommended:{tierId:"recommended",filename:"wiring-tier2-recommended.svg",title:"Tier 2: Recommended Wiring Diagram",summary:"3 ESP32 nodes + 1 camera · power strip → 12V 5A PSU → 14 AWG pigtail → WAGO → fused 18 AWG branches → 2 switch boards · STEMMA QT sensor chain · 2 smart plugs",width:1600,height:1496,bytes:67527,sha256:"ea6bd045b13b38f5a9f57d2183a4929107514a0b7d7dce4c2fdd5f7bdf1ca3e1",svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1496" width="1600" height="1496">

  <!-- Background -->
  <rect width="1600" height="1496" fill="#0a0a0f"/>

  <!-- ═══════════════════════ TITLE ═══════════════════════ -->
  <text x="800" y="30" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="700">Tier 2: Recommended Wiring Diagram</text>
  <text x="800" y="50" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="11">3 ESP32 nodes + 1 camera · power strip → 12V 5A PSU → 14 AWG pigtail → WAGO → fused 18 AWG branches → 2 switch boards · STEMMA QT sensor chain · 2 smart plugs</text>

  <!-- ═══════ OUTSIDE THE CHAMBER (dry side) ═══════ -->
  <rect x="16" y="64" width="988" height="966" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="32" y="86" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">OUTSIDE THE CHAMBER — the dry side</text>

  <!-- ═══════ CHAMBER WALL ═══════ -->
  <rect x="1012" y="64" width="26" height="966" rx="4" fill="#1f2937" stroke="#64748b" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="1029" y="540" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" transform="rotate(-90 1029 540)">CHAMBER WALL — 7/8 in. grommet / tent cable port</text>

  <!-- ═══════ INSIDE THE GROW CHAMBER ═══════ -->
  <rect x="1046" y="64" width="538" height="966" rx="6" fill="#0b1716" stroke="#2dd4bf" stroke-width="1.2" stroke-dasharray="6,4"/>
  <text x="1062" y="86" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">INSIDE THE GROW CHAMBER (85-95 % RH)</text>
  <text x="32" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">power strip, 12 V supply, chargers, Pi, smart plugs and both switch boards</text>
  <text x="1062" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">sensors, camera and 12 V loads only — no supplies, chargers or switch boards</text>

  <!-- Power strip (mains, outside the chamber) -->
  <rect x="28" y="112" width="112" height="908" rx="8" fill="#1e293b" stroke="#f97316" stroke-width="1.5"/>
  <text x="84.0" y="132" text-anchor="middle" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">Power strip</text>
  <text x="84.0" y="146" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">UL-listed surge</text>
  <text x="84.0" y="158" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">protector</text>
  <text x="84.0" y="170" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">12</text>
  <text x="84.0" y="182" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">widely spaced</text>
  <text x="84.0" y="194" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">outlets</text>
  <text x="84.0" y="998" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cord to a</text>
  <text x="84.0" y="1009" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">wall outlet</text>

  <!-- USB chargers for the two in-chamber boards (6 ft cables) -->
  <rect x="122" y="123" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="128" x2="130" y2="136" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="128" x2="138" y2="136" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="132" x2="160" y2="132" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="116" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="129" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="142" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft micro-USB → CAM-MB</text>
  <rect x="286" y="127" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <rect x="122" y="167" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="172" x2="130" y2="180" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="172" x2="138" y2="180" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="176" x2="160" y2="176" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="160" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="173" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="186" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft USB-C → climate</text>
  <rect x="286" y="171" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 294 132 L 1096 132" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 294 176 L 1058 176" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="560" y="126" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → micro-USB, 6 ft (2 m) → the camera's ESP32-CAM-MB</text>
  <text x="560" y="170" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → USB-C, 6 ft (2 m) → the climate ESP32 (in the chamber)</text>
  <rect x="1015" y="120" width="20" height="68" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>

  <!-- ═══════ RELAY NODE (outside) ═══════ -->
  <rect x="304" y="206" width="692" height="296" rx="6" fill="#0f1623" stroke="#475569" stroke-width="1"/>
  <text x="318" y="226" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Relay node</text>
  <text x="392" y="226" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay_board_mount, node="relay" — 4 switch channels, a UF4007 on every one</text>
  <rect x="122" y="267" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="272" x2="130" y2="280" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="272" x2="138" y2="280" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="276" x2="160" y2="276" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="260" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="273" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="286" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">1 ft USB-C → relay</text>
  <rect x="286" y="271" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <rect x="320" y="250" width="120" height="140" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="380.0" y="267" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="380.0" y="281" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay-01</text>
  <text x="380.0" y="294" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <text x="432" y="309" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 25</text>
  <circle cx="440" cy="306" r="3.5" fill="#22c55e"/>
  <text x="432" y="325" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 26</text>
  <circle cx="440" cy="322" r="3.5" fill="#22c55e"/>
  <text x="432" y="341" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 27</text>
  <circle cx="440" cy="338" r="3.5" fill="#22c55e"/>
  <text x="432" y="357" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 14</text>
  <circle cx="440" cy="354" r="3.5" fill="#22c55e"/>
  <text x="432" y="377" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="440" cy="374" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <rect x="316" y="270" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 294 276 L 316 276" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="540" y="258" width="440" height="220" rx="4" fill="#16202f" stroke="#64748b" stroke-width="1.2"/>
  <text x="760.0" y="273" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">IRLZ44N switch board (relay_board_mount)</text>
  <line x1="590" y1="284" x2="590" y2="478" stroke="#4b5563" stroke-width="3.5"/>
  <line x1="930" y1="284" x2="930" y2="478" stroke="#ef4444" stroke-width="3.5"/>
  <rect x="544" y="285" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="296" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="307" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="304" x2="590" y2="304" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="296" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH0 fae — FAE fan (GPIO 25)</text>
  <text x="598" y="308" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">100R gate · 10K pull-down · IRLZ44N · UF4007 across J2</text>
  <rect x="938" y="285" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="296" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="307" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="293" x2="938" y2="293" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="323" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="334" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="345" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="342" x2="590" y2="342" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="334" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH1 exhaust — exhaust fan (GPIO 26)</text>
  <text x="598" y="346" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="323" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="334" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="345" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="331" x2="938" y2="331" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="361" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="372" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="383" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="380" x2="590" y2="380" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="372" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH2 circulation — circulation fan (GPIO 27)</text>
  <text x="598" y="384" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="361" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="372" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="383" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="369" x2="938" y2="369" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="399" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="410" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="421" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="418" x2="590" y2="418" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="410" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH3 aux — spare, 60 s max-on (GPIO 14)</text>
  <text x="598" y="422" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">the pump channel in All the Things</text>
  <rect x="938" y="399" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="410" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="421" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="407" x2="938" y2="407" stroke="#ef4444" stroke-width="1.5"/>
  <text x="596" y="470" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND bus</text>
  <text x="924" y="470" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus</text>
  <path d="M 440 306 L 470 306 L 470 294 L 544 294" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 322 L 478 322 L 478 332 L 544 332" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 338 L 486 338 L 486 370 L 544 370" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 354 L 494 354 L 494 408 L 544 408" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 374 L 462 374 L 462 446 L 520 446 L 520 418 L 544 418" fill="none" stroke="#4b5563" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="492" y="272" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8">Dupont jumpers</text>
  <text x="492" y="283" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">(or 22 AWG)</text>
  <rect x="320" y="454" width="200" height="40" rx="4" fill="#0a0a0f" stroke="#eab308" stroke-width="0.8" stroke-dasharray="3,2"/>
  <text x="328" y="467" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">COMMON GROUND</text>
  <text x="328" y="479" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">ESP32 GND → J1 − → GND bus</text>
  <line x1="976" y1="293" x2="1180" y2="293" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="304" x2="1180" y2="304" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="282" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="295" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">FAE fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="308" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">fresh-air intake at the wall · fan_duct</text>
  <line x1="976" y1="331" x2="1180" y2="331" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="342" x2="1180" y2="342" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="320" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="333" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Exhaust fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="346" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">exhaust at the wall · fan_duct</text>
  <line x1="976" y1="369" x2="1180" y2="369" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="380" x2="1180" y2="380" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="358" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="371" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Circulation fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="384" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">inside, away from the sensors</text>
  <rect x="1015" y="284" width="20" height="108" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1056" y="432" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Fans: bundled 30 cm extension + Noctua NA-SEC3 4-pin extension (cut its far end): GND → J2 −,</text>
  <text x="1056" y="444" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">+12 V → J2 + — identify by pin position, not colour; tach + PWM unused (heat-shrink them).</text>

  <!-- ═══════ 12 V DISTRIBUTION: PSU → pigtail → WAGO → fuses ═══════ -->
  <rect x="122" y="549" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="554" x2="130" y2="562" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="554" x2="138" y2="562" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="558" x2="160" y2="558" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="516" width="130" height="84" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="225.0" y="534" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12V 5A PSU (60W)</text>
  <text x="225.0" y="548" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Facmogu AL-1250</text>
  <text x="225.0" y="561" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">power_supply_mount</text>
  <text x="225.0" y="574" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">5.5 × 2.5 mm barrel</text>
  <text x="225.0" y="587" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">load ≤ ~4 A</text>
  <rect x="290" y="546" width="10" height="22" rx="2" fill="#0a0a0f" stroke="#94a3b8" stroke-width="0.8"/>
  <path d="M 300 562 L 546 562" fill="none" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 300 552 L 330 552 L 330 520 L 584 520 A 6 6 0 0 1 596 520 L 866 520 L 866 548 L 886 548" fill="none" stroke="#ef4444" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="318" y="584" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">5.5 × 2.5 mm DC barrel pigtail — 14 AWG</text>
  <rect x="546" y="540" width="88" height="24" rx="3" fill="#1e293b" stroke="#9ca3af" stroke-width="1.2"/>
  <text x="590" y="555" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">WAGO 221-415 GND</text>
  <rect x="886" y="540" width="88" height="24" rx="3" fill="#1e293b" stroke="#ef4444" stroke-width="1.2"/>
  <text x="930" y="555" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">WAGO 221-413 +12V</text>
  <line x1="590" y1="540" x2="590" y2="478" stroke="#4b5563" stroke-width="3"/>
  <line x1="930" y1="540" x2="930" y2="478" stroke="#ef4444" stroke-width="3"/>
  <rect x="923" y="490" width="14" height="28" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="930.0" y1="494" x2="930.0" y2="514" stroke="#fca5a5" stroke-width="1"/>
  <text x="930.0" y="486" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700"></text>
  <text x="916" y="515" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">3 A fuse</text>
  <text x="916" y="525" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">relay branch</text>
  <line x1="590" y1="564" x2="590" y2="652" stroke="#4b5563" stroke-width="3"/>
  <line x1="930" y1="564" x2="930" y2="652" stroke="#ef4444" stroke-width="3"/>
  <rect x="923" y="584" width="14" height="28" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="930.0" y1="588" x2="930.0" y2="608" stroke="#fca5a5" stroke-width="1"/>
  <text x="930.0" y="580" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700"></text>
  <text x="916" y="597" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">5 A fuse</text>
  <text x="916" y="608" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">lighting branch</text>
  <text x="604" y="596" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">branches: 18 AWG red (+12 V, fused)</text>
  <text x="604" y="608" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">and black (GND, not fused)</text>

  <!-- ═══════ LIGHTING NODE (outside) ═══════ -->
  <rect x="304" y="626" width="692" height="300" rx="6" fill="#0f1623" stroke="#475569" stroke-width="1"/>
  <text x="318" y="646" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Lighting node</text>
  <text x="318" y="660" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay_board_mount, node="lighting" (PETG)</text>
  <text x="318" y="672" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">no diodes — LED strips are resistive</text>
  <rect x="122" y="701" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="706" x2="130" y2="714" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="706" x2="138" y2="714" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="710" x2="160" y2="710" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="694" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="707" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="720" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">1 ft USB-C → lighting</text>
  <rect x="286" y="705" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <rect x="320" y="684" width="120" height="140" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="380.0" y="701" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="380.0" y="715" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">lighting-01</text>
  <text x="380.0" y="728" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <text x="432" y="743" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 25</text>
  <circle cx="440" cy="740" r="3.5" fill="#22c55e"/>
  <text x="432" y="759" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 26</text>
  <circle cx="440" cy="756" r="3.5" fill="#22c55e"/>
  <text x="432" y="775" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 27 spare</text>
  <circle cx="440" cy="772" r="3.5" fill="#22c55e"/>
  <text x="432" y="791" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 14 spare</text>
  <circle cx="440" cy="788" r="3.5" fill="#22c55e"/>
  <text x="432" y="811" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="440" cy="808" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <rect x="316" y="704" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 294 710 L 316 710" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="540" y="652" width="440" height="196" rx="4" fill="#16202f" stroke="#64748b" stroke-width="1.2"/>
  <text x="760.0" y="667" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">IRLZ44N switch board (relay_board_mount)</text>
  <line x1="590" y1="652" x2="590" y2="834" stroke="#4b5563" stroke-width="3.5"/>
  <line x1="930" y1="652" x2="930" y2="834" stroke="#ef4444" stroke-width="3.5"/>
  <rect x="544" y="687" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="698" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="709" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="706" x2="590" y2="706" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="698" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH0 white — 6500K strip (GPIO 25)</text>
  <text x="598" y="710" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">100R gate · 10K pull-down · IRLZ44N · no diode</text>
  <rect x="938" y="687" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="698" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="709" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="695" x2="938" y2="695" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="725" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="736" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="747" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="744" x2="590" y2="744" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="736" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH1 blue — tri-spectrum BLUE wire (GPIO 26)</text>
  <text x="598" y="748" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="725" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="736" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="747" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="733" x2="938" y2="733" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="763" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="774" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="785" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="782" x2="590" y2="782" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="774" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH2 red — spare (GPIO 27)</text>
  <text x="598" y="786" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">the strip's RED wire, later — no re-flash</text>
  <rect x="938" y="763" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="774" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="785" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="771" x2="938" y2="771" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="801" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="812" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="823" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="820" x2="590" y2="820" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="812" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH3 far_red — spare (GPIO 14)</text>
  <text x="598" y="824" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">the strip's GREEN wire (730 nm), later</text>
  <rect x="938" y="801" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="812" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="823" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="809" x2="938" y2="809" stroke="#ef4444" stroke-width="1.5"/>
  <text x="596" y="844" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND bus</text>
  <text x="924" y="844" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus</text>
  <path d="M 440 740 L 470 740 L 470 696 L 544 696" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 756 L 478 756 L 478 734 L 544 734" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 808 L 500 808 L 500 744 L 544 744" fill="none" stroke="#4b5563" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="320" y="864" width="200" height="40" rx="4" fill="#0a0a0f" stroke="#eab308" stroke-width="0.8" stroke-dasharray="3,2"/>
  <text x="328" y="877" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">COMMON GROUND</text>
  <text x="328" y="889" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">ESP32 GND → J1 − → GND bus</text>
  <line x1="976" y1="695" x2="1180" y2="695" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="706" x2="1180" y2="706" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="684" width="390" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="697" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">White 6500K LED strip — JOYLIT 5 m roll, cut to closet length</text>
  <text x="1190" y="710" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">red → J2 +, black → J2 − (18 AWG red/black pair)</text>
  <line x1="976" y1="733" x2="1180" y2="733" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="744" x2="1180" y2="744" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="724" width="390" height="100" rx="4" fill="#1e293b" stroke="#93c5fd" stroke-width="1"/>
  <text x="1192" y="736" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">common wire → +12 V (J2 +)</text>
  <text x="1192" y="747" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">BLUE wire (450 nm) → J2 − of CH1</text>
  <line x1="1180" y1="760" x2="1200" y2="760" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <rect x="1198" y="756" width="6" height="8" rx="1" fill="#6b7280"/>
  <text x="1210" y="763" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">RED wire (660 nm) — insulated with heat-shrink for now</text>
  <line x1="1180" y1="774" x2="1200" y2="774" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1198" y="770" width="6" height="8" rx="1" fill="#6b7280"/>
  <text x="1210" y="777" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">GREEN wire (730 nm far-red) — insulated for now</text>
  <text x="1192" y="798" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Tri-spectrum strip, IP67 — one strip, one 4-wire lead</text>
  <text x="1192" y="812" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">SuperLightingLED p-7120 · cut to length · heat-shrink every joint</text>
  <rect x="1015" y="688" width="20" height="62" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1056" y="678" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG red/black pairs</text>

  <!-- ═══════ PI + SMART PLUGS ═══════ -->
  <rect x="122" y="937" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="942" x2="130" y2="950" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="942" x2="138" y2="950" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="946" x2="160" y2="946" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="932" width="130" height="28" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="944" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Pi 27 W USB-C PSU</text>
  <text x="221.0" y="955" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">official, 5.1 V 5 A</text>
  <path d="M 290 946 L 330 946" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="330" y="928" width="290" height="40" rx="6" fill="#1e293b" stroke="#34d399" stroke-width="1.5"/>
  <text x="475" y="945" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">Raspberry Pi 5 + Active Cooler (pi_case)</text>
  <text x="475" y="960" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Server · Mosquitto :1883 / :8883 TLS · Web UI :3001</text>
  <g>
  <rect x="640" y="932" width="340" height="18" rx="4" fill="#0f2418" stroke="#34d399" stroke-width="0.6"/>
  <text x="810.0" y="943.88" text-anchor="middle" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">MQTT over WiFi — no wires from the Pi to any node or plug</text>
  </g>
  <text x="640" y="965" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Plugs: User sp-3p, Topic = role, Full Topic tasmota/%topic%/%prefix%/ (required)</text>
  <rect x="122" y="967" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="972" x2="130" y2="980" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="972" x2="138" y2="980" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="965" width="144" height="22" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1"/>
  <text x="218" y="979" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota plug #1 · humidifier</text>
  <rect x="122" y="993" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="998" x2="130" y2="1006" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="998" x2="138" y2="1006" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="991" width="144" height="22" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1"/>
  <text x="218" y="1005" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota plug #2 · heat / cool</text>
  <line x1="290" y1="976" x2="1180" y2="976" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="1015" y="966" width="20" height="20" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <rect x="1180" y="962" width="300" height="30" rx="4" fill="#1e293b" stroke="#fdba74" stroke-width="1"/>
  <text x="1190" y="975" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Ultrasonic humidifier (or piped in)</text>
  <text x="1190" y="987" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">plug-humidifier (Topic humidifier)</text>
  <line x1="290" y1="1002" x2="690" y2="1002" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="690" y="986" width="300" height="34" rx="4" fill="#1e293b" stroke="#fdba74" stroke-width="1"/>
  <text x="700" y="999" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Space heater ≤ 1500 W, outside, aimed at the intake</text>
  <text x="700" y="1012" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">or a Peltier cooler at the wall (Topic heater / cooler)</text>

  <!-- ═══════ CAMERA + CLIMATE NODE (inside) ═══════ -->
  <rect x="1100" y="114" width="470" height="36" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1.2"/>
  <rect x="1096" y="126" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="1112" y="129" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · cam_mount</text>
  <text x="1112" y="142" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cam-01 · no GPIO wiring · flash LED (GPIO 4) · 15-30 cm from the substrate</text>
  <rect x="1062" y="160" width="110" height="110" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1117.0" y="177" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="1117.0" y="191" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">climate-01</text>
  <text x="1117.0" y="204" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <text x="1164" y="215" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">3V3</text>
  <circle cx="1172" cy="212" r="3.5" fill="#ef4444"/>
  <text x="1164" y="231" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="1172" cy="228" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <text x="1164" y="247" text-anchor="end" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 21</text>
  <circle cx="1172" cy="244" r="3.5" fill="#3b82f6"/>
  <text x="1164" y="263" text-anchor="end" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 22</text>
  <circle cx="1172" cy="260" r="3.5" fill="#eab308"/>
  <rect x="1058" y="170" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 1172 212 L 1196 212 L 1196 200 L 1250 200" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 228 L 1206 228 L 1206 210 L 1250 210" fill="none" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 244 L 1216 244 L 1216 220 L 1250 220" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 260 L 1226 260 L 1226 230 L 1250 230" fill="none" stroke="#eab308" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="1250" y="186" width="96" height="56" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1298" y="204" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SHT31-D</text>
  <text x="1298" y="218" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Temp + RH · 0x44</text>
  <text x="1298" y="233" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1362" y="186" width="96" height="56" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1410" y="204" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SCD41</text>
  <text x="1410" y="218" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">CO2 · 0x62</text>
  <text x="1410" y="233" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1474" y="186" width="96" height="56" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1522" y="204" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">BH1750</text>
  <text x="1522" y="218" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Light · 0x23</text>
  <text x="1522" y="233" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <line x1="1346" y1="205" x2="1362" y2="205" stroke="#ef4444" stroke-width="2"/>
  <line x1="1346" y1="211" x2="1362" y2="211" stroke="#4b5563" stroke-width="2"/>
  <line x1="1346" y1="217" x2="1362" y2="217" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1346" y1="223" x2="1362" y2="223" stroke="#eab308" stroke-width="2"/>
  <text x="1354" y="182" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <line x1="1458" y1="205" x2="1474" y2="205" stroke="#ef4444" stroke-width="2"/>
  <line x1="1458" y1="211" x2="1474" y2="211" stroke="#4b5563" stroke-width="2"/>
  <line x1="1458" y1="217" x2="1474" y2="217" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1458" y1="223" x2="1474" y2="223" stroke="#eab308" stroke-width="2"/>
  <text x="1466" y="182" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <text x="1222" y="194" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4397</text>
  <text x="1250" y="254" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">QT chain, not a star: 4397 → SHT31-D, 4210 → SCD41, 4210 → BH1750</text>
  <text x="1250" y="266" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">sensor_mount + sensor_bracket: chamber centre, substrate level</text>

  <!-- ═══════ ONE CHANNEL, END TO END ═══════ -->
  <rect x="16" y="1044" width="988" height="262" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="30" y="1066" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">One switch-board channel, end to end — CH0 (FAE fan) on relay_board_mount</text>
  <text x="30" y="1081" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">Every relay and lighting channel is this circuit; the lighting board leaves out the UF4007 and feeds a strip instead of a fan.</text>
  <rect x="30" y="1096" width="90" height="178" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="75" y="1176" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12V 5A</text>
  <text x="75" y="1190" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">PSU</text>
  <text x="112" y="1110" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">+</text>
  <text x="112" y="1266" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="120" y1="1106" x2="180" y2="1106" stroke="#ef4444" stroke-width="3.5" stroke-linecap="round"/>
  <line x1="120" y1="1262" x2="180" y2="1262" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round"/>
  <text x="150" y="1100" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">14 AWG</text>
  <text x="150" y="1256" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">14 AWG</text>
  <rect x="180" y="1096" width="60" height="20" rx="3" fill="#1e293b" stroke="#ef4444" stroke-width="1.2"/>
  <text x="210" y="1109" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">221-413 +12V</text>
  <rect x="180" y="1252" width="60" height="20" rx="3" fill="#1e293b" stroke="#9ca3af" stroke-width="1.2"/>
  <text x="210" y="1265" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">221-415 GND</text>
  <line x1="240" y1="1106" x2="290" y2="1106" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <text x="265" y="1100" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG</text>
  <rect x="290" y="1098" width="46" height="16" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="294" y1="1106.0" x2="332" y2="1106.0" stroke="#fca5a5" stroke-width="1"/>
  <text x="313.0" y="1094" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">3 A fuse</text>
  <line x1="336" y1="1106" x2="690" y2="1106" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <text x="520" y="1100" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus → J2 +</text>
  <rect x="690" y="1094" width="34" height="90" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="707" y="1090" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">J2</text>
  <text x="707" y="1110" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">+</text>
  <text x="707" y="1174" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="724" y1="1106" x2="850" y2="1106" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="724" y1="1170" x2="850" y2="1170" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
  <text x="787" y="1100" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">+12 V wire</text>
  <text x="787" y="1164" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8">GND wire</text>
  <text x="787" y="1140" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">4-pin PWM fan</text>
  <text x="787" y="1151" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">extension lead</text>
  <text x="787" y="1190" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">tach + PWM wires unused</text>
  <rect x="850" y="1092" width="140" height="92" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="920" y="1126" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">FAE fan</text>
  <text x="920" y="1141" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Noctua NF-A8 12 V</text>
  <text x="920" y="1155" text-anchor="middle" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="8">inside the chamber</text>
  <line x1="676" y1="1106" x2="676" y2="1170" stroke="#94a3b8" stroke-width="1.5"/>
  <path d="M 668 1152 L 684 1152 L 676 1138 Z" fill="#94a3b8"/>
  <line x1="668" y1="1136" x2="684" y2="1136" stroke="#e2e8f0" stroke-width="2"/>
  <circle cx="676" cy="1106" r="3" fill="#ef4444"/>
  <circle cx="676" cy="1170" r="3" fill="#22c55e"/>
  <text x="666" y="1136" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">UF4007</text>
  <text x="666" y="1147" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">band to +12 V</text>
  <rect x="560" y="1152" width="70" height="52" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1.5"/>
  <text x="595" y="1172" text-anchor="middle" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="700">IRLZ44N</text>
  <text x="566" y="1190" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">G</text>
  <text x="620" y="1174" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">D</text>
  <text x="591" y="1200" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">S</text>
  <line x1="630" y1="1170" x2="676" y2="1170" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="676" y1="1170" x2="690" y2="1170" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
  <text x="650" y="1164" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">drain</text>
  <line x1="595" y1="1204" x2="595" y2="1262" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="400" y="1166" width="40" height="58" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="420" y="1162" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">J1</text>
  <text x="420" y="1189" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">IN</text>
  <text x="420" y="1215" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="440" y1="1186" x2="470" y2="1186" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="470" y="1178" width="50" height="16" rx="3" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="495" y="1189" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">100R</text>
  <text x="495" y="1174" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">gate resistor</text>
  <line x1="520" y1="1186" x2="560" y2="1186" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <circle cx="540" cy="1186" r="3" fill="#22c55e"/>
  <line x1="540" y1="1186" x2="540" y2="1214" stroke="#94a3b8" stroke-width="1.5"/>
  <rect x="531" y="1214" width="18" height="30" rx="2" fill="#1e293b" stroke="#94a3b8" stroke-width="1"/>
  <text x="540" y="1232" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600" transform="rotate(-90 540 1232)">10K</text>
  <line x1="540" y1="1244" x2="540" y2="1262" stroke="#4b5563" stroke-width="1.5" stroke-linecap="round"/>
  <text x="527" y="1232" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">pull-down</text>
  <path d="M 440 1212 L 460 1212 L 460 1262" fill="none" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="240" y1="1262" x2="600" y2="1262" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round"/>
  <text x="300" y="1256" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG black → GND bus</text>
  <rect x="270" y="1138" width="90" height="88" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="315" y="1155" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">ESP32</text>
  <text x="315" y="1168" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">relay node</text>
  <text x="354" y="1189" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">GPIO 25</text>
  <text x="354" y="1215" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">GND</text>
  <circle cx="360" cy="1186" r="3.5" fill="#22c55e"/>
  <circle cx="360" cy="1212" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <line x1="360" y1="1186" x2="400" y2="1186" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <line x1="360" y1="1212" x2="400" y2="1212" stroke="#4b5563" stroke-width="3" stroke-linecap="round"/>
  <text x="380" y="1181" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7">Dupont</text>
  <line x1="250" y1="1200" x2="270" y2="1200" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round"/>
  <text x="258" y="1194" text-anchor="middle" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="7">USB</text>
  <rect x="356" y="1203" width="48" height="18" rx="3" fill="none" stroke="#eab308" stroke-width="1" stroke-dasharray="3,2"/>
  <g>
  <rect x="330" y="1228" width="100" height="14" rx="4" fill="#2a1f00" stroke="#eab308" stroke-width="0.6"/>
  <text x="380.0" y="1237.52" text-anchor="middle" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">COMMON GROUND</text>
  </g>
  <text x="30" y="1296" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">COMMON GROUND: ESP32 GND → J1 − → GND bus → WAGO 221-415 → PSU −. Leave it out and the gate has no reference — the channel never switches. Do it on both boards.</text>

  <!-- ═══════ LEGEND ═══════ -->
  <rect x="1046" y="1044" width="538" height="152" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="1060" y="1064" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">Legend</text>
  <line x1="1060" y1="1084" x2="1090" y2="1084" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1088" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="9">RED = +12 V (and 3V3 on the QT cable)</text>
  <line x1="1060" y1="1102" x2="1090" y2="1102" stroke="#1e1e1e" stroke-width="3" stroke-linecap="round"/>
  <rect x="1060" y="1100" width="30" height="4" rx="1" fill="none" stroke="#6b7280" stroke-width="0.5"/>
  <text x="1098" y="1106" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLACK = GND / 12 V −</text>
  <line x1="1060" y1="1120" x2="1090" y2="1120" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1124" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9">GREEN = GPIO signal / switched (drain) side</text>
  <line x1="1060" y1="1138" x2="1090" y2="1138" stroke="#3b82f6" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1142" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLUE = SDA, YELLOW = SCL (STEMMA QT)</text>
  <line x1="1321.0" y1="1084" x2="1351.0" y2="1084" stroke="#f97316" stroke-width="3" stroke-linecap="round"/>
  <text x="1359.0" y="1088" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="9">ORANGE = 120 V AC cord (power strip)</text>
  <line x1="1321.0" y1="1102" x2="1351.0" y2="1102" stroke="#22d3ee" stroke-width="3" stroke-linecap="round"/>
  <text x="1359.0" y="1106" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">CYAN = USB 5 V power cable</text>
  <line x1="1321.0" y1="1120" x2="1351.0" y2="1120" stroke="#34d399" stroke-width="2" stroke-linecap="round" stroke-dasharray="5,3"/>
  <text x="1359.0" y="1124" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="9">dashed = WiFi / MQTT, no wire</text>
  <rect x="1321.0" y="1132" width="30" height="12" rx="6.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1359.0" y="1142" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">= cable through the chamber wall</text>
  <text x="1060" y="1164" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">Wire: 14 AWG pigtail · 18 AWG red/black for every 12 V run · 22 AWG hookup wire or</text>
  <text x="1060" y="1178" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">Dupont for GPIO / GND → J1. Adhesive-lined heat-shrink on every splice; zip-tie every run.</text>
  <rect x="1046" y="1204" width="538" height="102" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1"/>
  <text x="1060" y="1224" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12 V branches and fuses (inline blade fuse on each +12 V branch)</text>
  <text x="1060" y="1242" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Relay board: 3 A — three NF-A8 fans draw ~0.25 A together.</text>
  <text x="1060" y="1257" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Lighting board: 5 A — the LED strips are the real load.</text>
  <text x="1060" y="1272" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">12V 5A PSU: keep the total ≤ ~4 A — cut the strips to closet length</text>
  <text x="1060" y="1287" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">(a full white roll alone is 3.3-4.2 A). GND branches are not fused.</text>

  <!-- ═══════ WIRING STEPS ═══════ -->
  <rect x="16" y="1316" width="1568" height="154" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="30" y="1338" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="700">Wiring Steps</text>
  <text x="30" y="1360" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">1 · Mains and 12 V (outside)</text>
  <text x="30" y="1378" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">12-outlet strip outside: Pi PSU, 12 V PSU, 4 chargers, 2 plugs.</text>
  <text x="30" y="1393" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">PSU barrel → 14 AWG pigtail → WAGO 221-413 (+12V) / 221-415 (GND).</text>
  <text x="30" y="1408" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-413 → inline 3 A fuse → relay +12 V bus (18 AWG red).</text>
  <text x="30" y="1423" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-413 → inline 5 A fuse → lighting +12 V bus (18 AWG red).</text>
  <text x="30" y="1438" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-415 → both boards' GND bus (18 AWG black).</text>
  <text x="420" y="1360" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">2 · Each switch channel (relay_board_mount)</text>
  <text x="420" y="1378" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">GPIO → Dupont jumper → J1 IN → 100R → IRLZ44N gate.</text>
  <text x="420" y="1393" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">10K from gate to source; source → GND bus.</text>
  <text x="420" y="1408" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Drain → J2 −; J2 + → +12 V bus.</text>
  <text x="420" y="1423" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">UF4007 across J2 on every relay channel, band to +12 V.</text>
  <text x="420" y="1438" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">ESP32 GND → J1 − on both boards: the COMMON GROUND.</text>
  <text x="810" y="1360" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">3 · Into the chamber (through the grommet)</text>
  <text x="810" y="1378" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Fans: NA-SEC3 extension, far end cut — GND → J2 −, +12 V → J2 +.</text>
  <text x="810" y="1393" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">FAE on CH0 (GPIO 25), exhaust CH1 (26), circulation CH2 (27).</text>
  <text x="810" y="1408" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Strips: 18 AWG red/black, red → J2 +, black → J2 −.</text>
  <text x="810" y="1423" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Tri-spectrum: BLUE wire → CH1 J2 −, common wire → +12 V.</text>
  <text x="810" y="1438" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Insulate its red + green wires; heat-shrink every joint.</text>
  <text x="1200" y="1360" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">4 · Climate, camera, plugs</text>
  <text x="1200" y="1378" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">4397: red 3V3, black GND, blue GPIO 21, yellow GPIO 22.</text>
  <text x="1200" y="1393" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">4397 QT plug → SHT31-D; 4210 → SCD41; 4210 → BH1750.</text>
  <text x="1200" y="1408" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Climate + camera: 6 ft (2 m) USB cables through the grommet.</text>
  <text x="1200" y="1423" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Relay + lighting ESP32s stay outside on short cables.</text>
  <text x="1200" y="1438" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Plugs: WiFi only — sp-3p + Full Topic (see the build guide).</text>
  <text x="1200" y="1462" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-style="italic">ESP32-S3 nodes use other pins (build guide §8a); S3 cameras: §8b.</text>

  <!-- ═══════════════════════ FOOTER ═══════════════════════ -->
  <text x="800" y="1486" text-anchor="middle" fill="#334155" font-family="system-ui, -apple-system, sans-serif" font-size="9">SporePrint  |  Tier 2: Recommended  |  github.com/59psi/SporePrint</text>

</svg>
`},all_the_things:{tierId:"all_the_things",filename:"wiring-tier3-all-the-things.svg",title:"Tier 3: All The Things Wiring Diagram",summary:"Tier 2 + 2nd climate node, 2nd camera, 4 LED channels, HX711 scale, door contact, peristaltic pump, 4 smart plugs · 12V 10A PSU, fused branches (3 A relay, 7.5 A lighting)",width:1600,height:1770,bytes:84583,sha256:"f1ea0c08c691d6d68a1cd9dfbe4bc318ba1e0da126d3d4fe0969d4f046272f24",svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1770" width="1600" height="1770">

  <!-- Background -->
  <rect width="1600" height="1770" fill="#0a0a0f"/>

  <!-- ═══════════════════════ TITLE ═══════════════════════ -->
  <text x="800" y="30" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="700">Tier 3: All The Things Wiring Diagram</text>
  <text x="800" y="50" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="11">Tier 2 + 2nd climate node, 2nd camera, 4 LED channels, HX711 scale, door contact, peristaltic pump, 4 smart plugs · 12V 10A PSU, fused branches (3 A relay, 7.5 A lighting)</text>

  <!-- ═══════ OUTSIDE THE CHAMBER (dry side) ═══════ -->
  <rect x="16" y="64" width="988" height="1218" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="32" y="86" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">OUTSIDE THE CHAMBER — the dry side</text>

  <!-- ═══════ CHAMBER WALL ═══════ -->
  <rect x="1012" y="64" width="26" height="1218" rx="4" fill="#1f2937" stroke="#64748b" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="1029" y="768" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" transform="rotate(-90 1029 768)">CHAMBER WALL — 7/8 in. grommet / tent cable port</text>

  <!-- ═══════ INSIDE THE GROW CHAMBER ═══════ -->
  <rect x="1046" y="64" width="538" height="1218" rx="6" fill="#0b1716" stroke="#2dd4bf" stroke-width="1.2" stroke-dasharray="6,4"/>
  <text x="1062" y="86" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">INSIDE THE GROW CHAMBER (85-95 % RH)</text>
  <text x="32" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">power strip, 12 V supply, chargers, Pi, smart plugs and both switch boards</text>
  <text x="1062" y="100" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">sensors, cameras, scale, door contact and 12 V loads only</text>

  <!-- Power strip (mains, outside the chamber) -->
  <rect x="28" y="112" width="112" height="1158" rx="8" fill="#1e293b" stroke="#f97316" stroke-width="1.5"/>
  <text x="84.0" y="132" text-anchor="middle" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700">Power strip</text>
  <text x="84.0" y="146" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">UL-listed surge</text>
  <text x="84.0" y="158" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">protector</text>
  <text x="84.0" y="170" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">12 + 2 USB-A</text>
  <text x="84.0" y="182" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">widely spaced</text>
  <text x="84.0" y="194" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">outlets</text>
  <text x="84.0" y="1248" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cord to a</text>
  <text x="84.0" y="1259" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">wall outlet</text>

  <!-- USB chargers for the four in-chamber boards (6 ft cables) -->
  <rect x="122" y="119" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="124" x2="130" y2="132" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="124" x2="138" y2="132" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="128" x2="160" y2="128" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="112" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="125" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="138" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft micro-USB → CAM-MB</text>
  <rect x="286" y="123" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="560" y="122" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → micro-USB, 6 ft (2 m) → cam-01's ESP32-CAM-MB</text>
  <rect x="122" y="159" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="164" x2="130" y2="172" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="164" x2="138" y2="172" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="168" x2="160" y2="168" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="152" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="165" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="178" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft micro-USB → CAM-MB</text>
  <rect x="286" y="163" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="560" y="162" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → micro-USB, 6 ft (2 m) → cam-02's ESP32-CAM-MB</text>
  <rect x="122" y="201" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="206" x2="130" y2="214" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="206" x2="138" y2="214" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="210" x2="160" y2="210" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="194" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="207" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="220" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft USB-C → climate-01</text>
  <rect x="286" y="205" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="560" y="204" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → USB-C, 6 ft (2 m) → climate-01 (shelf A)</text>
  <rect x="122" y="241" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="246" x2="130" y2="254" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="246" x2="138" y2="254" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="250" x2="160" y2="250" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="234" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="247" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="260" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">6 ft USB-C → climate-02</text>
  <rect x="286" y="245" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="560" y="244" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">USB-A → USB-C, 6 ft (2 m) → climate-02 (shelf B)</text>
  <path d="M 294 128 L 1096 128" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 294 168 L 1096 168" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 294 210 L 1058 210" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 294 250 L 1050 250 L 1050 322 L 1058 322" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="1015" y="116" width="20" height="146" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>

  <!-- ═══════ CAMERAS + CLIMATE NODES (inside) ═══════ -->
  <rect x="1100" y="112" width="470" height="34" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1.2"/>
  <rect x="1096" y="122" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="1112" y="127" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">cam-01 · ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · front view</text>
  <text x="1112" y="140" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cam_mount · no GPIO wiring · flash LED (GPIO 4) · substrate level, angled slightly up</text>
  <rect x="1100" y="152" width="470" height="34" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1.2"/>
  <rect x="1096" y="162" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <text x="1112" y="167" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">cam-02 · ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · top-down</text>
  <text x="1112" y="180" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cam_mount · looking straight down, 15-30 cm from the substrate</text>
  <g>
  <rect x="1474" y="170" width="92" height="15" rx="4" fill="#2e1065" stroke="#a78bfa" stroke-width="0.6"/>
  <text x="1520.0" y="180.02" text-anchor="middle" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">NEW IN TIER 3</text>
  </g>
  <rect x="1062" y="194" width="110" height="104" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1117.0" y="211" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="1117.0" y="225" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">climate-01</text>
  <text x="1117.0" y="238" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">shelf A</text>
  <text x="1164" y="241" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">3V3</text>
  <circle cx="1172" cy="238" r="3.5" fill="#ef4444"/>
  <text x="1164" y="255" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="1172" cy="252" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <text x="1164" y="269" text-anchor="end" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 21</text>
  <circle cx="1172" cy="266" r="3.5" fill="#3b82f6"/>
  <text x="1164" y="283" text-anchor="end" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 22</text>
  <circle cx="1172" cy="280" r="3.5" fill="#eab308"/>
  <rect x="1058" y="204" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 1172 238 L 1196 238 L 1196 226 L 1250 226" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 252 L 1206 252 L 1206 234 L 1250 234" fill="none" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 266 L 1216 266 L 1216 242 L 1250 242" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 280 L 1226 280 L 1226 250 L 1250 250" fill="none" stroke="#eab308" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="1222" y="220" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4397</text>
  <rect x="1250" y="214" width="96" height="50" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1298" y="231" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SHT31-D</text>
  <text x="1298" y="244" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Temp + RH · 0x44</text>
  <text x="1298" y="257" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1362" y="214" width="96" height="50" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1410" y="231" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SCD41</text>
  <text x="1410" y="244" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">CO2 · 0x62</text>
  <text x="1410" y="257" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1474" y="214" width="96" height="50" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1522" y="231" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">BH1750</text>
  <text x="1522" y="244" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Light · 0x23</text>
  <text x="1522" y="257" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <line x1="1346" y1="230" x2="1362" y2="230" stroke="#ef4444" stroke-width="2"/>
  <line x1="1346" y1="236" x2="1362" y2="236" stroke="#4b5563" stroke-width="2"/>
  <line x1="1346" y1="242" x2="1362" y2="242" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1346" y1="248" x2="1362" y2="248" stroke="#eab308" stroke-width="2"/>
  <text x="1354" y="210" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <line x1="1458" y1="230" x2="1474" y2="230" stroke="#ef4444" stroke-width="2"/>
  <line x1="1458" y1="236" x2="1474" y2="236" stroke="#4b5563" stroke-width="2"/>
  <line x1="1458" y1="242" x2="1474" y2="242" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1458" y1="248" x2="1474" y2="248" stroke="#eab308" stroke-width="2"/>
  <text x="1466" y="210" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <text x="1250" y="278" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">4397 → SHT31-D, 4210 → SCD41, 4210 → BH1750 · sensor_mount, substrate level</text>
  <rect x="1062" y="306" width="110" height="104" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="1117.0" y="323" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="1117.0" y="337" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">climate-02</text>
  <text x="1117.0" y="350" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">shelf B</text>
  <text x="1164" y="353" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">3V3</text>
  <circle cx="1172" cy="350" r="3.5" fill="#ef4444"/>
  <text x="1164" y="367" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="1172" cy="364" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <text x="1164" y="381" text-anchor="end" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 21</text>
  <circle cx="1172" cy="378" r="3.5" fill="#3b82f6"/>
  <text x="1164" y="395" text-anchor="end" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 22</text>
  <circle cx="1172" cy="392" r="3.5" fill="#eab308"/>
  <rect x="1058" y="316" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 1172 350 L 1196 350 L 1196 338 L 1250 338" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 364 L 1206 364 L 1206 346 L 1250 346" fill="none" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 378 L 1216 378 L 1216 354 L 1250 354" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 1172 392 L 1226 392 L 1226 362 L 1250 362" fill="none" stroke="#eab308" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="1222" y="332" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4397</text>
  <rect x="1250" y="326" width="96" height="50" rx="6" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="1298" y="343" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SHT31-D</text>
  <text x="1298" y="356" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Temp + RH · 0x44</text>
  <text x="1298" y="369" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1362" y="326" width="96" height="50" rx="6" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="1410" y="343" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">SCD41</text>
  <text x="1410" y="356" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">CO2 · 0x62</text>
  <text x="1410" y="369" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <rect x="1474" y="326" width="96" height="50" rx="6" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="1522" y="343" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">BH1750</text>
  <text x="1522" y="356" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Light · 0x23</text>
  <text x="1522" y="369" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">STEMMA QT ×2</text>
  <line x1="1346" y1="342" x2="1362" y2="342" stroke="#ef4444" stroke-width="2"/>
  <line x1="1346" y1="348" x2="1362" y2="348" stroke="#4b5563" stroke-width="2"/>
  <line x1="1346" y1="354" x2="1362" y2="354" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1346" y1="360" x2="1362" y2="360" stroke="#eab308" stroke-width="2"/>
  <text x="1354" y="322" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <line x1="1458" y1="342" x2="1474" y2="342" stroke="#ef4444" stroke-width="2"/>
  <line x1="1458" y1="348" x2="1474" y2="348" stroke="#4b5563" stroke-width="2"/>
  <line x1="1458" y1="354" x2="1474" y2="354" stroke="#3b82f6" stroke-width="2"/>
  <line x1="1458" y1="360" x2="1474" y2="360" stroke="#eab308" stroke-width="2"/>
  <text x="1466" y="322" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">4210</text>
  <text x="1250" y="390" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">4397 → SHT31-D, 4210 → SCD41, 4210 → BH1750 · sensor_mount, substrate level</text>
  <g>
  <rect x="1474" y="296" width="92" height="15" rx="4" fill="#2e1065" stroke="#a78bfa" stroke-width="0.6"/>
  <text x="1520.0" y="306.02" text-anchor="middle" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">NEW IN TIER 3</text>
  </g>

  <!-- ═══════ RELAY NODE (outside) + HX711 / reed runs ═══════ -->
  <rect x="304" y="384" width="692" height="332" rx="6" fill="#0f1623" stroke="#475569" stroke-width="1"/>
  <text x="318" y="402" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Relay node</text>
  <text x="392" y="402" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay_board_mount, node="relay" — 4 switch channels (UF4007 on each) + HX711 + door contact</text>
  <rect x="122" y="431" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="436" x2="130" y2="444" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="436" x2="138" y2="444" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="440" x2="160" y2="440" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="424" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="437" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="450" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">1 ft USB-C → relay</text>
  <rect x="286" y="435" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <rect x="320" y="412" width="130" height="248" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="385.0" y="429" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="385.0" y="443" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay-01</text>
  <text x="385.0" y="456" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <text x="442" y="473" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="450" cy="470" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <text x="442" y="489" text-anchor="end" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 32 HX DOUT</text>
  <circle cx="450" cy="486" r="3.5" fill="#a78bfa"/>
  <text x="442" y="505" text-anchor="end" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 33 HX SCK</text>
  <circle cx="450" cy="502" r="3.5" fill="#a78bfa"/>
  <text x="442" y="521" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">3V3</text>
  <circle cx="450" cy="518" r="3.5" fill="#ef4444"/>
  <text x="442" y="537" text-anchor="end" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 35 reed</text>
  <circle cx="450" cy="534" r="3.5" fill="#a78bfa"/>
  <text x="442" y="553" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="450" cy="550" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <text x="442" y="581" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 25</text>
  <circle cx="450" cy="578" r="3.5" fill="#22c55e"/>
  <text x="442" y="597" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 26</text>
  <circle cx="450" cy="594" r="3.5" fill="#22c55e"/>
  <text x="442" y="613" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 27</text>
  <circle cx="450" cy="610" r="3.5" fill="#22c55e"/>
  <text x="442" y="629" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 14</text>
  <circle cx="450" cy="626" r="3.5" fill="#22c55e"/>
  <text x="442" y="649" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="450" cy="646" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <rect x="316" y="434" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 294 440 L 316 440" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 470 L 456 470 L 456 414 L 1180 414" fill="none" stroke="#4b5563" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 486 L 462 486 L 462 418 L 1180 418" fill="none" stroke="#a78bfa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 502 L 468 502 L 468 422 L 1180 422" fill="none" stroke="#a78bfa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 518 L 474 518 L 474 426 L 1180 426" fill="none" stroke="#ef4444" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 534 L 494 534 L 494 446 L 1180 446" fill="none" stroke="#a78bfa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 550 L 500 550 L 500 450 L 1180 450" fill="none" stroke="#4b5563" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="520" y1="426" x2="520" y2="431" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="516" y="431" width="8" height="10" rx="1" fill="#1e293b" stroke="#d1d5db" stroke-width="1"/>
  <line x1="520" y1="441" x2="520" y2="446" stroke="#a78bfa" stroke-width="1.5"/>
  <circle cx="520" cy="426" r="2.2" fill="#ef4444"/>
  <circle cx="520" cy="446" r="2.2" fill="#a78bfa"/>
  <text x="528" y="439" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">10K pull-up</text>
  <text x="590" y="437" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8">↑ 22 AWG 4-conductor → HX711: red 3V3 → VCC, black GND, yellow DOUT → 32, white SCK → 33</text>
  <text x="590" y="461" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8">↑ second 22 AWG 4-conductor run (2 used) → door contact: COM → GPIO 35, alarm NC → GND</text>
  <rect x="540" y="466" width="440" height="200" rx="4" fill="#16202f" stroke="#64748b" stroke-width="1.2"/>
  <text x="760.0" y="481" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">IRLZ44N switch board (relay_board_mount)</text>
  <line x1="590" y1="492" x2="590" y2="666" stroke="#4b5563" stroke-width="3.5"/>
  <line x1="930" y1="492" x2="930" y2="666" stroke="#ef4444" stroke-width="3.5"/>
  <rect x="544" y="493" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="504" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="515" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="512" x2="590" y2="512" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="504" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH0 fae — FAE fan (GPIO 25)</text>
  <text x="598" y="516" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">100R gate · 10K pull-down · IRLZ44N · UF4007 across J2</text>
  <rect x="938" y="493" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="504" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="515" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="501" x2="938" y2="501" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="531" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="542" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="553" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="550" x2="590" y2="550" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="542" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH1 exhaust — exhaust fan (GPIO 26)</text>
  <text x="598" y="554" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="531" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="542" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="553" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="539" x2="938" y2="539" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="569" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="580" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="591" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="588" x2="590" y2="588" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="580" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH2 circulation — circulation fan (GPIO 27)</text>
  <text x="598" y="592" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="569" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="580" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="591" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="577" x2="938" y2="577" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="607" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="618" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="629" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="626" x2="590" y2="626" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="618" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH3 aux — peristaltic pump (GPIO 14)</text>
  <text x="598" y="630" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">UF4007 across the pump · 60 s max-on</text>
  <rect x="938" y="607" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="618" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="629" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="615" x2="938" y2="615" stroke="#ef4444" stroke-width="1.5"/>
  <text x="596" y="660" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND bus</text>
  <text x="924" y="660" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus</text>
  <path d="M 450 578 L 512 578 L 512 502 L 544 502" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 594 L 518 594 L 518 540 L 544 540" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 610 L 524 610 L 524 578 L 544 578" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 626 L 530 626 L 530 616 L 544 616" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 450 646 L 470 646 L 470 674 L 536 674 L 536 626 L 544 626" fill="none" stroke="#4b5563" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="604" y="674" width="220" height="34" rx="4" fill="#0a0a0f" stroke="#eab308" stroke-width="0.8" stroke-dasharray="3,2"/>
  <text x="612" y="687" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">COMMON GROUND</text>
  <text x="612" y="699" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">ESP32 GND → J1 − → GND bus (both boards)</text>
  <line x1="976" y1="501" x2="1180" y2="501" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="512" x2="1180" y2="512" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="490" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="503" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">FAE fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="516" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">fresh-air intake at the wall · fan_duct</text>
  <line x1="976" y1="539" x2="1180" y2="539" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="550" x2="1180" y2="550" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="528" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="541" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Exhaust fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="554" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">exhaust at the wall · fan_duct</text>
  <line x1="976" y1="577" x2="1180" y2="577" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="588" x2="1180" y2="588" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="566" width="300" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="579" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Circulation fan — Noctua NF-A8 12 V</text>
  <text x="1190" y="592" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">inside, away from the sensors</text>
  <line x1="976" y1="615" x2="1180" y2="615" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="626" x2="1180" y2="626" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="604" width="390" height="32" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1.2"/>
  <text x="1190" y="617" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Peristaltic pump — Adafruit 1150 12 V, in pump_bracket (new in Tier 3)</text>
  <text x="1190" y="630" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG red/black leads · food-grade silicone tubing (2 × 4 mm) to the substrate</text>
  <rect x="1015" y="406" width="20" height="226" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1056" y="652" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Fans: bundled 30 cm extension + Noctua NA-SEC3 (cut its far end): GND → J2 −, +12 V → J2 +</text>
  <text x="1056" y="664" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">by pin position, not colour; tach + PWM unused. Pump: 18 AWG red/black, red → J2 +, black → J2 −.</text>
  <rect x="1180" y="406" width="390" height="30" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1.2"/>
  <text x="1190" y="418" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">HX711 (Adafruit 5974) + 5 kg cell (4541) in hx711_scale, under the grow block</text>
  <text x="1190" y="430" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">22/4 cable: red VCC · black GND · yellow DOUT · white SCK · cell red E+, black E− · 10 SPS</text>
  <rect x="1180" y="440" width="390" height="34" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1.2"/>
  <text x="1190" y="453" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Door contact (weideer MC-31B) on the door frame, magnet on the door</text>
  <text x="1190" y="466" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">COM → GPIO 35, alarm NC → GND (closed = door shut) · wired on NO? tick invert (reed_inv)</text>

  <!-- ═══════ 12 V DISTRIBUTION: PSU → pigtail → WAGO → fuses ═══════ -->
  <rect x="122" y="769" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="774" x2="130" y2="782" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="774" x2="138" y2="782" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="778" x2="160" y2="778" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="736" width="130" height="84" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="225.0" y="754" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12V 10A PSU (120W)</text>
  <text x="225.0" y="768" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Facmogu AL-12100</text>
  <text x="225.0" y="781" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">power_supply_mount</text>
  <text x="225.0" y="794" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">5.5 × 2.5 mm barrel</text>
  <text x="225.0" y="807" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">load ≤ ~8 A</text>
  <rect x="290" y="766" width="10" height="22" rx="2" fill="#0a0a0f" stroke="#94a3b8" stroke-width="0.8"/>
  <path d="M 300 782 L 546 782" fill="none" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 300 772 L 330 772 L 330 740 L 584 740 A 6 6 0 0 1 596 740 L 866 740 L 866 768 L 886 768" fill="none" stroke="#ef4444" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="318" y="804" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">5.5 × 2.5 mm DC barrel pigtail — 14 AWG</text>
  <rect x="546" y="760" width="88" height="24" rx="3" fill="#1e293b" stroke="#9ca3af" stroke-width="1.2"/>
  <text x="590" y="775" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">WAGO 221-415 GND</text>
  <rect x="886" y="760" width="88" height="24" rx="3" fill="#1e293b" stroke="#ef4444" stroke-width="1.2"/>
  <text x="930" y="775" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">WAGO 221-413 +12V</text>
  <line x1="590" y1="760" x2="590" y2="666" stroke="#4b5563" stroke-width="3"/>
  <line x1="930" y1="760" x2="930" y2="666" stroke="#ef4444" stroke-width="3"/>
  <rect x="923" y="716" width="14" height="28" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="930.0" y1="720" x2="930.0" y2="740" stroke="#fca5a5" stroke-width="1"/>
  <text x="930.0" y="712" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700"></text>
  <text x="916" y="729" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">3 A fuse</text>
  <text x="916" y="740" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">relay branch</text>
  <line x1="590" y1="784" x2="590" y2="868" stroke="#4b5563" stroke-width="3"/>
  <line x1="930" y1="784" x2="930" y2="868" stroke="#ef4444" stroke-width="3"/>
  <rect x="923" y="804" width="14" height="28" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="930.0" y1="808" x2="930.0" y2="828" stroke="#fca5a5" stroke-width="1"/>
  <text x="930.0" y="800" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700"></text>
  <text x="916" y="817" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">7.5 A fuse</text>
  <text x="916" y="828" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">lighting branch</text>
  <text x="604" y="816" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">branches: 18 AWG red (+12 V, fused)</text>
  <text x="604" y="828" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">and black (GND, not fused)</text>

  <!-- ═══════ LIGHTING NODE (outside), 4 channels ═══════ -->
  <rect x="304" y="842" width="692" height="290" rx="6" fill="#0f1623" stroke="#475569" stroke-width="1"/>
  <text x="318" y="862" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">Lighting node</text>
  <text x="318" y="876" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">relay_board_mount, node="lighting" (PETG)</text>
  <text x="318" y="888" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">no diodes — LED strips are resistive</text>
  <rect x="122" y="917" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="922" x2="130" y2="930" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="922" x2="138" y2="930" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="926" x2="160" y2="926" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="910" width="130" height="32" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="923" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">5 V USB charger</text>
  <text x="221.0" y="936" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">1 ft USB-C → lighting</text>
  <rect x="286" y="921" width="8" height="10" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <rect x="320" y="900" width="120" height="140" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="380.0" y="917" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">ESP32</text>
  <text x="380.0" y="931" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">lighting-01</text>
  <text x="380.0" y="944" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">esp32_case</text>
  <text x="432" y="959" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 25</text>
  <circle cx="440" cy="956" r="3.5" fill="#22c55e"/>
  <text x="432" y="975" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 26</text>
  <circle cx="440" cy="972" r="3.5" fill="#22c55e"/>
  <text x="432" y="991" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 27</text>
  <circle cx="440" cy="988" r="3.5" fill="#22c55e"/>
  <text x="432" y="1007" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GPIO 14</text>
  <circle cx="440" cy="1004" r="3.5" fill="#22c55e"/>
  <text x="432" y="1027" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND</text>
  <circle cx="440" cy="1024" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <rect x="316" y="920" width="8" height="12" rx="1" fill="#0a0a0f" stroke="#67e8f9" stroke-width="0.8"/>
  <path d="M 294 926 L 316 926" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="540" y="868" width="440" height="196" rx="4" fill="#16202f" stroke="#64748b" stroke-width="1.2"/>
  <text x="760.0" y="883" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">IRLZ44N switch board (relay_board_mount)</text>
  <line x1="590" y1="868" x2="590" y2="1050" stroke="#4b5563" stroke-width="3.5"/>
  <line x1="930" y1="868" x2="930" y2="1050" stroke="#ef4444" stroke-width="3.5"/>
  <rect x="544" y="903" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="914" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="925" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="922" x2="590" y2="922" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="914" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH0 white — 6500K strip (GPIO 25)</text>
  <text x="598" y="926" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">100R gate · 10K pull-down · IRLZ44N · no diode</text>
  <rect x="938" y="903" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="914" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="925" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="911" x2="938" y2="911" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="941" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="952" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="963" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="960" x2="590" y2="960" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="952" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH1 blue — tri-spectrum BLUE wire (GPIO 26)</text>
  <text x="598" y="964" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="941" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="952" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="963" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="949" x2="938" y2="949" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="979" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="990" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="1001" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="998" x2="590" y2="998" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="990" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH2 red — tri-spectrum RED wire (GPIO 27)</text>
  <text x="598" y="1002" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit</text>
  <rect x="938" y="979" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="990" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="1001" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="987" x2="938" y2="987" stroke="#ef4444" stroke-width="1.5"/>
  <rect x="544" y="1017" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="563" y="1028" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 IN</text>
  <text x="563" y="1039" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J1 −</text>
  <line x1="582" y1="1036" x2="590" y2="1036" stroke="#4b5563" stroke-width="1.5"/>
  <text x="598" y="1028" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">CH3 far_red — tri-spectrum GREEN wire (GPIO 14)</text>
  <text x="598" y="1040" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">same circuit (green = 730 nm)</text>
  <rect x="938" y="1017" width="38" height="26" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="957" y="1028" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 +</text>
  <text x="957" y="1039" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">J2 −</text>
  <line x1="930" y1="1025" x2="938" y2="1025" stroke="#ef4444" stroke-width="1.5"/>
  <text x="596" y="1058" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GND bus</text>
  <text x="924" y="1058" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus</text>
  <path d="M 440 956 L 470 956 L 470 912 L 544 912" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 972 L 478 972 L 478 950 L 544 950" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 988 L 544 988" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 1004 L 494 1004 L 494 1026 L 544 1026" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 440 1024 L 462 1024 L 462 1050 L 520 1050 L 520 1036 L 544 1036" fill="none" stroke="#4b5563" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="320" y="1076" width="200" height="40" rx="4" fill="#0a0a0f" stroke="#eab308" stroke-width="0.8" stroke-dasharray="3,2"/>
  <text x="328" y="1089" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">COMMON GROUND</text>
  <text x="328" y="1101" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">ESP32 GND → J1 − → GND bus</text>
  <line x1="976" y1="911" x2="1180" y2="911" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="922" x2="1180" y2="922" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="900" width="390" height="32" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="1190" y="913" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">White 6500K LED strip — JOYLIT 5 m roll, cut to closet length</text>
  <text x="1190" y="926" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">red → J2 +, black → J2 − (18 AWG red/black pair)</text>
  <line x1="976" y1="949" x2="1180" y2="949" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="960" x2="1180" y2="960" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="998" x2="1180" y2="998" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <line x1="976" y1="1036" x2="1180" y2="1036" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="1180" y="940" width="390" height="132" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1.2"/>
  <text x="1192" y="952" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">common wire → +12 V (CH1 J2 +)</text>
  <text x="1192" y="963" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">BLUE wire (450 nm) → CH1 J2 −</text>
  <text x="1192" y="1001" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">RED wire (660 nm) → CH2 J2 −</text>
  <text x="1192" y="1039" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">GREEN wire (730 nm far-red) → CH3 J2 −</text>
  <text x="1400" y="984" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Tri-spectrum strip, IP67</text>
  <text x="1400" y="998" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">one strip, three channels</text>
  <text x="1400" y="1012" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">SuperLightingLED p-7120</text>
  <text x="1400" y="1026" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">cut to length · heat-shrink</text>
  <text x="1400" y="1038" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">every joint</text>
  <rect x="1015" y="904" width="20" height="140" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1056" y="894" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG red/black pairs</text>

  <!-- ═══════ PI + 4 SMART PLUGS ═══════ -->
  <rect x="122" y="1141" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="1146" x2="130" y2="1154" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="1146" x2="138" y2="1154" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="146" y1="1150" x2="160" y2="1150" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="160" y="1136" width="130" height="28" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="221.0" y="1148" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Pi 27 W USB-C PSU</text>
  <text x="221.0" y="1159" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">official, 5.1 V 5 A</text>
  <path d="M 290 1150 L 330 1150" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="330" y="1132" width="290" height="40" rx="6" fill="#1e293b" stroke="#34d399" stroke-width="1.5"/>
  <text x="475" y="1149" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">Raspberry Pi 5 + Active Cooler (pi_case)</text>
  <text x="475" y="1164" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Server · Mosquitto :1883 / :8883 TLS · Web UI :3001</text>
  <g>
  <rect x="640" y="1136" width="340" height="18" rx="4" fill="#0f2418" stroke="#34d399" stroke-width="0.6"/>
  <text x="810.0" y="1147.88" text-anchor="middle" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">MQTT over WiFi — no wires from the Pi to any node or plug</text>
  </g>
  <text x="640" y="1168" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Plugs: User sp-3p, Topic = role, Full Topic tasmota/%topic%/%prefix%/ (required)</text>
  <rect x="122" y="1173" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="1178" x2="130" y2="1186" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="1178" x2="138" y2="1186" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="1171" width="144" height="22" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1"/>
  <text x="218" y="1185" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota #1 · humidifier</text>
  <rect x="122" y="1199" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="1204" x2="130" y2="1212" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="1204" x2="138" y2="1212" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="1197" width="144" height="22" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1"/>
  <text x="218" y="1211" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota #2 · dehumidifier</text>
  <rect x="122" y="1225" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="1230" x2="130" y2="1238" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="1230" x2="138" y2="1238" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="1223" width="144" height="22" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1"/>
  <text x="218" y="1237" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota #3 · heater</text>
  <rect x="122" y="1251" width="24" height="18" rx="3" fill="#0a0a0f" stroke="#fdba74" stroke-width="0.8"/>
  <line x1="130" y1="1256" x2="130" y2="1264" stroke="#fdba74" stroke-width="1.4"/>
  <line x1="138" y1="1256" x2="138" y2="1264" stroke="#fdba74" stroke-width="1.4"/>
  <rect x="146" y="1249" width="144" height="22" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1"/>
  <text x="218" y="1263" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Tasmota #4 · cooler</text>
  <line x1="290" y1="1182" x2="1180" y2="1182" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="1180" y="1168" width="390" height="28" rx="4" fill="#1e293b" stroke="#fdba74" stroke-width="1"/>
  <text x="1190" y="1180" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Ultrasonic humidifier (or piped in)</text>
  <text x="1190" y="1191" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">plug-humidifier (Topic humidifier)</text>
  <line x1="290" y1="1208" x2="640" y2="1208" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="640" y="1196" width="176" height="24" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1"/>
  <text x="648" y="1206" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Dehumidifier (outside)</text>
  <text x="648" y="1216" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">intake facing the chamber</text>
  <line x1="290" y1="1234" x2="822" y2="1234" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="822" y="1222" width="176" height="24" rx="4" fill="#1e293b" stroke="#fdba74" stroke-width="1"/>
  <text x="830" y="1232" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">Space heater ≤ 1500 W (outside)</text>
  <text x="830" y="1242" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">aimed at the intake</text>
  <line x1="290" y1="1260" x2="1180" y2="1260" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="1180" y="1246" width="390" height="28" rx="4" fill="#1e293b" stroke="#a78bfa" stroke-width="1"/>
  <text x="1190" y="1258" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">Peltier cooler at the chamber wall</text>
  <text x="1190" y="1269" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="8">plug-cooler (Topic cooler) · plugs #2 + #4 are new in Tier 3</text>
  <rect x="1015" y="1172" width="20" height="20" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <rect x="1015" y="1250" width="20" height="20" rx="10.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>

  <!-- ═══════ ONE CHANNEL, END TO END ═══════ -->
  <rect x="16" y="1296" width="988" height="262" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="30" y="1318" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700">One switch-board channel, end to end — CH3 aux (peristaltic pump) on relay_board_mount</text>
  <text x="30" y="1333" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">Every relay and lighting channel is this circuit; fans use a 4-pin PWM extension lead instead, and the lighting board leaves out the UF4007.</text>
  <rect x="30" y="1348" width="90" height="178" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="75" y="1428" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12V 10A</text>
  <text x="75" y="1442" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">PSU</text>
  <text x="112" y="1362" text-anchor="end" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">+</text>
  <text x="112" y="1518" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="120" y1="1358" x2="180" y2="1358" stroke="#ef4444" stroke-width="3.5" stroke-linecap="round"/>
  <line x1="120" y1="1514" x2="180" y2="1514" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round"/>
  <text x="150" y="1352" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">14 AWG</text>
  <text x="150" y="1508" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">14 AWG</text>
  <rect x="180" y="1348" width="60" height="20" rx="3" fill="#1e293b" stroke="#ef4444" stroke-width="1.2"/>
  <text x="210" y="1361" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">221-413 +12V</text>
  <rect x="180" y="1504" width="60" height="20" rx="3" fill="#1e293b" stroke="#9ca3af" stroke-width="1.2"/>
  <text x="210" y="1517" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="700">221-415 GND</text>
  <line x1="240" y1="1358" x2="290" y2="1358" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <text x="265" y="1352" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG</text>
  <rect x="290" y="1350" width="46" height="16" rx="3" fill="#2a0a0a" stroke="#ef4444" stroke-width="1.2"/>
  <line x1="294" y1="1358.0" x2="332" y2="1358.0" stroke="#fca5a5" stroke-width="1"/>
  <text x="313.0" y="1346" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="700">3 A fuse</text>
  <line x1="336" y1="1358" x2="690" y2="1358" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <text x="520" y="1352" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">+12 V bus → J2 +</text>
  <rect x="690" y="1346" width="34" height="90" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="707" y="1342" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">J2</text>
  <text x="707" y="1362" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">+</text>
  <text x="707" y="1426" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="724" y1="1358" x2="850" y2="1358" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="724" y1="1422" x2="850" y2="1422" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
  <text x="787" y="1352" text-anchor="middle" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="8">red (+)</text>
  <text x="787" y="1416" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8">black (−)</text>
  <text x="787" y="1392" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">18 AWG red/black</text>
  <text x="787" y="1403" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">pump leads</text>
  <text x="787" y="1442" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">60 s max-on backstop (aux)</text>
  <rect x="850" y="1344" width="140" height="92" rx="4" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="920" y="1378" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">Peristaltic pump</text>
  <text x="920" y="1393" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">Adafruit 1150, 12 V</text>
  <text x="920" y="1407" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">pump_bracket</text>
  <text x="920" y="1421" text-anchor="middle" fill="#5eead4" font-family="system-ui, -apple-system, sans-serif" font-size="8">inside the chamber</text>
  <line x1="676" y1="1358" x2="676" y2="1422" stroke="#94a3b8" stroke-width="1.5"/>
  <path d="M 668 1404 L 684 1404 L 676 1390 Z" fill="#94a3b8"/>
  <line x1="668" y1="1388" x2="684" y2="1388" stroke="#e2e8f0" stroke-width="2"/>
  <circle cx="676" cy="1358" r="3" fill="#ef4444"/>
  <circle cx="676" cy="1422" r="3" fill="#22c55e"/>
  <text x="666" y="1388" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">UF4007</text>
  <text x="666" y="1399" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">band to +12 V</text>
  <rect x="560" y="1404" width="70" height="52" rx="4" fill="#1e293b" stroke="#eab308" stroke-width="1.5"/>
  <text x="595" y="1424" text-anchor="middle" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="700">IRLZ44N</text>
  <text x="566" y="1442" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">G</text>
  <text x="620" y="1426" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">D</text>
  <text x="591" y="1452" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">S</text>
  <line x1="630" y1="1422" x2="690" y2="1422" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
  <text x="650" y="1416" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">drain</text>
  <line x1="595" y1="1456" x2="595" y2="1514" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round"/>
  <rect x="400" y="1418" width="40" height="58" rx="3" fill="#0f172a" stroke="#94a3b8" stroke-width="0.8"/>
  <text x="420" y="1414" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">J1</text>
  <text x="420" y="1441" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">IN</text>
  <text x="420" y="1467" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">−</text>
  <line x1="440" y1="1438" x2="470" y2="1438" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <rect x="470" y="1430" width="50" height="16" rx="3" fill="#1e293b" stroke="#86efac" stroke-width="1"/>
  <text x="495" y="1441" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="8" font-weight="600">100R</text>
  <text x="495" y="1426" text-anchor="middle" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">gate resistor</text>
  <line x1="520" y1="1438" x2="560" y2="1438" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <circle cx="540" cy="1438" r="3" fill="#22c55e"/>
  <line x1="540" y1="1438" x2="540" y2="1466" stroke="#94a3b8" stroke-width="1.5"/>
  <rect x="531" y="1466" width="18" height="30" rx="2" fill="#1e293b" stroke="#94a3b8" stroke-width="1"/>
  <text x="540" y="1484" text-anchor="middle" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600" transform="rotate(-90 540 1484)">10K</text>
  <line x1="540" y1="1496" x2="540" y2="1514" stroke="#4b5563" stroke-width="1.5" stroke-linecap="round"/>
  <text x="527" y="1484" text-anchor="end" fill="#6b7280" font-family="system-ui, -apple-system, sans-serif" font-size="7">pull-down</text>
  <path d="M 440 1464 L 460 1464 L 460 1514" fill="none" stroke="#4b5563" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="240" y1="1514" x2="600" y2="1514" stroke="#4b5563" stroke-width="3.5" stroke-linecap="round"/>
  <text x="300" y="1508" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="8">18 AWG black → GND bus</text>
  <rect x="270" y="1390" width="90" height="88" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="315" y="1407" text-anchor="middle" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600">ESP32</text>
  <text x="315" y="1420" text-anchor="middle" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="8">relay node</text>
  <text x="354" y="1441" text-anchor="end" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">GPIO 14</text>
  <text x="354" y="1467" text-anchor="end" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">GND</text>
  <circle cx="360" cy="1438" r="3.5" fill="#22c55e"/>
  <circle cx="360" cy="1464" r="3.5" fill="#1e1e1e" stroke="#9ca3af" stroke-width="1"/>
  <line x1="360" y1="1438" x2="400" y2="1438" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/>
  <line x1="360" y1="1464" x2="400" y2="1464" stroke="#4b5563" stroke-width="3" stroke-linecap="round"/>
  <text x="380" y="1433" text-anchor="middle" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="7">Dupont</text>
  <line x1="250" y1="1452" x2="270" y2="1452" stroke="#22d3ee" stroke-width="2.5" stroke-linecap="round"/>
  <text x="258" y="1446" text-anchor="middle" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="7">USB</text>
  <rect x="356" y="1455" width="48" height="18" rx="3" fill="none" stroke="#eab308" stroke-width="1" stroke-dasharray="3,2"/>
  <g>
  <rect x="330" y="1480" width="100" height="14" rx="4" fill="#2a1f00" stroke="#eab308" stroke-width="0.6"/>
  <text x="380.0" y="1489.52" text-anchor="middle" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="7" font-weight="600">COMMON GROUND</text>
  </g>
  <text x="30" y="1548" fill="#fde047" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600">COMMON GROUND: ESP32 GND → J1 − → GND bus → WAGO 221-415 → PSU −. Leave it out and the gate has no reference — the channel never switches. Do it on both boards.</text>

  <!-- ═══════ LEGEND ═══════ -->
  <rect x="1046" y="1296" width="538" height="170" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="1060" y="1316" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600">Legend</text>
  <line x1="1060" y1="1336" x2="1090" y2="1336" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1340" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="9">RED = +12 V (and 3V3 on the QT cable)</text>
  <line x1="1060" y1="1354" x2="1090" y2="1354" stroke="#1e1e1e" stroke-width="3" stroke-linecap="round"/>
  <rect x="1060" y="1352" width="30" height="4" rx="1" fill="none" stroke="#6b7280" stroke-width="0.5"/>
  <text x="1098" y="1358" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLACK = GND / 12 V −</text>
  <line x1="1060" y1="1372" x2="1090" y2="1372" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1376" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="9">GREEN = GPIO signal / switched (drain) side</text>
  <line x1="1060" y1="1390" x2="1090" y2="1390" stroke="#3b82f6" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1394" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9">BLUE = SDA, YELLOW = SCL (STEMMA QT)</text>
  <line x1="1060" y1="1408" x2="1090" y2="1408" stroke="#a78bfa" stroke-width="3" stroke-linecap="round"/>
  <text x="1098" y="1412" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="9">PURPLE = new in Tier 3 (HX711 / reed signals)</text>
  <line x1="1321.0" y1="1336" x2="1351.0" y2="1336" stroke="#f97316" stroke-width="3" stroke-linecap="round"/>
  <text x="1359.0" y="1340" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="9">ORANGE = 120 V AC cord (power strip)</text>
  <line x1="1321.0" y1="1354" x2="1351.0" y2="1354" stroke="#22d3ee" stroke-width="3" stroke-linecap="round"/>
  <text x="1359.0" y="1358" fill="#67e8f9" font-family="system-ui, -apple-system, sans-serif" font-size="9">CYAN = USB 5 V power cable</text>
  <line x1="1321.0" y1="1372" x2="1351.0" y2="1372" stroke="#34d399" stroke-width="2" stroke-linecap="round" stroke-dasharray="5,3"/>
  <text x="1359.0" y="1376" fill="#34d399" font-family="system-ui, -apple-system, sans-serif" font-size="9">dashed = WiFi / MQTT, no wire</text>
  <rect x="1321.0" y="1384" width="30" height="12" rx="6.0" fill="#0a0a0f" stroke="#94a3b8" stroke-width="1.2"/>
  <text x="1359.0" y="1394" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">= cable through the chamber wall</text>
  <text x="1060" y="1434" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">Wire: 14 AWG pigtail · 18 AWG red/black for every 12 V run (strips, pump) · 22 AWG hookup</text>
  <text x="1060" y="1448" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9">or Dupont for GPIO / GND → J1 · 22 AWG 4-conductor for the HX711 + reed. Heat-shrink splices.</text>
  <rect x="1046" y="1474" width="538" height="84" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1"/>
  <text x="1060" y="1494" fill="#fca5a5" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">12 V branches and fuses (inline blade fuse on each +12 V branch)</text>
  <text x="1060" y="1512" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Relay board: 3 A — three fans + the pump stay under ~1 A.</text>
  <text x="1060" y="1527" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Lighting board: 7.5 A — the strips are the load. GND branches are not fused.</text>
  <text x="1060" y="1542" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">12V 10A PSU: keep the total ≤ ~8 A — cut the strips to closet length.</text>

  <!-- ═══════ WIRING STEPS ═══════ -->
  <rect x="16" y="1568" width="1568" height="176" rx="6" fill="#111827" stroke="#475569" stroke-width="1"/>
  <text x="30" y="1590" fill="#e2e8f0" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="700">Wiring Steps</text>
  <text x="30" y="1612" fill="#fdba74" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">1 · Mains and 12 V (outside)</text>
  <text x="30" y="1630" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Strip (12 + 2 USB-A): Pi PSU, 12 V PSU, 6 chargers, 4 plugs.</text>
  <text x="30" y="1645" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">PSU barrel → 14 AWG pigtail → WAGO 221-413 / 221-415.</text>
  <text x="30" y="1660" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-413 → inline 3 A fuse → relay +12 V bus (18 AWG red).</text>
  <text x="30" y="1675" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-413 → inline 7.5 A fuse → lighting +12 V bus (18 AWG red).</text>
  <text x="30" y="1690" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">221-415 → both boards' GND bus (18 AWG black).</text>
  <text x="30" y="1705" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">ESP32 GND → J1 − on both boards: the COMMON GROUND.</text>
  <text x="420" y="1612" fill="#86efac" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">2 · Switch channels + loads</text>
  <text x="420" y="1630" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">GPIO → Dupont → J1 IN → 100R → gate; 10K gate → source.</text>
  <text x="420" y="1645" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Drain → J2 −; J2 + → +12 V bus; UF4007 on relay channels.</text>
  <text x="420" y="1660" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Fans: NA-SEC3 extension, far end cut — GND → J2 −, +12 V → J2 +.</text>
  <text x="420" y="1675" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Pump on CH3 aux (GPIO 14): 18 AWG, UF4007 across it.</text>
  <text x="420" y="1690" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Strips: 18 AWG red/black. BLUE wire → CH1, RED → CH2,</text>
  <text x="420" y="1705" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">GREEN (730 nm) → CH3, common wire → +12 V.</text>
  <text x="810" y="1612" fill="#c4b5fd" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">3 · HX711 + door contact (relay node)</text>
  <text x="810" y="1630" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">22/4: red 3V3 → VCC, black GND, yellow DOUT → 32, white SCK → 33.</text>
  <text x="810" y="1645" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">22 AWG 4-conductor (2 used): COM → GPIO 35, alarm NC → GND.</text>
  <text x="810" y="1660" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">EXTERNAL 10K pull-up GPIO 35 → 3V3 (no internal pull on 34-39).</text>
  <text x="810" y="1675" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Wired on NO? Tick the portal's invert box (reed_inv).</text>
  <text x="810" y="1690" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Tick HX711 + door reed under Optional peripherals.</text>
  <text x="810" y="1705" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Cell red → E+, black → E−; tare, then calibrate once.</text>
  <text x="1200" y="1612" fill="#93c5fd" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700">4 · Climate, cameras, plugs</text>
  <text x="1200" y="1630" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Each climate node: 4397 on 3V3 / GND / GPIO 21 / GPIO 22,</text>
  <text x="1200" y="1645" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">QT plug → SHT31-D, 4210 → SCD41, 4210 → BH1750.</text>
  <text x="1200" y="1660" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">climate-01/02 + cam-01/02: 6 ft (2 m) USB through the grommet.</text>
  <text x="1200" y="1675" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Relay + lighting ESP32s stay outside on short cables.</text>
  <text x="1200" y="1690" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">Plugs: humidifier, dehumidifier, heater, cooler —</text>
  <text x="1200" y="1705" fill="#d1d5db" font-family="system-ui, -apple-system, sans-serif" font-size="9">WiFi only, sp-3p + Full Topic (see the build guide).</text>
  <text x="1200" y="1736" fill="#94a3b8" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-style="italic">ESP32-S3 nodes use other pins (build guide §8a); S3 cameras: §8b.</text>

  <!-- ═══════════════════════ FOOTER ═══════════════════════ -->
  <text x="800" y="1760" text-anchor="middle" fill="#334155" font-family="system-ui, -apple-system, sans-serif" font-size="9">SporePrint  |  Tier 3: All The Things  |  github.com/59psi/SporePrint</text>

</svg>
`}};export{t as BUILDER_WIRING_SVGS};
//# sourceMappingURL=builder.wiring.generated-BUxAZAR8.js.map
