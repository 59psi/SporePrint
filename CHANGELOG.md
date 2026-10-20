# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `docs/cloud-relay-flow.md` documents the relay's session and device-token
  rechecks.
- The dashboard's Vision contamination flags and the Species Wizard's
  mismatch tag use the theme's error tint, as every other error mark does.
- `GET /api/sessions/{id}/stats` adds `last_harvest_at`: when the newest harvest was logged (null before the first).
- `GET /api/health/detail/system`: `table_counts` (six full table counts on
  every call, polled every 15 s by the dashboard's fleet view and every 60 s
  by the cloud heartbeat) is now recounted at most every 10 minutes.
- The Pi stores each node's transport security from its heartbeat (`tls`,
  `tls_fallback`, `board`, `ca_fp`, additive in `GET /api/hardware/nodes`) and
  checks `ca_fp` against the CA it serves: `ca_fp_match` is 1 or 0, and a
  node trusting another CA is logged as a `[SEC]` warning.
- Telemetry writes are lighter on the SD card: each connection runs
  `synchronous=NORMAL` (it ran FULL, an fsync per commit), a frame's readings
  and its `last_seen` refresh are one commit, a live frame's grow is looked up
  once for both its readings' tag and its rules, and the newest readings
  (`GET /api/telemetry/latest`) are read through a `(node, sensor, time)`
  index instead of a scan of the week's raw history. Node log batches trim
  the 10,000-row history every 500 rows instead of on every batch.
- Notifications and the weather and Aranet clients reuse one TLS context
  instead of loading the CA bundle on the event loop for every request.
- A cloud reboot command runs `systemctl reboot` in a worker thread, off the
  event loop.
- Fewer database round trips per telemetry frame: each rule target is
  resolved once per frame, and an OFF deletes a stored safety ceiling only
  when one exists.
- **Smart plug reports no longer write the database on every message.** A
  report that changes nothing (Shelly Gen1 republishes its relay and power
  every 30 s) refreshes `last_seen` at most every 5 minutes; a state, power or
  online change is still written at once.
- **A chamber runs one grow at a time.** Starting a grow in a chamber that
  still ran another, or linking one to it (`PATCH /api/chambers/{id}`), let
  the newer grow take the chamber over: a grain jar started in a fruiting
  tub's chamber ran it as a sealed vessel, with no fresh air or humidity
  control for the tub, and ending the jar then showed the chamber idle while
  the tub still ran there. Both are now refused with 409 (a cloud session
  start reports why) until the first grow ends or goes to cold storage. A
  chamber left with two grows by an older release shows the remaining one
  when either ends.
- **A node listed in no chamber runs only a grow bound to no chamber.** It
  used to take the grow of the only chamber that had one, so when the
  closet's own grow ended, the closet's unlisted nodes started running that
  chamber's setpoints. List every node of a chamber in it (README →
  Multi-Chamber Management).
- **Aranet and Pulse run on the shared integration poll loop**, like the
  other polling drivers, so their health (including the per-device
  "degraded"/"error" states) and start/stop behave the same way.
- **Docs:** the Aranet and Pulse guides no longer walk you through filling
  `sensor_mappings` / `device_mappings` (accepted but not used yet; add a
  sensor's node id to a chamber's `node_ids` to show it there), describe how
  readings are stored and when a sensor counts as stale, and no longer call
  Pulse's cloud mode premium; the lighting/HVAC guide lists every driver as
  free; `smart-plugs.md` notes that a manual OFF clears the safety ceiling
  and how numeric action values are read.
- **Docs:** the integration notes say which chamber and mapping fields are
  accepted but not used yet (Quest and Anden `chamber_id`, Fluence, Fohse
  and BIOS `fixture_mappings`, Trane `device_mappings`, the plugs'
  `chamber_id` and `actuator`), and how to show a vendor device with a
  chamber (add its node id to the chamber's `node_ids`); `feature-status.md`
  also lists a chamber's unused `automation_rule_ids`.
- `GET /api/builder/tiers` `component_count` is the number of BOM lines. It
  summed every line's quantity, adding feet of wire, grams of solder and
  screws into one figure (308 for All the Things).
- The Builder's model, diagram and firmware file handling (listings,
  include inlining, ZIP bundles) moved from the router into
  `app/builder/service.py`; the routes and responses are unchanged.
- Automatic Claude camera analysis now runs every `SPOREPRINT_VISION_AUTO_INTERVAL_MIN` (6 h) per camera of a grow instead of once per grow, and each camera's first frame after a phase change is read. With one slot per grow, two cameras raced for it and one view could go unread indefinitely; Claude spend now scales with the number of cameras.
- The weather poller keeps the hourly forecast in memory only and no longer rewrites it to the `weather_forecasts` table on every poll (nothing read it; about 24,000 inserts and as many deletes a day on the SD card). The table is kept.
- `pi_case.scad` drops `fan_size`, which nothing read (`cooling="fan40"` fixes the fan size), and `power_supply_mount.scad` an unused derived value. A test now fails when a model assigns a top-level parameter that nothing reads.
- `scripts/pin_firmware_toolchain.py` keeps each download in a folder named after its SHA-256, so two locked packages whose URLs end in the same file name can never overwrite each other's checked copy.
- **`provision-node.sh --rotate` re-keys the nodes before the Pi.** Current
  node firmware keeps accepting the key a re-key replaced until the first
  command signed with the new one, so a rotation now lists re-keying every
  node first and applying the key to the Pi server last, and no node rejects
  a command in between (firmware without that grace is re-keyed last). The
  outage warning is gone; a first key, with none in `.env` yet, still goes to
  the Pi first. `docs/firmware-security.md` gains "Rotating the key", with an
  empty command that retires a node's old key at once.
- README's UI Pages table says the Chambers page re-reads its readings and event feed every 30 s while the page is visible, instead of "reload to refresh".

### Fixed

- **Pinning the mister on kept the misting rules off long after it stopped.**
  The dashboard offered ON pins of up to 5 minutes, but the relay node stops
  the misting pump after 60 s, and the pin kept automation off the channel
  for the rest of the window. The chamber page now offers ON pins only within
  each actuator's firmware limit (up to 60 s for the mister), and the fleet
  page's quick pin holds the mister on for 60 s. OFF pins are unchanged.
- **The Pi dashboard words ages the way the web app does.** "Seen …",
  "synced …" and "last frame …" use whole seconds, minutes, hours and days,
  rounded down; the Vision page gains the day unit ("2d ago", not "50h ago")
  and counts a frame's age on the Pi's clock, like the rest of the dashboard.
  A timestamp a moment ahead of the clock reads "now" instead of "0s ago".
- **Chamber history spread each trace evenly across the width** and read its
  time axis off the temperature samples by position, so a stretch with no
  data vanished, the axis mislabelled it, and a sensor that began reporting
  partway through was stretched over the whole window. The traces and the
  axis now follow time across the selected window, and the line breaks across
  a gap.
- **The chamber page and the Chambers quick override offered "override →" on
  the heater and pump,** which no node drives; it could only answer "no
  heater channel is mapped". Those tiles show state only (a standing override
  can still be released).
- **Integrations:** "Set power on/off" left unchecked sent no state, so
  switching a Kasa, Wemo or Tapo plug off failed; it now sends off.
  Agrowtek's "Set output" value went out as text ("false", "50"); it now goes
  as a boolean or a number, and anything else is refused in the form. Device
  lists show `[]` when unset instead of `{}`, which the Pi refuses. Grafana's
  actuator and contamination counters show as on until set, as the server
  treats them. Pulse Grow's free local (LAN) mode can be set up: transport,
  device URLs, discovery broadcast address and ports. A JSON field no longer
  re-formats itself while you type, a cleared number field saves as the
  default instead of failing, and a card takes the latest settings after a
  save or a test.
- **Enter on a chamber's name in the Chambers table selected the row**
  instead of opening the chamber; links, buttons and fields inside a
  clickable row keep their own keys now.
- **The Live events and Session timeline headers said "local · 1Hz"**,
  which neither is. The label is gone.
- **A sensor with no reading showed "—°F", "—%", "—ppm" or "—kPa"** on the
  chamber page; it shows a bare "—".
- **The spore-print marks on Chambers re-stippled on every refresh;** each is
  drawn once.
- **A dialog taller than the screen** ran off it with its buttons out of
  reach; dialogs now scroll inside.
- **Automation page: a rule held by a hold on its whole node showed as
  "active".** A hold with no channel (a cloud suspend of a scene rule, a hold
  on a node) keeps the rules off every channel of that node, and a hold on
  any channel of a light holds its scene rules, but the page only matched a
  hold on the rule's own target and channel. Those rules now show as
  suspended, with what holds them, and "cancel suspend" clears each hold by
  its own target and channel (a whole-node hold with a DELETE that names no
  channel, which is the only one that clears it). The page also stopped
  re-rendering every rule card once a second while nothing was suspended.
- **Automation page: fire counts, "failed recently" and "last fired" came
  from the newest 500 firings.** A Pi running its schedules fires more than
  that in a few days, so the week's counts came out low and a rule whose last
  firing was older than the newest 500 read "never". The new
  `GET /api/automation/firings/stats?days=7` counts every firing in the
  window, per rule and in total (safety cutoffs included), with each rule's
  newest firing of all time, and the page reads it. The side panel asks the
  Pi for the selected rule's own newest 20 firings.
- **Automation page: firing times and "last fired" had no date,** so a rule
  that last fired days ago read as if it fired today. Times from an earlier
  day now show their date ("10-17 14:03"), as do the chamber event feeds,
  which also run across days.
- **Automation page: a double click on a rule's switch flipped it twice,**
  and the two answers could land in either order, leaving the switch showing
  the opposite of what the Pi holds. The switch now waits for the Pi's answer
  before it takes another click, and `PATCH /api/automation/rules/{id}/toggle`
  flips the flag in one statement, so two toggles that overlap (two tabs)
  flip it twice instead of once.
- **Automation page: "authoring → cloud" did nothing.** It is now a link to
  sporeprint.ai/automation.
- **Chambers: a safety lockout looked like an ordinary override.** When a
  rule held an actuator past its `safety_max_on_seconds` ceiling, the hold the
  Pi places read "override · until …" with a "release →" button, so one tap
  handed the actuator back to the rule that had just tripped, with nothing
  saying why it was held. The tile now reads "safety lockout · until …" and
  offers "clear lockout →", with the Pi's reason on the button.
- **Chambers: a VPD reading that had stopped updating outranked fresh
  climate readings.** A VPD reported by an integration was shown whatever
  its age; when it is more than two minutes older than the temperature and
  humidity, the VPD derived from those is shown instead.
- **Shopping List: a ticked part stayed bought after more of it was
  needed.** A tick was kept per part name, so raising the chamber count, or
  sending a build that needs more of the part (one ESP32, then a 3-pack),
  left the line ticked and "to buy" and "still to buy" too low. A tick now
  also records how much it bought; a line that needs more shows "bought 3 of
  9", is counted in what is left to buy (the missing units, in whole packs)
  and in the CSV, and one tick buys the rest. A pack keeps covering what it
  holds (a pack of 70 inserts stays bought at 28 or 52). Ticks from before
  count as bought for the amount on screen when the list first opens.
- **Shopping List: the CSV opened garbled in Excel.** Excel reads a CSV
  without a byte-order mark in the system code page, which garbled the "×",
  "·" and "—" in every quantity ("Ã—4 Â· 2 packs of 2"); the file now starts
  with a UTF-8 byte-order mark.
- **Shopping List: grow supplies for a custom species profile whose id mixes
  "-" and "_" answered "Species profile not found".** The list asks for the
  id with "_" throughout; the Pi now finds a profile by its id with either
  separator in any place.
- **Builder: a link with a malformed tab name blanked the whole dashboard.**
  Opening `/builder#%` (or `#100%`) threw while the page drew; it now opens
  the Overview tab.
- **Builder: two open Builder tabs undid each other's setup ticks.** Each tab
  wrote its own copy of the setup progress over the other's; every tick is
  now written into what is stored, and a tick made in another tab shows.
- **Builder: some model descriptions could not be read in full.** The Pi's
  model listing cuts a description at 240 characters, at a sentence end when
  it can, and that cut left no "…", so the Models tab offered no "more" (four
  of the shipped models, the pump bracket's "mount OUTSIDE the grow chamber"
  note among the hidden text). `GET /api/builder/models` now flags a cut
  description (`description_truncated`) and the tab offers the rest whenever
  it is set.
- **First-run setup: blocked site data turned the setup redirect off, and a
  reinstalled Pi never brought a browser back to the wizard.** The dashboard
  cached "setup complete" in the browser for good and read that cache
  unguarded. It now asks the Pi every time (the Pi's answer decides; an
  error never redirects) and sends a tab to the wizard at most once per
  session, so a Pi that could not store the flag cannot trap the operator in
  the wizard.
- **A chamber running a grow could read as idle.** The dashboard found a
  chamber's grow only through the chamber's `active_session_id` link, while
  the automation drives the chamber's nodes with the grow bound to it, else
  the linked one, else the newest grow bound to no chamber. A grow started
  without a chamber, or the older of two grows in one chamber after the newer
  ended, ran the chamber's nodes while the chamber page, history, inventory,
  planner and Chambers home showed "idle" and no event feed.
  `GET /api/chambers` and `GET /api/chambers/{id}` now also return
  `resolved_session_id`, the grow the Pi runs there, and every dashboard
  page reads it. A grow two chambers share is listed once in the live feed,
  under both names.
- **Chamber page: a manual override could only switch a channel on.** Every
  override pinned the actuator ON, whatever its state, so there was no way to
  stop a running mister or fan from the chamber page, and "release" showed
  the tile as "Off" without switching anything. The override now asks for on
  or off before the window (an OFF pin sends a plain `state: off`, no
  duration). The hold is registered before the command, so no rule can
  answer the command first, and lifted again if the command fails. Release
  still only hands the channel back to the rules, and the tile no longer
  claims a state it does not know ("—" instead of "Off").
- **Manual holds and rule suspends were timed by the browser's clock.** The
  dashboard sent an absolute expiry computed on the phone or laptop, so with
  the Pi's clock off (no battery-backed clock and no NTP after a power cut) a
  5 s pin kept the rules off a channel for hours, or arrived already expired.
  `POST /api/automation/overrides` now takes `duration_sec`, counted on the
  Pi's own clock (an absolute `expires_at` still works), the cloud's override
  frames use their `duration_sec` the same way, and the dashboard counts
  holds, suspends and ages on the Pi's clock (from its responses' `Date`
  header).
- **Chamber page: a dead node's last readings showed as current.** The
  readouts showed the newest row the Pi had for each sensor however old it
  was, with no age, and never refreshed. Each readout now says how old it is;
  a reading older than 15 minutes, or from a node the Pi reports offline,
  shows "—" with "stale · last 74.2°F · 12h ago", and the readouts and
  sparklines re-read every 30 s without touching an override in progress.
- **Chamber page and history: a deleted custom species profile took the page
  down.** A grow whose species profile had since been deleted showed only
  "Failed to load chamber", hiding the readouts and the override controls.
  The species is now named from its id instead, and a feed that fails to
  load says so without failing the rest of the page.
- **Chamber history: charts were blank or drawn off the scope.** The history
  read every trace from the chamber's first listed node, so a chamber listing
  its relay first showed empty charts; each sensor is now read from the node
  that reports it. A steady reading got a zero-width scale ("75 – 75 °F")
  and its line was drawn far off the chart; the scale now rounds outward,
  always holds every sample and gives a flat reading a minimum span. Derived
  VPD paired temperature and humidity samples by position, so one missing
  humidity sample shifted every later point; they are paired by time now.
- **Chamber page: sparklines read every sensor from the temperature node,**
  so a CO₂ sensor on another node showed a live CO₂ readout beside an empty
  CO₂ trace. Each sparkline comes from the node that reports it.
- **Chamber page and Chambers home downloaded a grow's whole event history**
  on every load to show its newest 40 (22 on the home page); they now ask
  the Pi for just those.
- **Chamber page: a slow load for one chamber could fill another chamber's
  actuator strip** after a quick back-and-forward between two chamber pages.
- **Contamination checks were never linked to a chamber or grow.** A
  positive identify was saved with no chamber and no session, so chamber
  contamination stats, the event gallery and the grow's history (on the Pi
  and in the cloud) never counted it. The drop zone now asks which chamber
  the photo is from (the only chamber by default) and links the check to it
  and to its grow.
- **Contamination: two checks of photos with the same file name in the same
  second shared one row id,** so one answer overwrote both rows (iOS names
  every photo `image.jpg`).
- **Chamber inventory: the detail panel kept the last chamber's draft.** A
  note typed into "schedule maintenance", or an error, carried over to the
  next chamber selected, and "schedule →" posted the note to that chamber.
- **Chamber inventory: "mark cleaned" while the maintenance log was loading
  or had failed to load** logged a second clean and left the scheduled clean
  task open. The button now waits for the log.
- **Cultures: a culture stored under the Pi's underscored species id
  (`blue_oyster`) showed the raw id** in the table, panel, parent picker and
  lineage tree. It shows the species' names.
- **Cultures: the "created" date was the UTC day,** a day late for a culture
  made in the evening in the Americas. It is the local day now.
- **Cultures: the lineage tree went stale after a transfer** from the
  selected culture; it reloads with the list.
- **Cultures: "+ new culture" offered the source "transfer" with no parent,**
  making a generation-0 culture outside its lineage. Transfers are recorded
  with the transfer flow, which names the parent.
- Chambers page: the tiles, quick overrides and live event feed now re-read the Pi every 30 seconds while the page is visible (the chambers, grows and species every 5 minutes). A tablet left on the page kept its first readings, node states and feed for good while the CPU/RAM sparklines kept moving. The grid says when it last heard from the Pi, and a reading too old to be current shows "—" instead of an old value.
- Chambers page: polling stops while the tab is hidden and catches up as soon as it shows again.
- Chambers page quick overrides: tapping an actuator now asks whether to pin it on or off. It could only ever pin a channel ON, since the page can't see the channel's state. The hold is placed before the channel is switched and lifted again if the command fails; a failure used to leave a channel switched with no hold while the panel showed neither. Once the Pi confirms a pin, the actuator shows the state it pins ("On" / "Off") and when it ends; a hold that has run out leaves the panel at the next poll, and tapping one offers a new pin instead of releasing nothing.
- Chambers page: one chamber grow whose events fail to load no longer replaces the whole page with "Failed to load chambers"; the feed leaves that grow out and says so. The Pi system figures stay up even when the chambers fail to load.
- Chambers page: the quick-override note said to tap a tile to switch target, but a tile opens its chamber; it now points to the chamber menu.
- Chambers page and Settings: uptime counts whole hours (47.6 h read "1d / 24h", now "1d 23h").
- Sessions: a grow's timeline loads its newest 200 events, with "show full history" for the rest, instead of downloading and drawing the whole history (thousands of rule firings on a long grow) each time the grow is opened. The harvest form still starts on the right flush number.
- Experiments: a significance analysis still running for one experiment no longer lands in the panel of the experiment picked next, whose button no longer sits on "analyzing…".
- Experiments: the significance analysis is sent as a POST, the method the Pi expects for a call that spends Claude credit.
- Experiments and Transcripts: a Claude analysis that comes back as prose instead of the requested fields is shown as written; it used to leave an empty panel.
- Experiments: the new-experiment form refuses the same session as both control and variant (a grow compared with itself ties on every metric).
- Firmware: a push result kept from an earlier push says when that push finished ("last push finished 3d ago"), so a days-old failure no longer reads as current.
- Firmware, Hardware and Setup: a node that reports an empty firmware version reads "fw —" instead of a blank.
- Integrations: saving or testing a driver no longer swaps the whole panel for "Loading…" while the list is re-read, which wiped the other cards' unsaved settings and hid the test result.
- Sessions: "+ new session" started in the first chamber even when that chamber was running a grow, so logging a grain jar with the defaults took over a fruiting tub's automation (no fresh air, no humidity control). The form now starts on a chamber that runs no grow (else unassigned), shows a chamber with a grow of its own as unavailable, asks for a second click before a new session takes over a grow it would displace (an unassigned grow the Pi's nodes follow), and shows the Pi's reason when it refuses a session.
- Sessions, Cultures, Planner and Species: the species pickers and the species library list the custom profiles saved on the Pi (user-defined strains, clones) after the built-in library; a custom profile could not be chosen from the dashboard.
- Sessions: a new session starts in its container's own stage: an agar plate in agar, a liquid culture in liquid culture, a grain jar in grain colonization (in substrate colonization when the species profile has no such stage). Every new session started in substrate colonization.
- Sessions: choosing another session drops an armed "confirm end?" or "mark contaminated" and an open harvest form, so one click can no longer end, abort or log a harvest against a different grow. With filters that hide every row, the detail panel shows no session instead of one the list hides.
- Sessions: a grow's day count turns over at local midnight when it has an inoculation date (in the Americas it turned over in the afternoon), an ended grow's Day column stops at its end, and the "duration" sort orders by how long each grow ran (it sorted like "oldest").
- Sessions: the harvest form starts on the right flush number (the next flush after the grow went back into fruiting, the same one for more pickings of a flush). It always said 1, and a second flush saved that way merged into the first, so flush counts and the rest → fruiting / complete suggestion ran a flush short.
- Sessions: "yield · 30d" is what was harvested in the last 30 days, from any grow (`GET /api/sessions?yield_since=` adds each grow's grams since then); it summed the whole yield of grows started in the last 30 days.
- Sessions, transcripts and grow reports print yield totals to a tenth of a gram; sums of 0.1 g harvests showed as "300.29999999999995g".
- Settings: clearing the ntfy topic goes back to the default topic, and a topic ntfy would refuse (a space, punctuation) is refused before it is sent.
- Setup § III Cloud link: describes the pairing flow that exists (trade the code for a configure token with the command shown, then Devices → Pair new device on sporeprint.ai), says when a Pi paired after its server started needs a restart to connect, and how (`GET /api/cloud/status` adds `restart_required`), tells a paired but offline Pi from an unpaired one, and keeps checking after the code expires, so a Pi connected later shows as paired.
- Setup § IV First chamber: a claimed node joins a chamber, one picked there or a new one named there (a claim alone put it in no chamber, and the Chambers page stayed empty). A failed scan says so and keeps rescan available; only a server without the discovery endpoint is reported as such.
- Shopping List: the exported CSV's download link is freed 40 seconds after the click instead of at once, which could cancel the download in Safari and older Firefox.
- **The dashboard's Vision page never listed a camera.** It looked for nodes
  of type or role `cam`, but camera nodes report `camera`, so the page said
  "No camera nodes on this Pi yet" with a camera online, and the Claude check
  and the manual contamination mark could not be reached. Cameras are found
  by `camera` now (and still by `cam`).
- **Vision: a verdict or contamination mark stayed under the next frame.**
  Claude check results and marks were kept per camera, so after "refresh
  all →" brought a newer frame, the older frame's verdict and "flagged" mark
  read as the new frame's. Each now belongs to the frame it was made on, and
  the verdict the Pi stored on the latest frame (the automatic check, or an
  earlier one) still shows after a reload.
- **Vision: "flag chamber →" only labelled the frame.** The mark reached
  neither the Contamination page, the chamber's contamination stats nor the
  cloud sync, and the "flagged" badge was gone after a reload. It now also
  logs a contamination event for the frame's grow and chamber, and the badge
  is read back from the frame the Pi stored it on.
- **Vision: the key note promised a fallback that does not exist.** It said
  the Claude check falls back to an on-Pi classifier when no key is set.
  There is none yet: without a key there is no Claude check and no automatic
  contamination detection, which the note now says, with where to add a key.
- **Species wizard: the climate options named the wrong temperatures.** They
  read 55–62 / 62–70 / 70–80 °F while the Pi scores the answers against
  50–65 / 65–75 / 75–85 °F, so a 72 °F room picking "warm" was matched
  against 75–85 °F and a 65–75 °F fruiter scored as outside the range. The
  options now state the bands the Pi uses.
- **Species wizard: active species could not rank alongside the rest.** With
  "include active" on, every goal the wizard sent gave the active category
  no goal points. "Mixed — exploring" now asks for the goal that scores every
  category alike while active species are in the pool.
- **Species library: the TEK guide showed another phase's numbers.** Its
  steps read a profile's phases by position, so a profile that pins under its
  fruiting conditions showed the fruiting duration under "Primordia induction
  (pinning)", a species that never fruits got Fruiting and Harvest steps with
  its colonization numbers, and a grain spawn run was titled substrate
  colonization. Each step now reads its own phase by name and appears only
  when the profile has that phase; pinning is described in the fruiting step
  when there is no separate pinning phase.
- **Species library: the yield estimator overstated yields about 2.5×.** It
  multiplied a wet block weight (default 2,270 g, a 5 lb block) by biological
  efficiency, which is fresh yield over dry substrate. It now takes the dry
  substrate weight, default 900 g (a 5 lb block at about 60 % moisture).
- **Species library: "apply to chamber →" applied nothing.** It opened the
  Planner exactly as "plan grow →" does, and is removed.
- **Species library: a damaged "recently viewed" value blanked the page.**
  Anything but a list of species ids stored under `pi:species:recent` crashed
  the page until browser storage was cleared; it now reads as none.
- **Species library: the photo tiles' shading never rendered.** The overlay
  asked for a colour the theme does not define; it uses the base colour now.
- **Transcripts: exports and "copy to clipboard" failed silently.** A failed
  export showed nothing, and on the dashboard's plain-http LAN address the
  copy did nothing (browsers offer the Clipboard API only on secure origins).
  Both now say what happened, the copy falls back to the method that works
  over http, and a download's link stays valid until Safari / iOS have read
  it.
- **Transcripts: a Claude analysis opened under the wrong session.** Picking
  another session while an analysis ran showed that session as analysing and
  then switched it to an empty analysis tab. The result, and any error, now
  stay with the session they were run for.
- **Most node outages never paged.** When a node loses power or WiFi or
  crash-loops, the broker announces it offline within about 22 s, and the
  liveness check skipped every node already marked offline, so the CRITICAL
  "node offline" page and the cloud's push never went out for those nodes:
  only a node that went silent without that announcement was paged. Every
  node silent for 15 minutes is now paged once, whoever marked it offline;
  its next heartbeat or live "online" re-arms the page, and a Pi restart does
  not page a dead node again. Nodes already offline when you update count as
  paged.
- **Paging a silent node could make telemetry and rule commands fail.** The
  liveness check held the database write lock while it waited on the ntfy
  server (5 s timeouts), so meanwhile telemetry writes and rule firings could
  fail with "database is locked" and a rule's command was not sent. The pages
  now go out after the change is saved.
- **Socket.IO clients did not hear every node status change.** `node_status`
  is now also sent when a silent node is marked offline and when a heartbeat
  brings an offline node back.
- **A camera that reached the Pi by an unlisted name lost its frames
  silently.** Since the Host allow-list, a camera whose portal "Pi host" is a
  name outside it (for example your router's own `sporeprint.fritz.box`) has
  its uploads refused, so its vision checks stop while MQTT keeps it looking
  online. The Pi now logs each such camera with its node id and pages once a
  day (WARNING) for a registered one, naming the setting to change; the README
  upgrade notes cover the case.
- **QR labels ignored `SPOREPRINT_PUBLIC_UI_URL`.** A label requested without
  an Origin or Referer (a typed URL, a script) always pointed at
  `sporeprint.local:3001`, a dead link where mDNS does not resolve. It now
  uses `SPOREPRINT_PUBLIC_UI_URL`. A malformed Referer no longer causes a 500.
- **`GET /api/sessions` always reported `biological_efficiency: null`.** The
  session rows (list, detail, and the session returned by every session
  change) now carry the same figure as `GET /api/sessions/{id}/stats`.
- **A database created by the very first release could not create
  sessions.** It lacked the session location columns (`tub_number`,
  `shelf_number`, `shelf_side`), which are now added at start-up.
- **A failed database upgrade at start-up went unnoticed.** A column
  migration that failed (a full SD card, an I/O error) was ignored, and the
  server started without the column, so heartbeats or rule firings then
  failed with "no such column" until the next restart. The server now stops
  with the error instead.
- **Socket.IO connects could be refused for up to an hour after the clock
  stepped back.** The connect rate limit measured its window on the wall
  clock, so after a backward step (NTP, `date -s`, an RTC that ran ahead) a
  dashboard reconnecting far below the limit was refused until the clock
  caught up. It now uses a monotonic clock, and forgets idle clients.
- **`GET /api/health/detail/tasks` showed failing jobs as running.** Weather
  polling, the nightly retention and the node-liveness check were reported
  "running" forever, even when retention failed every night. Each now reports
  running, idle or error with the error message (a poll every weather
  provider failed counts as an error).
- **Browser clients on another LAN origin could not use the `PUT` routes or
  read errors.** CORS now allows `PUT` (settings, rules, species,
  integration config, planner events) and the `X-Request-ID` header, exposes
  `X-Request-ID`, and an API-key 401 carries the CORS headers, so a
  cross-origin client sees the 401 instead of an opaque network error.
- **One malformed MQTT message could stop all ingest.** A payload Python's
  JSON parser refuses to build (nested thousands of levels deep, or an
  integer longer than 4,300 digits) escaped the message loop and restarted
  the MQTT session. Published retained, it came back on every reconnect, so
  no reading was stored and no rule ran until someone cleared it. Such a
  frame, and any frame over 64 KB, is now dropped with a warning and counted
  (`reliability.dropped_frames` in `GET /api/health/detail/system`); a frame
  that fails later in its handling no longer ends the session either.
- **Settings saved on the Settings page were lost at every restart.** The
  Claude key, ntfy topic, OTA verify key and weather location reached the
  running server only when saved: after a restart (a power cut, an update)
  vision auto-analysis was off, every page went to the default ntfy topic and
  OTA was refused, while the Settings page still showed the saved values.
  Saved settings are now applied at start-up; one that no longer validates is
  skipped with a warning and the `.env` value stays in force.
- **A cleared or invalid setting was stored as is.** An empty value now
  removes the override, as documented (a cleared ntfy topic used to be saved
  and every page, critical ones included, was refused by ntfy). An ntfy topic
  ntfy would refuse (spaces, over 64 characters), a NaN or infinite weather
  latitude/longitude, a poll interval over a day and a `setup_complete` other
  than `0`/`1` are refused with 400.
- **Firmware limit alerts paged CRITICAL for conditions the grow expects.**
  A node's own limits (CO2 above 4000 ppm, below 40 °F, RH below 30 % or above
  99 %) fired hourly through phases that hold those levels on purpose:
  colonization CO2 with no fresh air, a fridge at 35-40 °F in cold storage,
  room CO2 and humidity around a sealed bag or jar. A node's temperature, CO2
  or humidity alert is now pushed only when the reading is outside what its
  grow's current phase allows; with no grow running, every limit still pages,
  and sensor failures always do.
- **A CO2 emergency on one node could silence another node's.** CO2 pages are
  now always collapsed per node and name the node; temperature and humidity
  emergency pages name their node too (`Temperature EMERGENCY on climate-a`).
- **Two grows of the same species got one phase reminder between them.**
  Reminders were collapsed by session name, which is the species name by
  default; each session now gets its own.
- **One reading with a node clock far in the future pinned the "latest"
  reading.** A node that synced to a bogus future time (a year ahead, say)
  left that reading on the Fleet and Chamber pages and in Grafana until real
  time caught up with it, and retention never aged it out. A synced timestamp
  more than 5 minutes ahead of the Pi is now stored at its arrival time
  (counted in `reliability.future_ts_clamps`; frame ordering and the skew
  warning still use the node's own clock), and the nightly retention moves
  readings already stored in the future back to the time they arrived.
- **A null or NaN reading lost the whole frame.** A dew point computed from
  RH 0 arrives as `null`, and one such field failed the frame's insert, so its
  temperature, humidity and CO2 were lost too. A field that is not a finite
  number is now skipped (`reliability.skipped_readings`) and the rest stored.
  `POST /api/telemetry/ingest` refuses a `ts` that is not a finite number, and
  a non-string `node_id`, with 422.
- **A grow running without a chamber binding had no readings of its own.**
  The rules engine drives a chamber with no grow of its own by the newest
  grow bound to no chamber, but readings were tagged by a stricter rule, so
  that grow's per-session charts were empty and its transcript fell back to
  every node's telemetry. Readings are now tagged with the grow the engine
  runs on them, and once they age into rollups such a grow still resolves to
  the chamber it runs.
- **Restarting the Pi made long-dead nodes look "seen just now".** The broker
  replays each node's retained status (its last-will "offline" included) on
  every reconnect, and each one refreshed `last_seen`. Only a live "online"
  does now; an "offline" records the status without refreshing it.
- **A node re-provisioned without channels kept its old channel list**, so
  rules naming channels it no longer has still passed validation. A health
  report without channels now clears the list.
- **A manual ON pin outlived the node's own safety cutoff.** When a node's
  max-on backstop, safe mode or an OTA start switches a pinned channel off,
  the hold ends instead of showing the channel held on and keeping automation
  off it until it expired. Only holds placed with an ON command end this way
  (`POST /api/automation/overrides` takes an optional `state`; the dashboard
  and cloud pins send it); rule suspensions and safety lockouts stay.
- **Node OTA events forwarded to the cloud read as "firmware" events.** A
  start event's own `type` and uptime `ts` replaced the event's; it now stays
  `node_ota` with the Pi's time and carries them as `ota_type` / `node_ts`.
- **README:** the weather provider order is not fixed; `weather_provider`
  picks the one tried first.
- **The CO2 Hard Ceiling and the life-safety CO2 page could never fire.** Both
  needed more than 40000 ppm, the full scale of the SCD30 and SCD4x, which
  report a saturated reading as exactly 40000. Both now trip at 40000 ppm;
  unedited stored copies of the rule upgrade at start-up. (An MH-Z19C, 5000 ppm
  full scale, never reaches that level.)
- **One CO2 page held back the next.** A stage-band CO2 emergency blocked the
  same node's life-safety page for 15 minutes, so a climb to a level dangerous
  to people paged nobody, and every node's CO2 page shared one ntfy key, so one
  node's page silenced every other node's. Each node now pages on its own, the
  life-safety level separately from the stage band (a reading that trips both
  still pages once), the page names the node, and a page ntfy did not take is
  retried on the next frame instead of 15 minutes later (without forwarding it
  to the cloud again).
- **Manual holds:** a new hold on an actuator now replaces the one in force.
  Each hold used to add a row while only the newest counted, so a short hold
  placed over a long one released the actuator early, session-end safing still
  treated it as held, and the long hold came back after a restart. An "until
  cancelled" hold from before 5.0 now really ends after 24 h, an expiry of 0
  reads as expired instead of never, and a NaN expiry gets the 24 h ceiling.
- **A safety lockout could end early.** A ceiling that tripped while a hold
  was about to expire placed no lockout, so the next frame after the hold
  lapsed switched the heater straight back on. The 15-minute lockout now
  applies unless a hold already in force runs longer, and the warning names
  that hold.
- **A safety ceiling on a scene rule left the lights on.** Its OFF went to
  `cmd/config`, which switches nothing, while the trip read as sent, warned
  "switched OFF" and held the light out of the Lights Off rule. It now sends
  the all-off scene, the same OFF session-end safing sends.
- **A safety ceiling restored at boot trusted a clock that was behind.** A Pi
  with no real-time clock that started before NTP set its clock waited the
  overstated time, up to hours past the real deadline, before switching a
  heater off. A ceiling armed "in the future" now fires at once, the wait is
  capped at the ceiling's own length, and it re-checks the clock every 30 s.
- **A safety trip is on record from the start:** its firing is written as
  pending before the OFF goes out, not only after up to ten minutes of
  retries.
- **A firing whose outcome could not be written left its device without a
  ceiling.** A database busy at that moment skipped the safety ceiling for an
  ON that had already gone out. The ceiling is now armed regardless.
- **The grow timeline listed actuations that never happened.** "Rule … fired"
  was written before the command went out; an unpaired plug or a broker outage
  added one every cooldown. Only a command that went out reaches the timeline
  now (the firing history still records every outcome).
- **A liquid culture counted as an open container:** the humidifier and fans
  ran against a sealed jar and the closet paged humidity emergencies. Liquid
  culture is now a sealed culture vessel, in one container list the engine and
  the next-phase suggestion share.
- **A jar parked in cold storage drove the closet it left.** The closet ran
  the fridge's 35–40 °F band (cooler on, a temperature emergency page every
  15 minutes) and a grow sharing the closet's nodes went unmanaged. A grow
  advanced to cold storage now leaves its chamber; a fridge with its own node
  runs it once the session is linked to the fridge's chamber
  (`PATCH /api/chambers/{id}` with `active_session_id`). Grows already in cold
  storage are released from their old chamber at start-up.
- **Rest kept the fruiting lights on.** No light rule covered rest, so a grow
  advanced to rest inside its light window stayed lit for the whole rest.
  Light Scene — Colonization Dark now covers rest; unedited stored copies
  upgrade at start-up.
- **Chambers drove each other's devices.** One chamber's firing put the rule
  in cooldown for every other chamber, whose own fan then never ran; a plug
  role reached whichever plug of that role came first; and a chamber with no
  relay or lighting node published its placeholder rules into nothing while
  the firing read "sent". Cooldowns are now kept per device, a chamber that
  lists its plugs' ids among its node ids drives its own plug of each role,
  and a placeholder rule with no node in its chamber does not fire.
- **A grow in no chamber drove another chamber's fans and lights.** For
  nodes in no chamber, the `relay-01` / `light-01` placeholders reached
  whichever relay or lighting node of the role was seen last, even one a
  chamber running its own grow lists, so a closet grow's FAE or light-scene
  rule switched that chamber's fan or light. They now resolve the way a plug
  role does: a node no chamber lists, else one of a chamber that runs the same
  grow, never one of a chamber that runs a grow of its own; with none, the
  rule does not fire. The smart-plug guide now says to name each chamber's
  plugs after the chamber (`heater-a`), because a hold or a safety lockout on a
  plug whose id is the role's own name pauses that role's rules in every
  chamber.
- **A plug named by role and by id was two devices.** Two rules naming one
  plug the two ways both owned it, and an OFF through one name left a ceiling
  armed through the other running, which then tripped (a false warning and a
  15-minute lockout of a heater already off). The plug is one device now,
  held, timed and switched off under any of its names.
- **The sealed-vessel gate missed a humidifier named by its plug id,** and a
  plug-driven fan escaped the fan gates. Plugs are now judged by their role.
- **A hold on one light channel did not hold the photoperiod.** The scene
  rules rewrote the light during the hold. A hold on any channel of a light
  now holds its scene rules.
- **A relay or lighting node's own frame handed its device to a lower rule.**
  Such a frame carries no climate reading, which counted as the in-force
  rule's condition going false, so the Scheduled FAE Cycle overrode a running
  CO2 FAE Trigger. A frame that cannot judge a condition now keeps the claim.
- **A null or text reading broke rules.** Comparing it raised: the rule was
  skipped and an error logged on every frame, and an OR never reached its
  other branch. Such a reading now simply does not match.
- **One invalid stored rule stopped every rule,** the CO2 Hard Ceiling
  included, and failed the automation-coverage endpoint. It is now skipped and
  logged once.
- **Cron with both day fields set** now fires when either matches, as cron
  does; it needed both.
- **On/off values in rules:** a rule's state and photoperiod are read
  whatever their case (`"ON"` switched a heater on with no safety ceiling,
  `"OFF"` never cleared one), and anything other than `on` / `off` is refused
  with 422 on create or update. A stored unreadable photoperiod no longer
  reads as "off" (an inverted light cycle).
- **Automation coverage** (`GET /api/chambers/{id}/automation-coverage`): a
  channel read available when any node on the Pi had it, another chamber's
  included; it now needs the chamber's own node (a node that has not reported
  its channels yet offers its personality's). Vendor-integration requirements
  read unavailable even with the integration enabled; they now read available
  once it is.
- **Built-in rules an operator deleted came back on the first 5.2 boot.** A
  Pi set up before 5.2.0 kept no record of the built-in rules it had been
  given, so updating to 5.2 added back every built-in missing from its table,
  enabled, including ones the operator had deleted or renamed (the aux mister
  pulsing a repurposed channel, the 06:00 photoperiod fighting a custom light
  schedule, a renamed rule running twice). The server now works out which
  built-ins such a Pi's release seeded and adds only the ones that release did
  not ship; a Pi with no built-in left gets none. An addition is logged as a
  warning. A Pi already on 5.2.0–5.2.2 had them re-added once: delete them
  again and they stay deleted.
- **Pis first set up on 4.x or earlier kept seven outdated built-in rules.**
  Emergency CO2 Exhaust still fired at a fixed 3000 ppm in every phase, and
  as an unscoped priority-20 rule it now counted as life-safety, so it vented
  colonizing grow bags at full power and paged; CO2 FAE Trigger still ran in
  colonization; Scheduled FAE Cycle ignored the profile's FAE interval and
  duration; Light Scene — Colonization Dark re-asserted hourly with no
  photoperiod. Unedited copies now upgrade to the current rules at start-up.
  Light Scene — Fruiting (it re-lit the fruiting scene every hour, through the
  dark period) and the reishi antler and king trumpet primordia CO2 restrict
  rules (replaced by CO2 Floor — Restrict FAE) are switched off once, with a
  warning; switch one back on if you want it. An edited copy is left running
  and named in the log.
- **Heater, cooler and dehumidifier short-cycled at the edge of the band.**
  Their cutoffs switched off at the same edge the triggers switched on at, so
  sensor noise there cycled the plug every few minutes (relay wear; a
  compressor cooler or dehumidifier short-cycling). The cutoffs now switch off
  a deadband inside the band: 1 °F above the minimum / below the maximum, 3 %RH
  below the humidity maximum, never more than a quarter of the band (profile
  refs `temp_heat_off_f`, `temp_cool_off_f`, `humidity_dehumidify_off`).
  Unedited stored cutoffs upgrade at start-up.
- **Rules saved over the cloud relay skipped the Pi's checks.** A rule created
  or edited from the cloud could name an unpaired node or a channel the node
  does not have, and was stored, looked armed and fired into nothing. Rules
  saved over the relay now get the same checks as
  `POST`/`PUT /api/automation/rules`, and the same 422.
- **A rule just switched off, edited or deleted could still fire** for up to
  5 seconds from the engine's rule cache. Every rule change now reaches the
  engine at once.
- **`GET /api/automation/firings`:** a negative `limit` returned the whole
  table; `limit` is now clamped to 1–1000. `rule_id=0` now filters to that id
  instead of returning every rule's firings.
- **A node command's off spelling meant different things to the Pi and the
  node.** `{"state": "false", "pwm": 200}` (or `"0"`, `"OFF"`) went out as
  written: current firmware switched the channel off, firmware from before the
  hardware audit switched it on at duty 200, and the Pi counted it as an ON,
  so a safety ceiling stayed armed and tripped early on the next automation
  ON. Every node command (manual, cloud or rule) now goes out as `"on"` or
  `"off"`, and an OFF of any spelling clears the ceiling.
- **Gen1 Shelly and Tasmota plugs under a multi-level MQTT prefix** looked
  paired while the broker dropped every command and the firing read "sent"
  (only Gen2+ was checked). No command goes to such a prefix any more (the
  firing reads failed), and `POST /api/automation/plugs` refuses such a
  prefix, or an unknown plug type, with 422.
- **A second device on a plug's id could re-point the plug.** Any report for
  the same plug id on another plug type or prefix (a second device claiming
  the id, or anything else using the plug login) re-pointed the stored plug,
  and the Pi's commands, a safety OFF included, went to the wrong device. The
  change now applies only once the stored device has gone quiet (offline, or
  10 minutes without a report), so a Gen1 replaced by a Gen2 still heals; a
  report from a live plug's rival is ignored and logged as a warning.
- **Deleting a chamber that still ran a grow handed the grow to every other
  chamber.** The delete detached the live grow from its chamber, which made
  it "the newest grow bound to no chamber": every idle chamber's nodes and
  every node listed in no chamber then ran its setpoints (light scene,
  humidifier, FAE, heater). `DELETE /api/chambers/{id}` now answers 409 while
  a grow is bound to the chamber or linked to it; end the grow (or unlink it)
  first. Ended grows still outlive the chamber with no chamber set.
- **Linking a session to a chamber accepted links the automation could not
  honour.** `PATCH /api/chambers/{id}` with `active_session_id` took a grow
  bound to another chamber (the dashboards then showed it in this chamber
  while this chamber's nodes ran something else; 409 now), an ended grow
  (shown in the chamber for good; 422 now) and an unknown id (a bare 500;
  422 now). A grow in cold storage can still be linked to a fridge chamber.
- **The cloud kept a session's old chamber name.** Linking a session to a
  chamber, renaming its chamber or deleting the chamber of an ended grow now
  re-sends the session to the cloud; its snapshot names the chamber.
- **Chamber comparison showed only one node per sensor.** With two nodes in a
  chamber reporting `temp_f`, `GET /api/chambers/compare` reported the last
  node's figures alone; each sensor's average, range and count now cover
  every node of the chamber (in one query). Malformed `ids` (`1,abc`) answer
  422 instead of 500, and a trailing comma is ignored.
- **"Mark contaminated" recorded no contamination.** The Sessions page's
  button only aborted the grow, so chamber contamination rates, experiment
  comparisons, the Contamination page, the Prometheus exporter and the cloud
  never counted it. The new `POST /api/sessions/{id}/contaminated` (optional
  `contamination_type` and `notes`) aborts the grow and logs a manual
  contamination event against it and its chamber in one step, and the
  dashboard's button uses it.
- **Chamber photos returned their analyses as JSON strings.**
  `GET /api/chambers/{id}/photos` now returns `analysis_claude` and
  `analysis_local` as objects, as `GET /api/vision/frames` does.
- **The grow report's vision section printed raw JSON.** "Vision Analysis
  Summaries" showed each stored analysis cut at 300 characters, which always
  lost the summary, and listed the grow's ten oldest. It now lists the ten
  newest, oldest first, each with its time, assessment and summary.
- **Frame and session-event lookups scanned whole tables.** Chamber photos,
  the frame list and the harvest check now read `vision_frames` through
  per-camera and per-session indexes, and the dashboard's newest-events
  feeds read `session_events` through a (session, time) index instead of
  sorting a grow's whole history on every request. The old session-only
  events index is dropped on start-up.
- **Contamination photo identify read the whole upload into memory before
  checking its size.** A request sent to the server's own port could pass
  gigabytes and get the server killed. The upload now needs a Content-Length
  of at most the 10 MB cap plus form framing (413 otherwise, 411 without
  one) before the form is parsed, and the image is read only up to the cap.
  An unknown `session_id` or `chamber_id` answers 422 before Claude is
  called, and a Claude rate limit or other API error now answers 502 (some
  answered 500).
- **An off-format identify reply failed a paid identification.** A
  `contaminants` entry that was not an object made the route answer 500, a
  confidence given as a percentage (85) was stored as 85 (the dashboard
  showed 8500 %), and `"contamination_detected": "false"` was logged as a
  detection. A detection is now only a true value, a bare name counts as its
  type, and confidences are stored on the 0-1 scale, as vision detections
  are.
- **Experiments accepted a session compared with itself** (every metric a
  tie) and any status text: `"Completed"` or `"done"` neither stamped the
  completion nor appeared under the completed filter. Both are now 422; the
  status is one of `active`, `completed`, `cancelled`.
- **The planner's expected-harvest marker was invalid iCal.** Its end date
  equalled its start date; it is now a one-day all-day event. A species
  common name with a comma or a newline is escaped in the calendar name (a
  newline failed the whole `.ics` feed).
- **Planned events dated `20261016` or `2026-W42-5` never showed.** Both
  validate as ISO dates but were stored as sent and sorted outside every
  month's range; dates are now stored as `YYYY-MM-DD`.
- **Phase reminders skipped rest and folded pinning.** A rest (or a pinning
  phase the species folds into fruiting) runs on fruiting's setpoints, but
  the overrun reminder looked the phase up directly and never fired; it now
  uses the window of the setpoints the phase runs on.
- **The planner's session warnings called stale weather current.** After the
  weather providers stopped answering, hours- or days-old readings were
  reported as "Current outdoor temp ... Immediate action needed". The
  warnings now use the same freshness rule as the automation and the
  forecast alerts.
- **Harvests and drying weights took any number.** A negative weight was
  subtracted from the grow's yield total for good (there is no harvest edit
  or delete), flush 0 counted as a flush, and a zero or negative drying
  weight announced "Drying Complete". Harvests now need flush 1-50, weights
  of 0 or more and a quality of 0-10 (the cloud's bounds); drying weights
  must be above 0.
- **Unknown ids in a request answered 500.** A note or harvest for an
  unknown session now answers 404; a planned event, an experiment or a
  manual contamination event naming an unknown session, chamber or frame
  answers 422 naming the id.
- **Ending a grow left actuators on.** A rule written for `relay-01` /
  `light-01` was switched off on the node of that kind seen last anywhere,
  not on the chamber's node its ON went to, so the chamber's light stayed on
  its fruiting scene; every node the placeholder stands for is now switched
  off. A grow bound to no chamber that ended while a chamber's grow ran
  switched nothing off; the nodes it ran that no grow runs any more are now
  switched off. A grow parked in cold storage counted as a running grow, so
  ending the closet's grow beside it switched nothing off. Vendor devices a
  rule switched on (Kasa, Tapo and Wemo plugs, Fluence, Fohse and BIOS
  lights, Agrowtek outputs) were never switched off; they now get the OFF
  their safety ceiling sends.
- **An ended grow could be ended or advanced again.** Aborting a completed
  grow (or completing an aborted one) rewrote its outcome and end time,
  logged a second end and switched its actuators off again, and advancing an
  ended grow reopened a phase. These now answer 409 (ending it again the same
  way changes nothing). `POST /api/sessions/{id}/phase` with `complete` now
  completes the grow (ended, actuators off): it set only the phase, leaving
  an active grow managed with no setpoints. A grow can no longer be created
  in `complete`, and of two phase changes made at once the second answers 409
  instead of leaving the same phase twice.
- **A cloud session end for no such grow reported success.** An unknown
  session id, an id that is not a number, or a grow that was aborted now
  reports success=false.
- **Grows on a custom profile whose id mixes `_` and `-` ran unmanaged.** A
  session on `lions_mane-custom` was stored as `lions-mane-custom`, which
  found no profile: no setpoints and no stage alerts for the whole grow.
  Such sessions, new and existing, now find their profile, and a session
  keeps its own profile when another one is the same id spelled differently.
- **Custom species profiles.** A profile whose id is another's other
  separator spelling (a custom `lions-mane` beside the built-in `lions_mane`)
  silently took over every grow of that species: `POST /api/species` now
  refuses it with 409 (an exact duplicate was a 500). `PUT` stored a body
  naming another profile under the path's row, listed under an id nothing
  could reach: now a 422. A profile active grows still run on can no longer
  be deleted (409, naming them). Setpoints automation cannot run (a minimum
  above its maximum, humidity outside 0–100, light hours that do not add up
  to 24, a number that is not finite) are refused with 422: a swapped
  temperature band ran the heater and the cooler against each other.
- **The grow report never listed contamination.** It read contamination
  from session events no detection writes; it now lists every detection
  (vision, identify, a manual mark) with its time, type, source, confidence
  and notes, and recommends accordingly. The fewer-flushes-than-typical
  advice now covers custom profiles too.
- **Drying a harvest never recorded its dry weight.** A harvest dried to
  cracker-dry read "Drying Complete" while its dry yield stayed 0 g in the
  stats, the report, the CSV and the cloud. The weight logged at the
  cracker-dry target, or a later one past it, is now the harvest's dry
  weight, and the session's dry yield is re-summed from its harvests (never
  counted twice).
- **An unreadable substrate volume broke the session pages.** A volume like
  "approx. L" or "1.5.2 l" made the session list, `/stats`, the report and
  experiment comparison return 500, and a long run of digits stalled the
  server. Such text now gives no biological efficiency, "1,5 l" and
  "12 x 1.5 L" read as 1.5 L and 18 L, and `substrate_volume` is capped at
  100 characters.
- **`PATCH /api/sessions/{id}` could not clear a field.** A `null` left the
  growth form, pinning tek or shelf number as they were, so a growth form,
  once set, kept its setpoints for good. An explicit `null` now clears the
  field (the name excepted); a field left out is kept.
- **Species filters missed grows stored in the other id spelling.**
  `GET /api/sessions?species=lions_mane` found no `lions-mane` grow, the
  species averages in `/stats` left out grows stored in the other spelling,
  and cultures were stored and filtered by the exact spelling given. All of
  them now match either spelling, and cultures store the hyphenated id as
  sessions do.
- **Phase reminders and the cloud's phase length for rest.** A rest phase
  (and a pinning phase the profile folds into fruiting) runs on its stand-in
  phase's setpoints; the cloud got no expected length for it, and the
  reminder ignored the session's growth form. Both now use the setpoints the
  phase runs on.
- **Calendar expected dates were a day late west of UTC** for a grow with no
  inoculation date: the projection started on the UTC date the grow was
  created on. It now starts on the Pi's local date.
- **Strict calendar apps dropped the grow calendar's moments.** Session
  start, phase, harvest and end events ended at the instant they began,
  which iCalendar forbids; they now carry no end time.
- **The "process immediately" harvest notice was a pink oyster special
  case.** Paddy straw and shaggy mane, whose harvests cannot wait either, got
  none. The notice now comes from the profile (`harvest_notice`): pink
  oyster, paddy straw and shaggy mane carry one, and a custom profile sends
  its own or that of the built-in profile of the same species.
- **Shopping list.** A log, a cardboard sheet or 5 cubic feet of chips was
  listed once for any number of grows; it now reads "… per grow × N". Giant
  puffball listed "Grain spawn: g", a 100 % grain jar listed 1.5 kg of grain
  spawn on top of its grain, and a log grown from plugs listed grain spawn
  beside them; none does now, and a jar culture lists "Spawn or liquid
  culture".
- **Substrate calculator.** A flour-cake recipe gave two water figures for
  one batch ("0.5 cup" and 0.6 L) and counted its water as dry substrate, so
  the dry ingredients came out a fifth short. Liquids no longer count toward
  the dry weight, and the recipe's water is given once.
- **The shopping list and substrate calculator returned 500** for `inf` or an
  absurd size. `container_liters` and `volume_liters` are capped at 1000 and
  `grows` at 100 (422 beyond).
- **Species wizard.** Species tagged beginner-intermediate or
  intermediate-advanced scored nothing for experience at "some experience",
  an "easy" species read as above a first-timer, and an untagged species read
  as above even an advanced grower (it now reads as intermediate, as the
  cloud shows it). The substrate score divided your picks by the species'
  substrate count, marking flexible species down and reading "3/2"; it now
  counts the species' substrates you can use.
- **`GET /api/species` re-read and re-rendered all 74 profiles on every
  request**, and every telemetry frame re-parsed its grow's profile. Profiles
  are now read once per change; a stored profile that cannot be read is
  skipped and logged instead of failing every lookup.
- **The light toggle on sporeprint.ai switched nothing.** A cloud command
  names a node kind and a channel, and the Pi sent it to the most recently
  seen node of that kind, so the light's `white` channel went to the relay
  bank (which drops it) while the matching manual hold froze the lighting
  node's schedule. On a Pi with two relay nodes (two chambers, or two banks)
  a fan toggle landed on whichever node reported last. A cloud command now
  goes to the one node whose reported channels include it, and the manual
  hold pins that same node; when two nodes could take it, the command is
  refused with the reason instead of guessing.
- **Cloud manual holds for exhaust, circulation, blue, red or far-red were
  refused.** They now register on the node that has the channel.
- **A cloud manual hold with a NaN or infinite expiry never expired.** It
  now falls back to the hold's duration, or to the 24-hour ceiling.
- **Reboot from the cloud reported success and did nothing on the Docker
  install**, which cannot reboot its host. The Pi now refuses it before
  acknowledging, with the reason; on a bare-metal install a reboot that
  `sudo` refuses fails at once and is logged with its exit status.
- **Readings buffered while the cloud link was down arrived as current
  readings.** On reconnect up to 10,000 hours-old frames were shown live in
  the web app and could raise alerts. They are now sent as replayed
  history, stored at their own time.
- **Readings sent into a dead connection were lost.** A link that dropped
  without closing (Wi-Fi loss, a NAT timeout) took readings for up to a
  minute before the Pi noticed, and none arrived. A reading now counts as
  delivered only once the cloud acknowledges it, and unacknowledged ones go
  out again on reconnect. Integration health changes (an integration going
  into or out of error) are likewise retried until the cloud confirms them.
- **A lapsed subscription was never recognised.** The Pi retried every five
  minutes forever and kept filling its buffer. It now shows `paused —
  subscription required`, stops buffering and rechecks every 15 minutes. A
  device token the cloud no longer accepts (the device was removed, or its
  token revoked or rotated) is handled the same way and shows `unauthorized
  — re-pair this Pi with the cloud`.
- **After re-pairing or a token rotation the Pi kept presenting the old
  token** and stayed offline until its server was restarted.
  `/api/cloud/configure` now takes the new
  credentials into use at once and reconnects (its reply says `applied`);
  `/api/cloud/reconnect` retries with the saved credentials.
- **The cloud connector started without `SPOREPRINT_CLOUD_DEVICE_ID`** and
  was then refused on every retry without saying why. It now needs all three
  of URL, token and device id, and names what is missing. While no connector
  runs, readings are no longer queued for it (the full queue logged an
  overflow warning every 100 readings).
- **Connecting failed whenever the cloud took longer than a second to
  accept** the Pi; the Pi now waits up to 10 seconds.
- **The web app showed the Pi's pairing-time version after an update** and
  offered to install the version already running. The Pi's heartbeat now
  carries its server version (`version`), and `/api/cloud/pair-verify`
  reports it too.
- **The fleet view's integration counts stayed empty.** The Pi's
  integrations snapshot now also goes out on its own `integrations_state`
  event, and is sent again every four minutes while connected.
- **Re-sending a Pi self-update for the version already installed deleted
  the running install** before extracting it again, so an interrupted
  extraction left a Pi that could not boot. Every update now extracts into a
  new directory and never touches the running tree. After a successful
  update the Pi keeps the new and the previous tree and removes older ones
  and the downloaded bundles, which each update used to leave on the SD card.
- **A cloud integrations request with a malformed signature or timestamp
  got no answer**, so the web app waited for its timeout. It now gets a 401.
- **Grow sync: a change made offline survives a restart.** An edit made
  while the cloud link was down (a rename, a late harvest weight) to a
  session older than a year, or beyond the 200 newest, was kept only in
  memory, so a restart before the link came back lost it. Pending sessions
  and contamination events now wait in a `cloud_sync_pending` table and go
  out on the next connect, however old they are.
- **Grow sync: reconnects send only what changed.** Every reconnect
  re-uploaded up to 200 sessions and 500 contamination events, one cloud
  write each, even when nothing had changed, and a quick reconnect could run
  a second catch-up beside the first. A reconnect now sends only what
  differs from what the cloud acknowledged (the first connect after the Pi
  starts still sends everything once), and a new connect replaces a
  catch-up left over from the last.
- **Grow sync: the cloud no longer ends on an older snapshot.** Two quick
  changes to one session were sent at once and could arrive in either
  order. The Pi now sends one snapshot of a session at a time and waits for
  the cloud's acknowledgement; a change made meanwhile goes out, freshly
  built, after it. A send counts only once acknowledged, so a snapshot
  handed to a socket that had silently died is sent again instead of lost.
- **Firmware push: a host connecting mid-transfer is refused cleanly.** A
  connection to the callback port from another host while an image was
  already flowing crashed the connect handler with a TypeError instead of
  being refused with the usual warning.
- **Firmware push: a signed manifest is armed right before the
  invitation.** The manifest went to the node before the push waited its
  turn for the callback port, so a push queued behind others for more than
  5 minutes reached a node whose arming had lapsed: the node flashed the
  image without its own check while the Pi said `node_verified`. The
  manifest now goes out once the push holds the port, and a flash the node
  reports without the manifest check ends as `pi_verified`.
- **Hardware routes: no trailing newline in a node id or channel.**
  `relay-01\n` (URL `%0A`) passed validation and was published to a topic
  the node never hears, reported as sent. It is now a 400 on the LAN routes
  and refused in cloud commands.
- **Setup claim can put the node in a chamber.** Claiming only flagged a
  node as adopted; it joined no chamber, so chamber scoping never saw it.
  `POST /api/hardware/claim` takes an optional `chamber_id` that also lists
  the node in that chamber, in the same transaction (404 for an unknown
  chamber).
- **A manual OFF of a vendor device clears its safety ceiling.** Switching
  a Kasa, Tapo, Wemo, Fluence, Fohse, BIOS or Agrowtek device off by hand
  (the integrations actions on the Pi, or from the web app) left the
  `safety_max_on_seconds` ceiling of the rule that switched it on running.
  When the rule switched it back on, the old deadline was kept and the
  ceiling tripped early: a false "Safety cutoff" page and a 15-minute
  lockout of, say, the heater. It is now cleared, as a manual plug OFF
  already did.
- **Vendor action values sent as text are read as the device needs
  them.** Agrowtek's `set_output` passed `"false"`, `"off"` or `"0"` to the
  controller as a string (which a controller may read as on), and a text
  `percent` such as `"50"` failed as a vendor error. Booleans and numbers
  are now parsed for every action — `"false"` is false, `"50"` is 50 — and a
  value a parameter cannot take (`"abc"`, `"nan"`), or a missing required
  one, is a 400. An automation rule whose ON value is text now arms its
  safety ceiling, and the ceiling's OFF matches its type.
- **Vendor failures and caller mistakes get the right status.** A vendor
  reply that is not JSON is a 502 (it was a 400, "your request was wrong");
  a missing parameter is a 400 (it was a 502 "vendor call failed").
- **No "integration degraded" alert on every reboot.** The health sweeper
  treated a driver going from "disabled" (before the drivers start) to "ok"
  as a recovery, and the cloud pushed it as "integration degraded" — on
  every Pi restart and every enable. Only a real incident is resolved now; a
  failing driver counts as recovered once it has been "ok" for three sweeps
  in a row, so a device that fails every other poll is one alert, not one
  every couple of minutes; and the alert carries what the driver reports
  (for example "connect timeout") instead of "degraded health".
- **The integrations page shows each driver's live health.** The status was
  the last Test's result, so a driver whose polls started failing after a
  good Test still read "ok", a disabled driver kept its old "ok", and an
  enabled one never tested read nothing. It now shows the driver's own
  state; a stored secret that no longer decrypts, or a driver saved as
  enabled that failed to start, show as errors.
- **Integration settings errors are a 400 with their message.** A
  validator's rejection (a base URL without `http://`, a malformed email or
  device IP) returned "Internal Server Error". The response no longer echoes
  the rejected values.
- **Saving integration settings is stricter and safer.** `"enabled":
  "false"` (a string) enabled and started the driver; a save without
  `config` reset every field to its default. `enabled` is now read like any
  boolean (junk is a 400), and an omitted `enabled` or `config` keeps what
  is stored. A secret that cannot be stored (it contains characters UTF-8
  cannot encode) is a 400 before the driver sees it, and a save that fails
  puts the driver back on the settings it had.
- **The integration key file can no longer be left empty.** It was written
  without an fsync, so a power cut or a full disk during first use could
  leave an empty file, after which every integrations request was a server
  error until the file was deleted by hand. The key is now written to a
  temporary file, synced and then linked into place, and an empty key file
  is set aside (`.integration-key.empty`) and replaced.
- **Aranet: a base URL whose host starts with "api" is accepted.**
  `http://api-gw.lan` or `http://apiary.local` was rejected ("must include a
  host"); only an `/api/...` path is cut off now.
- **Aranet: Test stores nothing.** It ran a full poll and wrote the
  readings into telemetry history; it now only reads the PRO and reports
  `sensors_seen` and `readings_seen`.
- **Aranet and Pulse store each reading once, at the time it was taken.**
  They serve a sensor's latest reading until the next one arrives (an
  Aranet4 radios every 1-10 minutes), and every poll stored it again at the
  Pi's clock: about ten rows per real reading, and a sensor that had died
  kept looking live. A reading is now stored once, at its own timestamp; a
  sensor whose reading stops changing for 30 minutes (Pulse: 10) turns the
  integration "degraded" and is named there ("error" when all have). A
  temperature reported in °F is converted.
- **Aranet and Pulse tolerate odd entries.** One measurement with no value,
  a numeric sensor or device id, or a malformed entry failed the whole poll,
  Test and Discover with a server error; such an entry is now skipped on its
  own (a numeric id is read as text).
- **Vendor polls write in one transaction.** Every integration stored each
  reading with its own database connection and commit; a poll's readings
  are now written together.
- **Every integration is reported free.** Trane, Fluence and Fohse reported
  `tier_required: "premium"`, which the integrations page showed as a chip,
  although the Pi has no paygate and every driver runs free.
- **Integrations: an unplugged plug shows in health.** Kasa, Wemo and Tapo
  skipped a device that did not answer and still reported the poll as
  successful, so health stayed "ok" (and no integration-health alert went
  out) with every plug offline. Health is now "degraded" while some devices
  fail, naming them under the status, and "error" when all do. A driver
  enabled without the settings it needs (no devices, no email and password,
  no base URL) reports an error instead of an empty "ok".
- **Integrations: one failing plug no longer stops the poll.** A Kasa plug
  that reset the connection, a Tapo plug that was off the network, or a
  device row with no IP aborted the whole poll, so the plugs after it were
  never read. Each device now fails on its own and the rest are polled; a
  Tapo cloud Test on a dead network reports an error instead of failing
  with a server error.
- **Integrations: a command the plug refuses is no longer reported as
  sent.** Kasa and Tapo answer a refused command inside the reply (for
  example `set_dim` on a Kasa plug that is not a dimmer). The write action
  reported success, an automation firing read "sent", and a safety OFF the
  plug refused counted as delivered. A refused command now fails the action
  with 502, like an unreachable plug; Tapo session errors start a fresh
  handshake.
- **Tapo: two commands to one plug at once no longer fail.** A reply was
  decrypted with whichever request had been sent last, so a write that
  overlapped the poll (or a safety OFF) could fail although the plug had
  switched. The driver now talks to one plug one request at a time and
  decrypts each reply with its own request's key stream.
- **Tapo: power readings are in watts.** `power_w` from a Tapo plug with
  `has_emeter` was stored a thousand times too small (a 1500 W heater read
  1.5 W).
- **Wemo Insight readings.** An Insight reports its standby state as `8`
  (and some firmware a pipe-separated state), which the driver rejected, so
  the plug was never read, power included. Both now read as on.
- **Trane, Fluence, Fohse: an expired token no longer fails a poll or a
  write.** On a 401 the driver now logs in again and repeats the request
  once, instead of failing that poll (and the integration-health alert that
  followed) or that write. A login that finished after the account was
  changed no longer installs the old account's token.
- **Cloud vendor logins are not resent every poll after a refusal.** Trane,
  Fluence, Fohse, Tapo (cloud) and Pulse (cloud) sent a refused password
  again on every poll, which can lock the vendor account. A refused login is
  now remembered until the settings are saved again (re-saving the same
  credentials after unlocking the account counts); Test always logs in, and
  network errors still retry every poll.
- **Trane `house_id` must be one id.** It went into the authenticated
  request path unchecked; a value such as `../x?y=` is now refused when the
  settings are saved.
- **Pulse local mode: a device URL with a port.** An entry such as
  `http://10.0.0.5:8080` was turned into an invalid address and every local
  poll failed. The URL's own port is used now (the others use
  `local_http_port`), and each entry is checked when the settings are saved.
- **Grafana: a dead sensor no longer shows as live.** `/metrics` exported a
  node's last reading until retention deleted it a week later. A node's
  gauges now drop out after 15 minutes of silence (a vendor integration's
  after three of its polls), and the `include_sensor_history` setting, which
  did nothing, adds `sporeprint_node_reading_timestamp_seconds`.
- **Grafana: the actuator counter no longer slows every scrape.**
  `actuator_events` gained a row per relay channel every minute and was
  never pruned, and each scrape counted the whole table (seconds on a Pi
  after some months). The lifetime totals are now kept in
  `actuator_event_counts` as reports arrive (started from the rows already
  stored, so the counter does not reset), and the nightly retention prunes
  reports older than 7 days.
- **Grafana: a chamber whose `node_ids` is not a list** no longer turns
  every scrape into a server error.
- **Grafana: `sporeprint_build_info` reports the real version.** It read
  "unknown" in the Docker image, and looked the version up again on every
  scrape.
- **Grafana: an odd bearer token is a 401, not a server error.** `/metrics`
  now uses the API gate's own token comparison, and a token that cannot be
  stored as text is refused when saved.
- **Aranet Discover, Pulse devices and Test after a restart** use the saved
  settings of a disabled integration instead of reporting it unconfigured.
- **A session analysis had no targets to compare against.** `POST
  /api/transcript/sessions/{id}/analyze` asked Claude to judge each phase's
  conditions against the species targets and each phase's duration, but sent
  only the species id: built-in species were judged against generic ranges,
  custom strains against nothing. Each phase now goes out with the setpoints
  it ran on (the ones frozen at phase entry; the profile's own for older
  sessions; a stand-in phase's temperature, humidity, CO2 and FAE bands when
  the phase borrows them) and its expected duration, next to its readings.
- **The JSON transcript double-encoded each phase's targets.**
  `phase_timeline[].params_snapshot` was a JSON string inside the JSON; it is
  now an object, as `GET /api/sessions/{id}` returns it.
- **The Markdown transcript printed "Noneg wet" / "Noneg dry"** for a
  harvest weighed only wet or only dry, and "None" for a vision read with no
  assessment. Unweighed amounts print as `?` and a missing assessment as
  `unknown`. An aborted grow's abort now appears under Key Events.
- **A manual re-analysis could replace a frame's analysis with prose.** When
  Claude answered without a JSON object (a dark or empty frame, say), the
  reply was stored over the frame's last good analysis, dropping its health
  read, so retention could later delete a frame flagged as a concern. Such a
  reply is now returned as an error and never stored, on manual and
  automatic analysis alike.
- **Frame upload stored any body labelled as an image.** A non-image (or a
  GIF) posted to `POST /api/vision/frame` with `Content-Type: image/jpeg` was
  saved as a frame and later sent to Claude, failing the call and using up
  that session's automatic-analysis slot. The bytes now decide: anything that
  is not a JPEG, PNG or WebP image gets 415 and nothing is stored.
- **Large frame uploads and analyses paused the server.** Writing a frame
  (up to 20 MB) and reading and encoding it for Claude ran on the event loop
  that handles MQTT and the rules; both now run in a worker thread.
- **Every frame stored a placeholder "healthy" local analysis.** The local
  CNN is not built, yet each ingested frame got a constant `{"model":
  "stub", "prediction": "healthy", ...}` blob (a second database write per
  frame). Nothing is stored now; the upload's `local_analysis` is `null`, and
  active-learning labels still work.
- **`GET /api/vision/frames/{id}` returned `analysis_claude` and
  `analysis_local` as JSON strings** while `GET /api/vision/frames` returned
  objects. Both return objects now.
- **A long Builder guide through the dashboard's port returned 504.** A
  guide can run to 32,000 output tokens and reaches nginx only once it is
  saved; nginx gave up after 180 s while the server went on to save it, so a
  retry paid for a second guide. `/api/builder/guide` now gets 15 minutes
  (`ui/nginx.conf`).
- **The Builder's Assistant could wire new hardware to unusable ESP32-S3
  pins.** Its avoid list for S3 nodes left out GPIO 47/48 (1.8 V I/O on the
  N32R16V; 48 is the v1.0 board's RGB LED) and GPIO 43/44 (the serial log),
  and said two channel banks took all eight LEDC channels (the node runs one
  bank on channels 0-3). It now lists those pins, names the free S3 pins, and
  on both boards says which free pins can read an analog sensor with WiFi on
  (ESP32 GPIO 4 and 13 are ADC2 and cannot).
- **The Builder's image list fallback named 3 of the 7 firmware envs** when
  `platformio.ini` could not be read; it now lists all of them.
- **The full firmware bundle came back as a README-only ZIP** when the
  firmware tree was missing; it now answers 404 like the per-image bundles.
- **Firmware and model ZIPs were built on the event loop**, pausing MQTT
  ingest and rule evaluation for each download. They are built in a worker
  thread.
- **STEMMA QT cables and Dupont jumpers were filed under "misc"** instead of
  wiring in the BOM, so the build guide's cabling table was never checked
  against them. They are wiring lines now.
- **`scripts/sync_ui_builder_data.py --check` passed with stale wiring
  diagrams.** The dashboard draws every tier-card thumbnail (and the diagram
  shown when the Pi's copy can't be fetched) from SVGs embedded in the
  bundle, which the check never compared; a regenerated SVG kept showing the
  old wiring. The check now compares each embedded SVG with
  `docs/wiring-tier*.svg` byte for byte and asks for a dashboard rebuild on
  any difference.
- Camera analysis no longer pages CRITICAL (and logs a contamination event) when Claude reports "None detected", "No contamination" or a similar "nothing found" type in a healthy read. A detection Claude returns as a list, as a bare type, or as a "contaminated" read that names nothing now pages instead of being ignored, and a confident spot inside an overall-healthy read sends the deduped "Possible contamination" warning rather than a CRITICAL page.
- Pressing "Claude check" on a frame that was already analysed no longer lets the frame confirm its own earlier read, and re-reading an older frame no longer counts as the latest read, so a single image can no longer fire the harvest-window alert. The two-read plateau is now judged per camera, so a second camera that cannot see the fruit no longer blocks the alert.
- A failing alert step during a camera analysis (a database lock held during the nightly retention run, say) no longer throws away the paid Claude analysis: the analysis is stored and the remaining alerts still run, and a failed contamination dedup lookup still records and pages the detection.
- A closet watched only by integration sensors (Aranet, Pulse, Trane and the other drivers report °C) now trains the weather→closet model, so its forecast heat and cold alerts can fire.
- A forecast hour with no temperature or humidity (a provider gap) no longer drops every forecast alert of that poll, and no longer makes `/api/weather/impact` or the planner's session warnings fail with a 500.
- With the NWS fallback serving current conditions, outdoor wind was 3.6× too high (km/h read as m/s); `outdoor_wind_mph` and wind rules now get the right speed.
- Forecast alerts now check every active grow (only the newest session was checked, so a second chamber never got them), use the setpoints its phase actually runs on (a rest phase between flushes runs on the fruiting envelope and was silent), skip grows in cold storage, and send a cold advisory when the closet is predicted 5–10 °F below the minimum.
- `/api/weather/impact` now covers every active grow (each item carries `session_id`, `session_name` and `chamber_id`), reports predicted cold as well as heat on the same thresholds the forecast alerts page on, ignores forecast hours already past (no more "in -6h"), and groups days by the local calendar day (UTC days moved evening hours to the next day and put yesterday evening into today's low).
- The planner's session warnings use the setpoints the phase runs on (a rest phase no longer answers "No parameters for phase 'rest'"), group the forecast by local day and skip hours with no temperature.
- A rest phase's recorded setpoints in the phase history now hold the fruiting envelope with the lights off instead of nothing.
- `SPOREPRINT_WEATHER_PROVIDER` and the Settings weather provider are now honoured: the chosen provider is tried first and the others take over when it fails (OpenWeatherMap only when its API key is set). An unknown provider name is refused.
- A weather poll interval of 0 or less no longer makes the poller re-poll back to back and mark every reading stale (which kept outdoor values from the rules): Settings refuses a value below 1 or a non-whole number, and an environment value below 1 is treated as 1 minute.
- **Automation page: a rule held from a chamber page still showed as
  "active".** The chamber page pins the chamber's real node
  (`node-xxxx:fae`), and a plug can be held by its id or by its role, while
  the seeded rules name the `relay-01` / `light-01` placeholders and a plug's
  role. The engine already kept those rules off the held actuator, but the
  page matched a hold only against the rule's own target name. Each rule in
  `GET /api/automation/rules` now carries `held_by`: the holds the engine
  honours for it, found the way the engine resolves the rule's target in each
  chamber (a hold on a node the placeholder never resolves to is not listed).
  The page shows those rules as suspended, says where each hold sits ("on
  node-a1b2:fae"), and "cancel suspend" clears them. The cloud's rule list
  carries the same field.
- **Shopping List: an amount needed per grow was undercounted when two
  species needed it.** The Pi marks a count or dimension that is one grow's
  worth ("4x4 foot sheet per grow × 3"); merged across two species, two
  identical lines showed once ("× 3" where six grows need "× 6"), and
  different grow counts were only joined. The merged line now adds the grows
  ("4x4 foot sheet per grow × 5"); a list for one grow, which carries no
  mark, counts once; different amounts per grow in one unit add up to a
  total ("21 cubic feet"); anything else is shown as it is.
- **Vision: the empty "Recent frames" panel pointed at the wrong
  transport.** It said cameras push frames over MQTT; cameras upload each
  capture to the Pi over HTTP (`POST /api/vision/frame`), which is the
  connection to check when a camera shows online but sends no frames.
- **Dashboard: a tab left open across a Pi update showed a broken page.**
  Its first lazy load (the Builder's wiring diagrams) asked for a file the
  update removed. The tab now reloads once onto the new build; a file
  missing from the new build too does not reload it again within a minute,
  so it cannot loop.
- **Re-running install.sh never replaces the broker's CA.** With the server
  certificate missing (deleted to get a fresh one), install.sh generated a
  new CA, and every node using Secure MQTT then failed TLS and stayed off the
  broker until it was factory-reset. It now re-issues the certificate from
  the existing CA, stops with instructions when the CA's key is gone, and
  moves the new key and certificate in only once both exist. setup.sh does
  the same.
- **The broker certificate is renewed before it expires.** Nothing renewed
  the five-year server certificate. A re-run now re-issues it from the same
  CA when it expires within 30 days, and warns a year before the CA itself
  expires.
- **Nodes in a room without internet can take their time from the Pi.** The
  setup portal and the docs point those nodes at the Pi for NTP, but the Pi
  answered no NTP clients, so a node holding the command-signing key refused
  every command. install.sh now installs chrony (replacing
  systemd-timesyncd) and lets it answer NTP from private addresses, from its
  own clock when it has no upstream either (udp/123: open it on a firewalled
  Pi). A host where chrony cannot be installed is told what that means.
- **install.sh no longer reports success while the server is off the
  broker.** It declared "SporePrint is running" from `/api/health` alone,
  even when the server's broker login failed (no telemetry, rules or
  commands). It now waits for the broker to accept the server's login and
  for the server's own MQTT stats, and otherwise prints the broker log and
  the fix instead of the success line.
- **Adding a key to an `.env` without a final newline no longer corrupts
  it.** The new key was glued onto the last line, changing that setting (an
  API key, say) and losing the new one. Every writer now ends each line, and
  values are read from `.env` the way docker compose reads them, so a quoted
  password is no longer hashed into the broker's password file with its
  quotes.
- **The broker starts from a checkout made under a strict umask.** Under
  umask 077, `acl.conf` and the certificates directory were unreadable to the
  broker's user and it crash-looped. install.sh and setup.sh now make them
  readable, and install.sh works under umask 022.
- **The server healthcheck is cheap.** It started a shell and a Python that
  imported `urllib` (with its ssl and email modules) every 10 seconds; it is
  now a bare socket probe of `/api/health`.
- **The automation docs no longer claim the rules read `light_spectrum`.**
  No rule does: Photoperiod — Lights On sends `fruiting_standard` whatever the
  profile asks (shiitake fruiting's blue emphasis included), and only
  Cordyceps Blue Light switches to a blue scene.
- **`rotate-mqtt-creds.sh` no longer cuts off the smart plugs unasked.** A bare run also rotated `sp-3p`: the broker reload dropped every plug, its relay stuck as it was and out of the server's reach, until the new password was typed into each one, and the script never showed it. The plugs' login is now rotated only with `./scripts/rotate-mqtt-creds.sh sp-3p`, which prints the new password and says the plugs stay off the broker until it is entered.
- **A failed broker edit no longer locks the server out after `rotate-mqtt-creds.sh`.** `.env` got the new passwords before the broker's password file did, so when that edit failed the server came back with a password its broker did not know. The password file is now updated first, and `.env` is changed only once that succeeded.
- **`generate-ota-keypair.py` no longer says the verify key does nothing on a Docker install.** Every install checks signed node-firmware manifests against it, and a firmware push that carries one is refused on a Pi without it; only Pi self-update is bare-metal only.
- **A Pi update reaches an open browser without a stale or blank dashboard.** `index.html` is now revalidated on every load (it could be served from cache, still naming the previous bundle), the content-hashed `/assets/` files are cached for good, and a missing bundle file is a 404 instead of `index.html`, which the browser rejected as a script.
- **`setup.sh` installs the server's locked dependencies.** It ran an unlocked `pip install -e ./server[dev]` into a root `.venv` on whatever Python the host had; it now runs `uv sync --python 3.12 --extra dev` in `server/` (uv is now a prerequisite). Its dead Node.js check and UI-dependency step (`ui/` has no `package.json`) and the unused `data/` directories are gone, its closing notes no longer claim the server refuses `.env` keys it does not know, and it writes the Claude key and weather location through the shared `.env` helper, refusing a key with characters an API key never has and a latitude or longitude that is not a number in range.
- **Tilting the sensor bracket's platform no longer detaches it.** A non-zero `tilt_angle` rotated the platform about its far corner, lifting the end that overlaps the arm clear of it: the render exported two loose parts. The tilt now raises the platform's outer end, pivoting where the arm holds it, and is limited to 0–30°.
- **`esp32_case` board overrides now do what the header promises.** `usb_conn_w`, `usb_conn_d`, `usb_overhang` and `module_w` size the lid's hold-down pads, and the render stops with a message when `pin_row_spacing` puts the header rows over the support ribs or `plug_w`/`plug_h` will not pass the USB opening. The four presets render the same parts as before.
- **`models/README.md`: the sensor bracket takes the enclosure's wall as `enc_wall`.** The README (and a `sensor_mount.scad` comment) said to pass `wall` identically to both files, but the bracket's `wall` is its clip ring: the saddle inserts then missed the enclosure's ear holes. The fan duct's retention line no longer calls the BOM's ties 14" (they are 18"; a 14" tie is too short).
- **A command too large for the node is reported as not sent.** The Pi
  published command frames the node drops unread (1024 bytes or more, even
  without destination binding) and answered "sent"; it now refuses them
  (503) and logs why.
- **Lighting level reports no longer run the sensor path.** Every level change
  and ramp step from a lighting node went through session lookup, a storage
  attempt, weather enrichment and a full rules pass. They are now shown and
  forwarded live only; the node's periodic telemetry still drives the rules,
  schedules included.
- **A node's refusal of an OTA push is reported.** The push status said "node
  accepted the invitation but never connected back" when the node had turned
  the image down (signed-manifest gate, an image on probation, an image too
  large). It now says "node refused the push: <reason>", from current
  firmware's `ERR` answer and from older firmware's MQTT error event.
- **Ending a grow switched off actuators the operator was holding.** A
  manual hold keeps an actuator as it is when the grow ends, but the end of
  a grow read a hold more narrowly than the rules do: a light with one
  channel pinned from the chamber page (a hold that keeps the light's scene
  rules off it) was sent the all-off scene, and a plug held by its id was
  switched off through a rule naming its role (or held by its role and
  switched off through a rule naming its id). The end of a grow now reads a
  hold exactly as the rules do.
- **Ending a grow left a chamber's own plug on.** A chamber that lists its
  plugs among its nodes drives its own plug of a role (each chamber its own
  heater or cooler), but the end of the last grow switched off only one plug
  of each role, and a chamber's grow that ended while another chamber's grow
  ran switched none. Now the end of the last grow switches off every plug of
  the role, and a chamber's own plugs go off once no grow runs that chamber.
- **A grow on nodes in no chamber could switch another chamber's plug.**
  Where chambers list their own plugs, the rules run for nodes listed in no
  chamber (a grow bound to no chamber) drove the plug of the role paired
  first, even one a chamber lists: the closet's cold reading switched on
  chamber A's heater while the closet's own heater stayed off. They now
  drive a plug no chamber lists; with none of the role, the plug of a
  chamber that runs the same grow (one with no grow of its own), never one
  of a chamber that runs its own grow. A fallback rule that runs while a
  plug is missing (vent while no dehumidifier is paired) now sees it missing
  there too.
- **A plug named after its role was every chamber's.** A plug whose Tasmota
  Topic or Shelly prefix is its role has the built-in rules' target as its
  id (`plug-heater`), and every chamber's rules drove that one plug, so a
  second chamber's heater (another Topic, given the role `heater`) never
  ran. That plug now counts as one of the role's plugs: each chamber drives
  its own.
- **Ending a grow left a plug on that no grow drove any more.** While
  another grow ran, the end of a grow switched off only plugs a chamber
  lists, so a plug no chamber lists stayed on even when no remaining grow
  could drive it (the closet's own heater, beside a chamber with its own).
  The end of a grow now switches off every plug its rules reached that no
  remaining grow's rules reach, and the end of the last grow also switches
  off a plug named after its role along with the role's other plugs.

### Security

- **A pairing session now belongs to the device id the Pi handed out.** An
  unpaired Pi's `GET /api/cloud/pair-verify` reported an empty
  `cloud_device_id`, so the caller couldn't check which device the session
  was for, and `POST /api/cloud/configure` took credentials for any id. The
  Pi now records the id `POST /api/cloud/pair` returned, pair-verify reports
  it, and configure refuses a different one (400).
- **Pairing put the whole API on the public internet.** The cloud's calls back
  to the Pi while pairing or rotating the device token
  (`GET /api/cloud/pair-verify`, `POST /api/cloud/configure`) carry no API key,
  so in API-key mode they got 401 and pairing could never finish. It only
  worked in LAN-trust mode, with every route (actuators, settings, the Claude
  key) open on the temporary public HTTPS address pairing needs. Both routes
  now answer without the key; they still refuse anything but the single-use,
  10-minute configure token that the code-gated `POST /api/cloud/pair` issues.
  The pairing steps (README → Pairing a Pi, `docs/auth.md`) now switch on
  API-key mode for that window and mint the pairing code with curl.
- **A web page you visited could change things on the Pi and read its live
  stream.** In LAN-trust mode any site open in a browser on your network could
  send body-less requests to the Pi's LAN name (abort or complete a session,
  mint a new pairing code, start a paid Claude analysis), and the Socket.IO
  server accepted every origin, so such a page could open and read the live
  telemetry, alert and log stream. A `POST`, `PUT`, `PATCH` or `DELETE` whose
  browser `Origin` is not the dashboard's own host or a name the Host
  allow-list admits now gets 403, the Socket.IO handshake checks the `Origin`
  the same way, and the deprecated `GET` form of experiment analysis is
  refused when a page on another site loads it. Requests without an `Origin`
  (curl, scripts, cameras, the cloud's pairing calls) are unaffected.
- **The server image ran unverified build tools.** Every image build upgraded
  pip to whatever PyPI served that day and installed uv by version only, both
  as root, ahead of the hash-checked dependency install they drive. The build
  now uses the pip of the digest-pinned base image and installs uv only as
  the exact files hashed in `server/requirements-build.txt`.
- **`GET /api/settings` returned the Claude and OpenWeatherMap API keys in
  full** (and so did every settings `PUT`/`DELETE` answer), readable by any
  device on the LAN in the default LAN-trust mode. A credential now comes back
  only as a fingerprint, with an added `is_set`.
- **A node could put events in a sibling's name.** A `node_id` inside a node's
  own payload overrode the node named by its topic (the identity the broker's
  per-node ACL checks) in the live dashboard events and in what is forwarded
  to the cloud; the topic's node id now always wins.
- **Unsigned cloud integrations requests are rejected by default.**
  `SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS` now defaults to `true`: the
  cloud signs every request, and this channel can create automation rules
  and switch vendor devices. Before, a freshly paired Pi accepted unsigned
  requests until it had seen a signed one. Setting it to `false` restores
  that behaviour.
- **Signed cloud commands: a NaN `ts` no longer escapes the replay
  window.** Every comparison with NaN is false and Python's JSON reads NaN,
  so such a frame never expired and could be replayed once the replay cache
  forgot its id. A `ts` that is not a finite number (NaN, ±Infinity, a
  boolean) is now refused.
- **Firmware push: another host at the node's address can no longer fake a
  flash.** The push goes to the IP from the node's last heartbeat and
  espota cannot prove the peer is the node. The Pi now refuses a push to a
  node that is offline or quiet for more than 10 minutes (409), refuses a
  host that answers the invitation without asking for the OTA password, and
  reports a push as done only once the node's own `success` event arrives
  over MQTT, which only its broker login can publish.
- **Firmware push: a signed image must fit the kind of node.** The
  manifest's image was never matched to the target. A camera image (`cam*`)
  is now refused for a climate, relay or lighting node, and a node image
  for a camera (400), so a node built without the verify key cannot be
  handed the wrong one.
- **Grafana `/metrics` stays closed when its bearer token cannot be
  decrypted.** After the integration key was lost or replaced (a database
  restored to a new SD card without `.integration-key`), the token read as
  empty and the exporter started with no bearer check, serving every gauge
  to anyone. An integration whose stored secret no longer decrypts is now
  not started at boot, and enabling it (or saving it as enabled) is refused
  with 409 until the secret is re-entered.
- **Secret previews no longer show any of the secret.** The integrations
  listing and config showed the last four characters of every password,
  API key and token — a whole secret of four characters or fewer — and the
  listing is also sent to the cloud. They now show `••••` plus a six-digit
  fingerprint keyed by this Pi's integration key: the same secret keeps the
  same preview, so you can still tell whether it changed, and sending the
  preview back still keeps the stored secret.
- **A secret that no longer decrypts is never overwritten.** Enable,
  disable, and saving other fields used to store an empty value over it, so
  restoring the original key file afterwards could not recover it (and the
  "re-enter the credentials" warning vanished). Enable and disable now
  change only the flag, a save keeps that secret's stored ciphertext unless
  you enter a new value (or clear it with `""`), and settings show it as
  `••••` until it is re-entered.
- **The firmware bundles and `GET /api/builder/firmware/platformio.ini`
  published upload credentials** written into the Pi checkout's
  `platformio.ini` (an espota `upload_flags = --auth=…`, an `upload_port`,
  a password in `build_flags`) to any LAN client, though the same lines in an
  `extra_configs` ini are kept private. Those options (and commented-out
  copies) are now replaced by a "withheld" comment in everything the Builder
  serves; the rest of the file is published unchanged.
- **Each smart plug can have its own broker login.** Every plug logged in as
  the shared `sp-3p` user, whose password sits in each plug and on its
  (usually unprotected) web page, so one plug's password could switch every
  other plug and fake their states. `./scripts/add-plug-mqtt-user.sh <name>`
  (the plug's Tasmota Topic or Shelly role) now creates a login the broker
  limits to that plug's own `tasmota/<name>/…` and `shellies/<name>/…`
  topics, lists it in the new `SPOREPRINT_MQTT_PLUG_USERS` (the server never
  takes node frames from those names) and recreates the server. Plugs already
  set up with `sp-3p` keep working. The server also ignores plug state
  published under a broker service account's name.
- **Broker passwords no longer show in the process table.** The broker
  healthcheck ran `mosquitto_sub -P <server password>` every 10 seconds, and
  install.sh, setup.sh and the broker scripts set passwords with
  `mosquitto_passwd -b`: any local user on the Pi could read them from `ps`.
  The healthcheck now logs in from a private options file on tmpfs, every
  script hands passwords to `mosquitto_passwd` on stdin, and `.env` values
  are written without going through a command line.
- **The stack's ports are published on IPv4 only.** Docker also published
  every port on IPv6, where no NAT hides a Pi with a global address: the
  unauthenticated API, the dashboard, MQTT, ntfy and the OTA callback port
  were guarded only by the router's IPv6 firewall. They now bind `0.0.0.0`.
- **A new install gets an ntfy topic nobody can guess.** The bundled ntfy
  server has no logins, so on the default topic `sporeprint` anyone on the
  network could read the alerts or post fake ones to the operator's phone.
  install.sh now writes a random `sporeprint-<hex>` topic on a new install
  and prints it; an existing install keeps the topic its phones use and is
  warned while that is still the default.
- **Other sites can no longer frame the dashboard.** The LAN dashboard switches actuators with no login, and nothing stopped a web page from loading it in a hidden frame and turning a visitor's clicks into commands. nginx now sends `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'` on every response.
- **`add-node-mqtt-user.sh` refuses the broker's service accounts.** Given `server`, `sp-3p`, `sp-cmd`, `sp-telemetry` or the server's own `SPOREPRINT_MQTT_USERNAME` (in any case), it gave that account a new password and reloaded the broker, cutting the Pi server, or every smart plug, off MQTT while `.env` kept the old password. It now stops and points to `rotate-mqtt-creds.sh`. A plug's own login listed in `SPOREPRINT_MQTT_PLUG_USERS` is refused the same way.
- **`setup.sh` keeps `.env` private from the start.** The Claude key went into a copy of `.env.example` that every local user could read until the very end of the script, so stopping at a later prompt left it that way. `.env` is now made 0600 as soon as it is created.

## [5.2.2] - 2026-10-07

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [5.2.1] - 2026-10-07

### Changed

- **README:** rewritten as the front door for the free install. It covers
  what is open source and what is not (the Pi dashboard ships as a pre-built
  bundle), install, update and pairing, which integrations are untested on
  hardware, and the education-and-research notice wherever the active
  category is mentioned. `server/tests/test_readme_front_door.py` pins
  those claims to the code.

## [5.2.0] - 2026-10-07

### Added

- **Grow sessions and contamination events reach the cloud.**
  `app/cloud/session_sync.py` sends each session's snapshot after every
  change: create, edit, phase advance, harvest, complete or abort. Every
  recorded contamination event (vision, identify, manual) is sent as it is
  recorded. Anything unsent is resent on reconnect, and every connect
  backfills the last year, so the cloud's sessions, analytics, planner,
  chamber tiles and contamination history fill from real grows. See
  [`docs/cloud-relay-flow.md`](docs/cloud-relay-flow.md).

### Fixed

- **The cloud connector could not connect.** python-socketio's asyncio
  client needs aiohttp, which nothing installed, so every connect failed.
  The Pi now depends on `python-socketio[asyncio_client]`.
- **Pis seeded by an older release never got newer built-in rules.** CO2
  Hard Ceiling and CO2 Floor — Restrict FAE were missing on those Pis. Each
  built-in is now offered once, and a built-in the operator deleted stays
  deleted.

## [5.1.2] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [5.1.1] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [5.1.0] - 2026-10-06

Two passes since 5.0.0. The **2026-09 hardware + software audit**: a live
re-check of the whole bill of materials, every enclosure re-fit to sourced
part drawings and joined with heat-set inserts, and ~180 verified software
findings fixed test-first across the server, firmware, broker/install scripts
and dependencies. The **2026-10 follow-ups**: Arduino-ESP32 core 3.3.12,
drivers for every sensor the BOM ever listed, the ESP32-S3 camera boards,
Shelly Gen2+ plugs, the shiitake browning phase, coredump acknowledgements,
and signed OTA manifests for the Pi and (optionally) for nodes. The wire
contract stays backward compatible: new payload keys are optional and the
signing vectors are unchanged. Firmware details are in
[`firmware/CHANGELOG.md`](firmware/CHANGELOG.md).

### Upgrade notes
- **Update a Docker Pi with `git pull && ./install.sh`** — `install.sh` writes
  the new `.env` keys; `git pull && docker compose up -d --build` alone does
  not. `install.sh` run inside a checkout no longer pulls by itself.
- **Secure MQTT nodes on the plaintext fallback start pinning the CA.** Under
  Docker `GET /api/provision/ca` used to return 404 (the server container had
  no `ca.crt`), so every node with Secure MQTT ticked ran on plaintext. Run
  `./install.sh` before the nodes see the new server: it re-issues the broker
  certificate with every Pi IPv4 in its names. Current firmware pins a fetched
  CA only after a TLS connection with it succeeds and otherwise stays on
  plaintext with a `tls_downgrade` alert that names the reason. **Firmware
  from 5.0.0 or earlier pins the CA at its next reboot without that check:**
  if the certificate does not cover the node's Pi address (an IP the old
  certificate lacks), that node loses MQTT, drops to safe mode after 10 min,
  and needs physical access (portal gesture or factory reset). Point nodes at
  `sporeprint.local`, or update their firmware first.
- **Schedules move to local time.** `install.sh` writes the host's time zone
  into `.env` as `TZ` (compose passes `TZ=${TZ:-UTC}`) and warns. Rule times
  typed in UTC to compensate must be changed back, or set `TZ=UTC`. Use a
  canonical Region/City name: the server image has no legacy aliases, and an
  unknown zone silently runs on UTC. Bare metal: set `TZ` in the service
  environment, not in `server/.env`.
- **Command signing is on by default.** `install.sh` generates
  `SPOREPRINT_MQTT_HMAC_KEY` (reusing one an older `provision-node.sh` left in
  `server/.env`). A cloud-paired Pi without a key refuses every node command,
  so run `./install.sh` or `./scripts/provision-node.sh`, then
  `docker compose up -d server`, before pairing.
- **The database moves to incremental auto-vacuum** with one full `VACUUM`
  (duration logged). A database up to 32 MB converts at the end of startup,
  after MQTT, the rules engine, the re-armed safety watchdogs and the vendor
  drivers are running. A bigger one is not rewritten at boot (that stalled
  ingest and safety for minutes on an SD card): the nightly retention window
  converts it once at least a quarter of the file is free pages. The
  conversion needs free disk of 2 × the DB size + 64 MB; otherwise it is
  skipped with a WARNING and retried.
- **Tasmota plugs need Full Topic `tasmota/%topic%/%prefix%/`** and the `sp-3p`
  login. Plugs on Tasmota's default Full Topic never reached the Pi.
- **Coredumps moved** to `<DB dir>/coredumps` (Docker: `/data/db/coredumps`, on
  the data volume). Dumps in the old `data/coredumps` are no longer listed.
- **Built-in species profiles are read-only** (`PUT` returns 409): clone one to
  customize it.
- **Node firmware moves to core 3.x over the air.** Push the new image from
  the dashboard's Firmware page as before: nodes on a core 2.x image (every
  release up to 5.0.0) take the first 3.x image with no USB cable. Update one
  node per board type and check its heartbeat before the rest
  ([`firmware/README.md`](firmware/README.md#updating-nodes-from-a-core-2x-image)).
  Building firmware now needs PlatformIO Core ≥ 6.2.0 and `git`.
- **Bare-metal Pi self-update checks a signed release manifest** (see *Cloud
  and Pi self-update*). A bare-metal Pi that takes beta or dev builds must set
  `SPOREPRINT_OTA_CHANNEL`. The legacy bundle `.sig` is still published, so
  older Pis keep updating; a current Pi accepts a release that has only the
  legacy `.sig` (published before manifests) only with
  `SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE=true`.

### Hardware and the Builder BOM (`GET /api/builder/tiers`)
- **Tier totals are now ~$290 / ~$745 / ~$960** (were ~$180 / ~$390 / ~$555),
  re-checked live on 2026-09-27, and now include the cabling, consumables,
  heat-set inserts and screws. A second chamber adds ~$62 / ~$316 / ~$527
  (the Pi side once, kits and spools in whole packs). They exclude the
  tri-spectrum strip's shipping and duty (~$10+) and tools. README and the
  build guide use the same numbers.
- **Cabling standard + consumables as BOM lines:** a UL-listed surge strip
  outside the chamber (6 / 12 / 12 + 2 USB-A outlets); 12 V distribution as
  14 AWG barrel pigtail → WAGO 221-413 (+12 V split) / 221-415 (GND join) →
  one inline ATC fuse per branch (relay 3 A; lighting 5 A on Recommended,
  7.5 A on All the Things) → the switch boards, every 12 V run in 18 AWG
  red/black; Noctua NA-SEC3 fan extensions (far end cut, pin 2 → J2 "+",
  pin 1 → J2 "−"); 22 AWG hookup wire for gate / GND jumpers; 22 AWG
  4-conductor runs for the HX711 (red 3V3 / black GND / yellow DOUT / white
  SCK) and the door contact; food-grade 2 × 4 mm pump tubing; adhesive-lined
  heat-shrink, UV zip ties, 18" (457 mm) duct ties, a VELCRO ONE-WRAP roll, a
  grommet kit, lead-free solder, and heat-set insert + stainless screw kits
  (ruthex M3 or M2–M5 assortment, uxcell M2.5). In-chamber boards get 6 ft USB
  cables (USB-C climate, micro-USB camera MBs). New optional field
  `Component.shared` and categories `wiring` / `hardware`; the wiring rows
  come from `_power_rows()`.
- New lines: Raspberry Pi Active Cooler (all tiers); Adafruit 4397 + 4210
  STEMMA QT cables (the climate node is now a no-solder daisy chain, replacing
  the M-F jumpers); USB-A to USB-C cables, USB-A to micro-USB cables (camera
  MBs) and UL-listed 5 V chargers — one per board; 100 Ω gate resistors;
  KF301-2P screw terminals for `relay_board_mount`; Dupont jumpers; a
  5.5 × 2.5 mm DC pigtail (Tiers 2/3).
- Changed lines: Pi 5 4GB $110 (PiShop), official 27 W PSU, 64 GB A1 card;
  ESP32-WROOM-32 is the narrow USB-C board (3-pack / 6-pack value options);
  ESP32-CAM is an AI-Thinker 2-pack **with ESP32-CAM-MB programmers**
  (OV2640, or OV3660 — both supported); flyback diode is the **UF4007**
  (1N4007 only on on/off channels); 5 m white roll; IP67 tri-spectrum strip
  with wire colours documented (blue 450 / red 660 / green 730); Facmogu 12 V
  5 A (Tier 2) and **10 A** (Tier 3) bricks with load budgets (≤ ~4 A / ≤ ~8 A);
  HX711 is Adafruit 5974 + 4541 (rate switch at 10 SPS); the reed switch is a
  weideer MC-31B wired **COM + alarm-NC**; Athom Tasmota US Plug V2 (Tasmota
  build, not the ESPHome twin).
- Quantities: IRLZ44N 6 / 8, 10 kΩ 6 / 9, diodes 4 / 4 (inductive channels
  only), Tasmota plugs 1 / 2 / 4.
- **The ESP32-S3 camera boards of earlier BOMs are supported again:** the
  camera's BOM note and the Builder's Assistant context no longer call them
  unsupported (the BOM still recommends the AI-Thinker ESP32-CAM; firmware
  below).
- **Whole packs, counted per chamber.** Every pack line has one shape:
  - New optional API fields `Component.pack_price` and `Component.pack_size`.
    `quantity` counts the units a tier needs per chamber, `price_approx` is
    the per-unit price inside the pinned pack, `pack_price` that pack's price
    and `pack_size` its units; N chambers buy `ceil(quantity x N / pack_size)`
    packs (`Component.line_cost(chambers)`, `HardwareTier.parts_cost(chambers)`),
    and `shared` lines never multiply. The camera 2-pack, USB charger 2-packs,
    1 ft USB-C 3-pack, micro-USB 2-pack, NA-SEC3 3-pack, DC pigtail 2-pack,
    KF301 30-pack and door-contact 2-set used to count packs (so ×4 chambers
    bought 8 cameras for 4), and the ESP32 / IRLZ44N / resistor / diode packs
    were bought once per chamber (×4 bought four 100-packs of resistors).
    All the Things now lists 4 ESP32 boards (the 6-pack leaves 2 spares)
    instead of 6. The inline fuse holders are two per chamber from a 10-pack
    instead of a shared line.
  - **Kits and spools the chambers use up are per-chamber pack lines** (new
    optional API field `Component.shared_units`). They used to be `shared` —
    bought once whatever the chamber count — so a multi-chamber shopping list
    under-bought from ~3–4 chambers up: the WAGO 221 assortment (3 × 221-413 +
    3 × 221-415, one of each per chamber) stayed one kit at ×4 and ×12, and 12
    All the Things chambers got one ruthex assortment (100 M3 inserts) for
    436. Now `quantity` counts what one chamber takes — inserts and screws
    from the `models/README.md` shopping list (a mixed kit counts the size the
    chambers use up first: M4 inserts on Recommended, M3 on All the Things;
    M2.5 × 6; M5 × 16; the M4 × 30/35/40 fan-duct screws), WAGO 221-413 +
    221-415 pairs (3 per assortment), fuse sets (15 per box), M-F Dupont
    jumpers (40 per kit), VELCRO 12" straps (12 per roll), 18 AWG pair by the
    foot (~20 / ~35 ft a chamber), the 22/4 cable (~12 ft), 22 AWG hookup
    (~2 ft of black) and solder by the gram (~5 / ~7 g) — and `shared_units`
    is the Pi case's share of the same pack (4 M2.5 inserts, 4 M3 inserts,
    4 M2.5 × 6), bought once: N chambers buy
    `ceil((quantity × N + shared_units) / pack_size)` packs. The bulk
    consumables are per-chamber pack lines too — zip ties, heat-shrink, large
    grommets and 18" duct ties (one per fan, of 100) — since one pack covering
    the 12-chamber preset still under-bought from 17 of the Builder's up to
    99 chambers. Only the Pi side and the bench breadboard stay shared (and
    Bare Bones' screw kit, which only the Pi lid draws on). The docs'
    "reusable kits" share (every shared line except the Pi side) is replaced
    by what a second chamber adds: ~$62 / ~$316 / ~$527.
  - **Mixed consumable kits are counted per size**, from the pinned listings
    (re-read 2026-10-05). **Heat-shrink**: the 400-piece kit holds only
    12 × ½" and 12 × ¾" pieces, and each 12 V chamber uses one of each over
    its two strip joints, so the line counts ¾" pieces (one kit covers 12
    chambers, not 16-26). **Zip ties**: 100 each of 4" / 6" / 8" / 12"; each
    tier counts its scarcest size from the printed parts' tie slots and its
    cable runs (one pack covers 33 / 11 / 7 chambers, not 16). **Grommets**:
    the kit has 10 open 7/8" / 1" grommets (the other 8 large ones are closed
    plugs), so one kit covers 10 chambers, not 20. **M4 kit**: its 75 flat
    washers now cover hx711_scale's 4 DIN 125 washers (the last uncounted
    fastener). Every size is checked at 1-99 chambers.
  - One-chamber totals are unchanged throughout. At ×4 / ×12 chambers the
    tiers come to $484.60 / $1,060.80, $1,733.38 / $4,644.18 and
    $2,613.78 / $7,180.87 (the ×12 totals include a second grommet kit, $13,
    and on Recommended / All the Things a second zip-tie pack, $13).
- **Setup steps**:
  - All tiers: `install.sh`; `./scripts/add-node-mqtt-user.sh <node_id>`
    before the portal, Node ID left blank; Tasmota User / Password / Topic /
    Full Topic (the step names the topic the default Full Topic publishes,
    `stat/<topic>/POWER`); ESP32-CAM-MB flashing (hold IO0, tap RST if the
    upload won't start); print presets per part; heat-set insert and screw
    counts per tier; PSU load budgets; the S3 pin map wherever
    `node_esp32s3` is named.
  - The smart-plug step also covers a Shelly Gen2+ plug (Plus, Gen3, Gen4):
    MQTT on, server = the Pi on port 1883, user `sp-3p`, MQTT prefix
    `shellies/<role>`, and both "RPC status notifications over MQTT" and
    "Generic status update over MQTT" on.
  - The PlatformIO step says `pip install -U platformio`, PlatformIO Core
    6.2.0+ and git, core 3.3.12 and the ~1 GB first build (every tier said
    only `pip install platformio`).
  - The steps name the Builder's current tabs (Firmware, Models) and the
    dashboard's Hardware page, and check a smart plug with
    `GET /api/automation/plugs` — the dashboard has no plug panel.
  - Every shell command, file path, JSON payload, MQTT topic, env name and
    config key is wrapped in backticks (`` `like this` ``), so the Builder can
    show them as copyable code; component notes and wiring rows stay plain.
    `tests/test_hardware_guides.py` checks that each marked span exists in
    the repo: scripts (and that they are executable), pio envs, compose
    services and published ports, `/api` routes, the keys the node reads
    from `cmd/config`, OpenSCAD parameters and their values, the install
    URLs, and the broker ACL for the Tasmota topics; it rejects name
    fragments. The weather step spells out `SPOREPRINT_WEATHER_LON` (it said
    `_LON`), and so does the weather API's "unavailable" message.
- Capability bullets that described unimplemented features were removed (kWh,
  PID, timelapse, quiet hours, EXIF, sensor fallback/divergence, correlation
  reports, local CNN).
- `POST /api/builder/guide` returns 503 (`not_configured`) or 502 (refusal,
  truncated, empty, upstream error) with the body fields unchanged. Firmware
  ZIPs include `library.json`, `VERSION.txt`, every partition table and the
  version script, and never bundle a private-looking `extra_configs` file.

### Enclosures (`models/`)
- **All 10 models re-fit** to sourced drawings (vendor drawings, STEP files,
  Eagle boards) and fit-checked in OpenSCAD against dimensioned proxies; every
  part and preset renders manifold with Manifold. Nothing has been printed
  yet; estimated dimensions are listed per model.
- **Brass heat-set inserts** join every multi-piece enclosure
  (`models/lib/sp_inserts.scad`: ruthex / CNC Kitchen sizes, pocket + boss +
  clearance helpers, `SP_INSERT_HOLE_TWEAK`, `SP_FASTENER="self_tap"` fallback).
  `models/README.md` has the per-part and per-tier shopping list.
- `pi_case` (Pi 5 + Active Cooler, full-height insert bosses, Pi 4 does not
  fit); `esp32_case` (narrow USB-C default, `devkitc_v4` / `wide_usbc` /
  `s3_devkitc1` presets, header clearance, lid over the USB receptacle);
  `sensor_mount` + `sensor_bracket` (current STEMMA QT board outlines, a QT
  cable gallery, insert-held lid, `scd30=true` on both); `cam_mount`
  (CAM + MB stack, IO0/RST reachable through side slots, M5 pivot insert);
  `hx711_scale` (Adafruit 4541 bar75 default + `tal220`, Adafruit 5974 /
  SparkFun / generic boards, recessed board inserts down a Ø5.2 access bore,
  × 10 or × 12 board screws); `pump_bracket` (bolts through the pump flange,
  presets `adafruit_1150` / `kamoer_nkp` / `universal`); `relay_board_mount`
  (through-hole chassis for 4 IRLZ44N channels with 100 Ω, 10 kΩ, DO-41 and
  KF301 footprints, `node="relay"|"lighting"`); `power_supply_mount` (Facmogu
  5 A / 10 A and other brick presets, strap retention); `fan_duct` (71.5 mm
  NF-A8 pitch, M4 inserts).
- Model downloads (`GET /api/builder/models/<file>.scad`) inline `lib/`
  includes so a single file renders on its own; `models-bundle.zip` ships the
  repo layout.
- This work supersedes the earlier unreleased model entries (TAL220-only
  scale, saddle pump clamp, "Adafruit 1150 = Kamoer" wording): Adafruit does
  not name the pump's OEM.

### Firmware (details in `firmware/CHANGELOG.md`)
- **Arduino-ESP32 core 3.3.12 / ESP-IDF 5.5.5** (pioarduino platform
  55.03.312-1, pinned by release URL) replaces the end-of-life core 2.0.17 /
  ESP-IDF 4.4. Same images, pins, partition tables, MQTT payloads and signing
  vectors; still 25 kHz / 10-bit PWM. Field nodes update **over the air from
  2.x** — they keep their 2.x bootloader, which boots the 3.x image and still
  rolls back a 3.x image that fails its 60 s MQTT probation; NVS settings
  carry over. The Pi's OTA push keeps working: the node speaks the same espota
  handshake (core 3.3's `ArduinoOTA` would have demanded a PBKDF2 answer the Pi
  does not send). Building needs PlatformIO Core ≥ 6.2.0 and `git`; a
  post-build guard (`firmware/scripts/image_guard.py`) fails any image that
  leaves < 64 KiB of its OTA slot or drifts from the fleet partition layout.
  Library pins are exact (PubSubClient 2.8, ArduinoJson 7.4.3).
- **Drivers for every sensor the BOM ever recommended**
  ([`firmware/docs/drivers.md`](firmware/docs/drivers.md) is the inventory):
  - **AHT20** (I²C 0x38), autodetected. It was a listed SHT31-D alternate with
    no driver. Its init follows Aosong's v1.1 datasheet (register re-init of
    0x1B / 0x1C / 0x1E when the status asks for it, the v1.0 `0xBE` init as
    the fallback), at boot and, non-blocking, after a part resets.
  - **BME280 / BMP280** (I²C 0x76 / 0x77), autodetected. It adds the
    telemetry key **`pressure_hpa`**, which the Pi now stores.
  - **MH-Z19B** frames pinned to the manual. The MH-Z19C driver serves it.
  - **SCD30 on core 3.x:** the SCD30 gets its own I²C path at 50 kHz with
    the clock-stretch timeout at the chip's hardware ceiling. Core 3.x's Wire
    allows only 2 ms, which would have made it go stale. The SCD30 on a
    WROOM-32 node is listed as partial until bench-tested: the classic ESP32
    can wait only 13.1 ms for its clock stretch.

  These changes are additive and change no node pins.
- **ESP32-S3 camera boards** from the 2026-04 to 2026-06 BOMs now run the
  cam image: envs `cam_esp32s3` (Freenove ESP32-S3-WROOM CAM),
  `cam_xiao_esp32s3` (Seeed XIAO ESP32S3 Sense) and `cam_waveshare_s3`
  (Waveshare ESP32-S3-CAM-OV5640 / -OV3660). They have no flash LED and use
  BOOT (GPIO 0) as the reset button; build guide §8b has their pin maps.
  Firmware CI and the release workflow build all three.
- New env **`node_esp32s3_n32r16v`** for the ESP32-S3-DevKitC-1-N32R16V (same
  pin map as `node_esp32s3`), built by CI and shipped as
  `node_esp32s3_n32r16v.zip` in every release (`node_esp32s3.zip` does not
  boot on that board).
- Camera detects **OV2640 / OV3660 / OV5640** and tunes per sensor; flash stays
  on through the exposure; uploads default to the portal's Pi address; HTTPS
  uploads require the pinned Pi CA. The camera's setup portal no longer shows
  the node-personality select.
- **Reed invert** (portal checkbox / `cmd/config {"peripherals":
  {"reed_inv": true}}`) for door contacts wired on NO.
- Heartbeat on its own clock (min(publish interval, 5 min)), with `tls` and
  `board` keys. Secure MQTT never downgrades silently (`tls_downgrade` alert,
  CA-fetch retries, optional "Require TLS").
- **Secure MQTT verifies before it pins.** A fetched CA is only a candidate:
  the node tries TLS on 8883 with it from RAM and writes it to NVS only after
  the broker's CONNACK. A failed trial goes back to plaintext (or stays off
  MQTT with "Require TLS"), backs off, and the `tls_downgrade` alert says why
  (certificate name mismatch or another CA, 8883 unreachable, TLS error,
  login refused). A verified pin is final. A CA an older image pinned without
  this check is re-verified as a candidate. New optional heartbeat key
  `ca_fp`: SHA-256 of the pinned CA PEM.
- Safety: `aux` max-on 60 s by default and per-channel `max_on_sec`; an explicit
  OFF wins over `pwm`/`level`; 10-min MQTT-loss safe mode; channels off at OTA
  start; OTA rollback on node and camera.
- The setup AP no longer opens on a WiFi hiccup (BOOT / GPIO 13 gesture
  instead); replay guard + topic binding on signed commands; portal node-id and
  password-keep rules; epoch `ts` + `"replay": true`; latched alerts; sensor
  staleness alerts.

### Nodes: commands, OTA and coredumps (Pi side)
- `POST /api/hardware/nodes/{id}/peripherals`
  (`{"mhz19"|"hx711"|"reed"|"reed_inv": bool}`) sends a signed `cmd/config`;
  the node reboots ~1.5 s later if its driver set changed. `reed_inv` (a door
  contact wired on its NO terminal) applies live, so the endpoint takes every
  key the firmware does.
- **Signed node commands** carry two more signed members, `topic` and a random
  `nonce`: current firmware rejects redirected frames and no longer drops a
  legitimate identical command in the same second. Deployed firmware verifies
  them unchanged.
- **OFF is never published with `pwm`/`level`** (rules, manual node commands,
  cloud commands), and every published OFF — manual node, cloud, session-end
  safing, manual plug — clears that actuator's `safety_max_on_seconds`
  ceiling. `POST /api/hardware/nodes/{id}/command` returns 503 when nothing
  was published.
- Node liveness: any telemetry frame from a registered node refreshes
  `last_seen`, so nodes on a 15 min–1 h publish interval no longer flap
  offline.
- **Coredumps survive until the Pi has them.** Nodes used to erase a panic
  dump as soon as its last chunk left, so a Pi restart or a lost chunk lost
  the crash. Chunks now carry `coredump_id` (the dump's SHA-256); the Pi
  checks the reassembled bytes against it, writes the file durably (temp
  file, fsync, rename) and only then sends the signed `cmd/coredump_ack`.
  The node erases only on that ack, retries with backoff otherwise (3 uploads
  per boot, 6 per dump), then keeps the dump. A re-upload is acknowledged
  again without a second file or alert. Older nodes (no id) are stored as
  before and never acked; a Pi without ack support gets at most 6 copies
  from a new node, which keeps its dump.
- **Signed node OTA manifests (optional).** `POST
  /api/hardware/nodes/{id}/ota` takes optional `manifest` + `manifest_sig`
  files (the release manifest format the Pi's own OTA uses, with `artifact`
  = the PlatformIO env). The Pi verifies them against its pinned
  `SPOREPRINT_OTA_PUBKEY_B64`, the uploaded `.bin` and the node's firmware
  version, sends them on `cmd/ota_manifest`, and waits for the node's
  answer: a node image built with the key then flashes only that exact
  image; a node rejection stops the push; a node without manifest support
  gets a Pi-verified push. `GET .../ota` reports `manifest`
  (`node_verified` | `pi_verified` | null) and the node's refusal text.
  This repo's firmware releases, from `firmware-v5.1.0` on, are built with
  the key and sign one manifest per env (see *Dependencies and CI* and
  `docs/firmware-security.md`).
- Pi-pushed node OTA uses fixed TCP port 3233 (published in compose), runs one
  push at a time and retries invitations. The connect-back listener accepts
  only the node being flashed: another LAN host that connects first is logged
  and closed, and can no longer take the image and report a fake success.

### Automation
- The highest-priority rule whose condition holds owns an actuator; ceilings
  count from the first ON and a trip locks automation out for 15 min (WARNING
  page, CRITICAL if the OFF fails); life-safety rules (priority ≥ 20,
  absolute thresholds) run with no session; species-scoped rules match
  `lions-mane` and `lions_mane`; redundant OFFs to unpaired plugs are skipped,
  and a repeat OFF is re-sent only every 15 min unless something switched the
  actuator back ON — a manual, cloud or plug command, or a node reporting the
  channel ON, drops that suppression so the cutoff rule re-sends its OFF at
  the next evaluation; cron catch-up; scheduled FAE runs only when the
  phase's `fae_mode` is scheduled or continuous; new `profile_ref`
  `temp_mid_f`; `growth_form` antler/conk picks the CO₂ params; `bulk_bag` is
  sealed until fruiting; the rule `notification` flag now pages (WARNING <
  priority 20 ≤ CRITICAL).
- Seeded templates are upgraded on boot unless edited (a WARNING names each
  edited copy). An edited Pre-cool or Heat Wave rule with no
  chamber-temperature condition now holds the cooler ON against Cooling
  Cutoff — add a `temp_f` condition. The Humidity Boost/Cut and Dry Weather
  rules carry 1800 s ceilings: a humidifier that needs more than 30 min to
  cross the band trips one (raise `safety_max_on_seconds` if yours is slow).

### Sessions, species and transcripts
- **Shiitake browning phase** (`browning`, between `substrate_colonization`
  and `primordia_induction`): the unbagged block holds 60-70 °F, 70-80 % RH,
  CO2 under 2000 ppm, 12/12 light and passive FAE for 7-14 days. `GET
  /api/sessions/{id}/next-phase` suggests colonization → browning →
  primordia induction for shiitake (other species unchanged) and returns the
  new `exit_reminder`, the cold-water soak (35-50 °F, 12-24 h). Stepping on
  out of browning logs a `phase_exit_reminder` session event (also in the
  transcript), and the daily phase check offers the soak from day 7. A
  profile without browning setpoints refuses the phase (422); custom profiles
  can add it with the new optional `PhaseParams.exit_reminder`. The humidity,
  dehumidify, misting, CO2 and photoperiod built-in rules now also run in
  browning, a grow bag counts as open from browning on, and unedited stored
  copies of those rules upgrade at start-up. Vision tells Claude the brown,
  popcorned skin is normal for shiitake, reads a `browning_percent`, and
  sends an INFO "Browning complete" with the soak at 90 %; a colonized
  shiitake block is reported ready to brown, not to fruit.
- Overdue-phase reminders: a daily 09:00 (container-local `TZ`) INFO "Phase
  check — <session>" for each grow past its phase's expected duration
  (`phase_reminders` task).
- `POST /api/sessions` and `/phase` return 422 for an unknown phase or one the
  species can't enter; missing primordia/fruiting/rest setpoints borrow from
  each other; `next-phase` skips phases the species lacks; ending a grow safes
  the actuators it drove (per chamber when several grows run); phase history
  stores `params_snapshot`.
- Session events: the `phase_change` event reads "Phase advanced to primordia
  induction" (it printed the raw enum, which the timeline, chamber feed and
  transcript then showed); `data.phase` keeps the raw value. Leaving a phase
  that owes a manual step logs the `phase_exit_reminder` event before the
  `phase_change` (same second, so the event id is the order): the session
  timeline and the transcript's Key Events — the text Claude analyses —
  listed shiitake's cold-water soak after "Phase advanced to primordia
  induction". `get_events` and the transcript sort same-second events by id.
- Chamber `PATCH` with `active_session_id: null` detaches; chambers with
  history can be deleted; iCal dates anchor at the first phase; the
  pink-oyster harvest page is CRITICAL; the substrate calculator and shopping
  list scale correctly; species setpoints match the spec's §4b, now
  `docs/species-reference.md` (pink oyster, cordyceps, king trumpet CO₂);
  `POST /api/experiments/{id}/analyze` is the preferred route.
- A species' grow-supplies list (`GET /api/species/{id}/shopping-list`) lists
  the vessel its first recipe uses: a filter-patch grow bag for a
  pressure-sterilized block (supplemented sawdust, masters mix), jars for
  grain / brown-rice / agar cultures, nothing for an outdoor bed or log, and
  the monotub + liner only for pasteurized bulk (CVG, manure, straw) — it gave
  every species a monotub + trash-bag liner.
- Transcripts: per-phase telemetry summaries are filled from rollups for old
  phases; unknown session ids return 404; session analysis sends at most 150
  vision summaries. The markdown transcript
  (`GET /api/transcript/sessions/{id}/transcript?format=markdown`) no longer
  prints Python `None` for unset session fields: the header used
  `session.get(key, 'N/A')`, but a NULL column is present with value None, so
  it printed lines such as `**Substrate**: masters_mix (None)` and
  `**Inoculated**: None (None)`. A missing value now drops its line, and a
  missing detail drops its parentheses. The header fields are a list
  (`- **Species**: …`), so they render on separate lines in any markdown
  viewer.
- Species summaries agree with their own cards: the Shiitake summary names
  the cold-water soak (35-50°F, 12-24 h) its pinning trigger and reminder
  use and 3-6 flushes, and the king trumpet, yellow oyster, chestnut,
  pioppino and nameko summaries give their yield notes' flush range
  (`tests/test_species.py` checks every profile).
- `POST /api/sessions` with a `chamber_id` the Pi has no chamber for answers
  422 `chamber N not found` instead of a bare 500 from the foreign-key
  failure; a cloud `session_start` reports the same reason.

### Telemetry, vision, weather and notifications
- Telemetry: `ts < 1e9` is treated as unsynced; replayed (`"replay": true`)
  and out-of-order frames (up to 120 s older than the node's newest live
  frame; a bigger step back is the node's clock being corrected and
  re-baselines) are stored but not evaluated or pushed live; history charts
  fall through every rollup tier. The Pi's own clock never decides whether a
  frame is live: a Pi clock running minutes fast no longer silently stops
  automation and safety thresholds for every synced node. Pi-vs-node clock
  skew is measured per node, logged as a rate-limited WARNING past 120 s, and
  reported (with non-live frame counts) under `reliability` in
  `GET /api/health/detail/system`.
- Readings are tagged with their grow, chamber-aware: a listed node belongs
  to its chamber's grow, an unlisted node to the newest chamberless grow.
  With grows in two chambers, list every node in its chamber.
- Vision auto-analysis runs every 6 h per session
  (`SPOREPRINT_VISION_AUTO_INTERVAL_MIN`, default 360) and on the first frame
  after a phase change, instead of every capture; the local CNN is still a
  stub. Contamination pages CRITICAL at confidence ≥ 0.6 and sends one
  "Possible contamination" WARNING at 0.3–0.6; contamination events are
  recorded with `source='vision'`. Frame retention: 30 days, then one frame
  per camera per day (flagged, labelled and referenced frames kept).
  `X-Camera-Sensor` is stored as the node's `camera_sensor` and named in the
  Claude prompt; a harvest-window INFO notification; stored frame names are
  unique and carry the real image type; a failed re-analysis never
  overwrites a stored one; `POST /api/contamination/identify` returns 415 for
  non-image uploads.
- Claude: every feature uses `SPOREPRINT_CLAUDE_MODEL` (default
  `claude-sonnet-5`); output ceilings are 16,000 tokens (32,000 streamed for
  the Builder). A refusal or truncated answer returns `{error}` (Builder:
  `truncated: true` plus the partial guide, not saved) instead of a 500 or a
  half-saved result.
- Weather: forecast alerts fire only once the weather→closet model is trained
  (~7 days), ignore past hours and dedupe per session, kind and day;
  `forecast_high_f` / `forecast_low_f` cover today's local day; the prediction
  model trains on 30 days; Open-Meteo times parse as UTC.
- Notifications: ntfy is published through its JSON API (titles with em dashes
  or °F now arrive); identical CRITICAL pages collapse for 15 min; temperature
  and humidity EMERGENCY pages dedupe per node, parameter and direction; node
  alerts reach ntfy by tier.
- Nightly retention also prunes session-less `automation_firings` older than
  90 days and thins vision frames; new index `idx_rollup_node_sensor_time`
  speeds long-range charts.
- INFO and WARNING notifications sent without a dedup key now dedupe by
  title (1 h and 5 min, as documented), and the drying-complete INFO keys on
  the harvest: it repeated on every drying-log entry past the target.

### Smart plugs and integrations
- **Shelly Gen2+ smart plugs** (Plus / Pro / Mini, Gen3, Gen4 — plug_type
  `shelly_gen2`) alongside Gen1 and Tasmota. Set the device's MQTT prefix to
  `shellies/<role>` (e.g. `shellies/humidifier` → `plug-humidifier`) and log in
  as `sp-3p`; the factory prefix (the device id) is outside the ACL and is
  dropped. Commands are JSON-RPC `Switch.Set {id, on}` on `<prefix>/rpc`
  (the `server` account gains `write shellies/+/rpc`; `sp-3p` is unchanged);
  state and `apower` come from `NotifyStatus` / `NotifyFullStatus` on
  `<prefix>/events/rpc`, `<prefix>/status/switch:<n>` and the reply to a
  `Shelly.GetStatus` the Pi sends whenever `<prefix>/online` turns true (so a
  plug registers and refreshes without a toggle). Multi-channel devices
  register `plug-<role>-<n>` per extra switch. Safety ceilings, manual OFFs
  and the cutoff re-assert work as for the other plugs; a Gen2 `errors` trip
  (overpower, overtemp) is logged. Every plug type now keeps `status`
  online/offline from its online flag or Tasmota `tele/LWT` (Socket.IO
  `plug_online`), and a plug report re-types a row whose `plug_type` no longer
  matches the device (a role assigned with the default `plug_type: "shelly"`
  keeps a detected Gen2).
- Tasmota plugs also update from `stat/RESULT` and `tele/STATE` JSON
  (`POWER` / `POWER1`); Shelly and Tasmota plugs register on their first state
  report.
- Plugs following the build guide never registered (missing Full Topic and
  credentials) — docs, Builder steps and the install summary now say both.
- `POST /api/automation/plugs/{id}/command` returns 409 for an unknown or
  unpaired plug and 503 when the broker is down.
- Integrations: sending back a masked `••••last4` secret (or omitting it)
  keeps it, `""` clears it — but a kept secret stays bound to where it is
  sent: changing a driver's `secret_bound_fields` (`base_url` for Aranet,
  Agrowtek and BIOS) without re-entering the secret returns 422, so a config
  PUT can no longer redirect a stored key to another host. A lost or changed
  `.integration-key` shows "re-enter the credentials"; vendor health
  transitions that happen while the cloud link is down are retried until
  delivered.
- Vendor drivers: the Tapo local KLAP handshake (real devices authenticate;
  its `set_power` integration test is no longer `xfail`), Kasa multi-segment
  replies, Wemo port probing (49153/49152/49154/49155/49151, `host:port`
  pins), Pulse session reuse, the Grafana contamination counter.

### Cloud and Pi self-update
- Cloud pairing credentials persist to `cloud.env` beside the DB (0600) and
  survive rebuilds; `cloud_url` must be `https://`; `integrations_request`
  frames are replay-deduped and, after the first signed one, must be signed.
- **Pi self-update verifies a signed release manifest.** Releases now
  publish `{version}.manifest.json` + `.manifest.json.sig`: canonical JSON
  `{schema, artifact, version, channel, sha256, size, published_at}` signed
  with the existing OTA key (`server/app/cloud/ota_manifest.py`, test vectors
  in `server/tests/fixtures/ota_manifest_vectors.json`). Before downloading
  the bundle, the Pi checks the signature over the exact bytes and the
  canonical form. The version must be the one requested, the channel must
  be the Pi's new `SPOREPRINT_OTA_CHANNEL` (default `stable`), and the
  version must not be older than the installed one or the floor recorded by
  the last OTA. The bundle is then capped at the signed size and its sha256
  checked. A downgrade needs `SPOREPRINT_OTA_ALLOW_DOWNGRADE=true` on the Pi;
  the OTA command cannot allow one. A key sent in the command (`ota_pubkey`)
  is ignored. A manifest that is present but broken never falls back to the
  legacy `.sig` (upgrade notes above). `scripts/sign-ota-bundle.py
  --manifest-out` writes the manifest. The version check uses `fullmatch` (a
  trailing newline used to pass).
- Pi OTA: bare-metal Pis only — the Docker install refuses cloud self-update
  and the refusal says `git pull && ./install.sh`; downgrades are refused;
  bundle extraction applies tarfile's `data` filter.

### Security
- **DNS-rebinding guard.** The API and Socket.IO answer only for Host names an
  outside attacker cannot point at the Pi: private, loopback, link-local,
  CGNAT (Tailscale) and IPv6 unique-local IP literals; `localhost`, `*.local`,
  `*.lan`, `*.home`, `*.home.arpa`, `*.internal`, `*.localdomain`; dotless
  names; the host of `SPOREPRINT_PUBLIC_UI_URL`; and the new
  `SPOREPRINT_ALLOWED_HOSTS` (comma list of names, `*.suffix`, IPs or CIDRs;
  `*` turns the check off). Anything else gets **421** with the setting to
  change. `GET /api/health` and `GET /api/provision/ca` stay open. Reach the
  Pi by a public DNS name (Tailscale MagicDNS `*.ts.net`, a reverse-proxy
  domain)? Add it to `SPOREPRINT_ALLOWED_HOSTS`.
- **Broker service accounts never become nodes.** Frames under
  `sporeprint/<id>/…` for `server`, `sp-3p`, `sp-cmd`, `sp-telemetry` or the
  Pi's own MQTT user are dropped (WARNING once) before registration or rule
  evaluation, `POST /api/hardware/claim` refuses those ids, and node rows an
  older server registered under them are deleted when MQTT starts. A leaked
  smart-plug credential can no longer register a node, claim a node type or
  feed the rules engine.
- `GET /api/provision/ca` is public in API-key mode, so Secure-MQTT nodes can
  fetch the CA; in that mode `GET`/`POST /api/cloud/pairing-code` now need the
  bearer, and a keyless `POST /api/vision/frame` is accepted only from a
  registered camera with a declared Content-Length ≤ 20 MB.
- A bearer token with non-ASCII bytes gets 401 instead of a 500 (the API-key
  check compares UTF-8 bytes, as the Grafana `/metrics` check already did).
- **`X-Forwarded-For` is trusted from one address only.** The ui and server
  containers share a fixed `edge` network (`SPOREPRINT_EDGE_SUBNET`, default
  `172.31.253.0/28`; ui `.2`, server `.3`), and `FORWARDED_ALLOW_IPS`
  defaults to the ui address instead of the whole `172.16.0.0/12` bridge
  range, whose gateway relays IPv6 and loopback clients of the published
  `:8000` that could forge the header. Move all four settings together if
  compose reports a pool overlap.
- `server/.dockerignore` keeps `data/`, SQLite files, `.integration-key` and
  `cloud.env` (the cloud device token) out of the image when the server was
  run from `server/`.
- **The Pi's node OTA push also answers the PBKDF2 login.** arduino-esp32
  3.3.1+'s stock `ArduinoOTA` challenges with a 64-hex nonce and accepts only
  `sha256(pbkdf2_hmac_sha256(sha256(password), nonce:cnonce, 10000):nonce:cnonce)`
  with a 64-hex cnonce; `server/app/hardware/ota_push.py` now picks the answer
  by nonce length as espota.py does (32 hex: the MD5 digest every SporePrint
  image still offers; 64 hex: PBKDF2, computed off the event loop) and refuses
  any other length. Nothing changes on the wire for current nodes. It is the
  first half of the coordinated move to the stock library: a firmware that
  drops `ota_service.cpp`'s MD5 login must wait until every Pi that pushes to
  it runs a release newer than 5.0.0.
- Also security-relevant, described above: stored integration secrets stay
  bound to their destination (*Smart plugs and integrations*), the OTA
  connect-back peer check (*Nodes*), Secure MQTT verify-before-pin and `ca_fp`
  (*Firmware*), and the signed Pi release manifest (*Cloud and Pi
  self-update*).

### Install and deploy
- `install.sh`: writes `TZ`, generates the command-signing key, issues the
  broker certificate with IP and DNS SANs for every host IPv4 (re-issued from
  the same CA when the IP changes), repairs Docker-created bind-mount
  directories, and prints the schedule time zone, signing status and
  smart-plug credential + Full Topic.
- `setup.sh` is a developer-workstation script (LAN-trust, no API key, IP
  SANs); `scripts/setup-pi.sh` wraps `install.sh`.
- `docker compose up` without `install.sh` fails loudly instead of creating
  root-owned directories; broker secrets are owned by the broker user; logs are
  capped at 10 MB × 3 per service.
- The broker ACL lets nodes publish log batches and coredump chunks and lets
  the server read `$SYS/broker/#`, so node logs, coredumps and
  `/api/health/detail/mqtt` fill in. The broker CA is mounted into the server
  container, so `/api/provision/ca` works under Docker.
- `provision-node.sh` writes the signing key to the repo-root `.env` (reusing
  an existing one); `add-node-mqtt-user.sh` mentions the key; broker password
  edits run inside the broker image and reload the `mqtt` service.
  `generate-ota-keypair.py` creates the private key 0600 atomically.
- `rotate-mqtt-creds.sh` writes only the `server` password into `server/.env`;
  the other shared passwords stay in the repo-root `.env`.
- New settings: `SPOREPRINT_VISION_AUTO_INTERVAL_MIN` (default 360),
  `SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS` (default false),
  `SPOREPRINT_PUBLIC_UI_URL`, `SPOREPRINT_CLAUDE_MODEL` (default
  `claude-sonnet-5`; every Claude feature), `SPOREPRINT_ALLOWED_HOSTS`,
  `SPOREPRINT_OTA_CHANNEL` / `_ALLOW_DOWNGRADE` / `_ALLOW_LEGACY_SIGNATURE`,
  `TZ`, `FORWARDED_ALLOW_IPS` and the `edge` network's
  `SPOREPRINT_EDGE_SUBNET` / `_UI_IP` / `_SERVER_IP`. Every `Settings` field
  is now forwarded by compose (enforced by a test).
- The server boots when `server/.env` holds keys that are not settings (a copy
  of the repo-root `.env` with `TZ` or `FORWARDED_ALLOW_IPS`) and when a
  non-string setting is present but blank (`SPOREPRINT_PORT=` means the
  default). A malformed non-blank value still fails loudly.
- Upgrading a database created before v3.3.0 no longer crashes `init_db`.
- Images pinned: `eclipse-mosquitto:2.1.2-alpine`, `binwiederhier/ntfy:v2.28.0`,
  `busybox:1.36.1` (BusyBox's latest stable release; 1.37 and 1.38 are
  unstable upstream), and `nginx:1.30.5-alpine` and `python:3.12.15-slim` by
  digest. The server image installs exactly `server/uv.lock` (hash-checked,
  exported with uv 0.12.23).
- The dashboard's nginx passes request bodies up to 21 MiB and gives `/api/`
  a 180 s timeout. Socket.IO rate limiting and client tracking use each
  client's real address (uvicorn `--proxy-headers` behind nginx).

### Dashboard (`ui/dist`)
- **Rebuilt from the monorepo's pi-ui** after five browser audits and again for
  the 2026-10 follow-ups. The first
  rebuild also brought in the other pi-ui and design-package changes made in
  the monorepo since the previous `ui/dist`, from the v5.0.0
  release work and the fixes after it. The main bundle is 1,166 kB (338 kB
  gzipped, built with Vite 8); it was 1,258 kB (340 kB) before the wiring
  SVGs moved to their own 173 kB chunk, fetched only when the Wiring tab
  opens (1,112 kB / 323 kB right after the split).
  `tests/test_ui_builder_sync.py` follows references from `index.html`
  through the bundle, so that chunk counts as a shipped asset. `ui/dist`
  no longer ships source maps (the same test fails on any `*.map` file or
  `sourceMappingURL` comment in `ui/dist`).
- **Licence notices ship with the dashboard.** The minified bundle carries no
  legal comments, so `ui/dist/THIRD-PARTY-LICENSES.md` lists every library
  the bundle and its stylesheet include (React, React Router, lucide-react,
  Tailwind CSS and the rest) with its licence text, and
  `ui/dist/FONT-LICENSES.txt` carries the SIL Open Font License and
  copyright of each bundled font family. `tests/test_ui_builder_sync.py`
  checks both are there.
- **Fonts ship with the dashboard.** Space Grotesk, Cormorant Garamond and
  JetBrains Mono (latin subset, woff2, SIL Open Font License) are bundled in
  `ui/dist/assets` instead of loaded from Google Fonts, so opening the LAN
  dashboard contacts no font service and the fonts work offline.
- **Species wizard** cards are keyed by species ID: two strains of one
  species share a binomial, and changing an answer used to leave a stale
  card behind (four cards, one ranked twice) while the
  education-and-research notice went away. **Shopping List** shows that
  notice when a controlled-category species is picked under Add a species
  or is among the grows. The Builder's **Firmware** tab links the signed
  `firmware-vX.Y.Z` release images and says a build from its ZIPs has no
  verify key; the **OTA verify key** row and note in Settings say to pin the
  key each firmware release's notes print (the keypair script only for
  signing your own builds: a freshly generated key makes the Pi refuse every
  official signed update). The **New session** and **New culture** pickers
  open on the first species outside the controlled category instead of the
  first library entry.
- **Built with Vite 8** (React 19.3, Tailwind v4). The bundle's build target
  is pinned to Chrome/Edge 111, Firefox 114 and Safari/iOS 16.4 (Vite 6
  targeted Safari 14 / Chrome 87); no browser the dashboard ran on is
  dropped, since its Tailwind v4 CSS already needed Safari 16.4, Chrome 111
  and Firefox 128. Vite 8's minifier writes string literals in backticks,
  so `tests/test_ui_builder_sync.py` and `tests/test_hardware_guides.py` now
  accept any JS quote in the bundle, as `scripts/sync_ui_builder_data.py`
  already did.
- **The Builder page reads this Pi live.** It loads the BOM
  (`/api/builder/tiers` and `/tiers/{id}`), the models, the wiring diagrams
  and the firmware ZIPs from the Pi. If a request fails, that resource falls
  back to a copy generated from this repo at build time, and a pill at the
  top of the page says which data is on screen. This replaces the stale
  static copy, which had a pre-audit BOM with no cabling, "browse repo" and
  wiring links to `hardware/3d` and `hardware/wiring` (both 404), raw GitHub
  `.scad` downloads that cannot render without `models/lib/`, and a false
  "slicer-ready STL exports" claim. The built-in BOM counts the mixed kits
  per size (×12: $1,061 / $4,644 / $7,181).
  - **Shopping tab and totals:** `shared` parts are bought once per
    installation and every other line's units scale with the chamber count;
    pack-sold lines buy whole packs (`shared_units` included), so totals
    equal `parts_cost(N)` at any chamber count from 1 to 99 (Bare Bones ×10
    buys two packs of M3 inserts for 104). Lines show their units and the
    packs that buy them, worded one way on the Shopping tab, the Shopping
    List and its CSV ("4 · 2 packs of 2 · 1 spare", "$5.49 / pack of 100 ·
    ~$0.05 ea"), and "(shared)" shows at every chamber count. Lines counted
    in something other than pieces say so (new optional API field
    `Component.unit`): "420 ft · 5 packs of 100 ft · 80 ft spare", "$26 /
    pack of 100 ft", "~$0.26 / ft"; the WAGO assortment reads "12 chamber
    sets · 4 packs of 3 chamber sets"; solder in grams, VELCRO in straps, the
    insert and screw kits in the size they are counted in. The total shows
    the shared and chambered parts separately and says what whole packs
    save; smart plugs, wiring and hardware have their own sections. Cost
    captions use whole dollars (the stale "Pi's estimate" clause is
    removed).
  - **Overview and tier cards:** the Overview counts packs and parts to buy
    (and BOM lines and units separately) instead of adding feet, grams and
    pieces, uses the Shopping tab's "shared, bought once" caption, and its
    cost caption reads like the BOM totals at ×1. Tier cards price the chosen
    count ("47 lines · ~$1,733 for 4 chambers"); a count outside the presets
    shows as its own "×7" pill next to a − / + count box; the chamber caption
    names what is bought once: the Pi side, the bench breadboard and bulk
    packs that cover 12+ chambers. The tier and chamber count stay in the
    URL.
  - **Setup tab:** the backticked commands, paths and topics show as code
    with a copy button (on a plain-http Pi it falls back to
    `execCommand("copy")`). Copying or selecting text no longer ticks the
    step. Ticks are stored per step id instead of per position, so adding a
    step no longer moves them; ticks saved by the released dashboard carry
    over to the matching new steps. The setup step covers Shelly Gen2+
    plugs.
  - **Wiring tab:** the tier's SVG as the Pi serves it, scaled to its box's
    width, with an "open full size" link and a link to its GitHub source;
    the cards show a thumbnail with a readable "full-size svg →" label. If
    the Pi's SVG does not load, the page shows the same generated diagram
    from the bundle instead of the old hand-drawn sketch, which clipped
    labels, put pin labels under wires and cut off the legend. The
    connection table uses the live wiring rows.
  - **Models tab:** each card shows the title and description from the
    model's `.scad` header (a cut description ends on a whole word, and
    "more" reads the full header from the Pi's download first, then GitHub)
    and downloads the Pi's self-contained file (`lib/` inlined); a "download
    all (.zip)" link; "browse repo" opens `models/`. Single-column model cards
    no longer leave blank bands.
  - **Firmware tab:** one card per image (unified node, camera), downloaded
    as the Pi's self-contained ZIP. An image is listed for a tier when one of
    its PlatformIO envs is a tier target, which covers
    `node_esp32s3_n32r16v`. Each card lists the `pio run -t upload -e <env>`
    command for each board, with copy buttons; the camera card lists `cam`,
    `cam_esp32s3`, `cam_xiao_esp32s3` and `cam_waveshare_s3`, each with its
    board. File names are their download links, so the table fits a phone.
    Offline, the tab lists the files (the new firmware files included, and
    `cam_policy.h` as well as `main.cpp` on the camera card) from a listing
    generated from this repo (raw GitHub links and sizes) instead of a
    hand-copied list.
  - **Resources:** the repo is labelled AGPL-3.0 (it said MIT). The dead forum
    link is removed, and the dead Discord invite is replaced by a plain-text
    "coming soon" placeholder with no link. "User docs" opens the
    sporeprint.ai user guide; "Quick start" is the README's.
  - **Layout:** checked in Chrome on every tier and tab from 320 to 1600 px
    wide: nothing sticks out of its box and the page never scrolls sideways.
    Below 900 px the BOM and wiring-connection tables stack as cards instead
    of scrolling (the Buy link and wiring notes were cut off between 1024
    and 1340 px); the firmware-file table scrolls inside its own box.
- **Shopping List** shows your build. "Send BOM to /shopping" is a real link
  (`/shopping?bom=…&chambers=…`) that hands over the tier and chamber count,
  and "Open in builder →" keeps them. The page no longer shows demo rows or a
  restock banner: it lists the sent BOM (live from
  `/api/builder/tiers/{id}`, totals equal to the Builder's), grow supplies
  for each species with an active session
  (`/api/species/{id}/shopping-list`), and your custom items.
  - Grow supplies are merged across species, one row per item (spawn,
    cultures and inoculants stay one row per species); a merged supply counts
    as bought only when every species it serves is ticked ("partly bought —
    for …" until then). A species with a session (`lions-mane`) and the same
    species picked by hand (`lions_mane`) is one grow target, not two.
  - A hand-set grow count shows as an override with a reset; a count change
    refetches only that species; one message when the sessions can't be
    read; the two 404s are told apart. An out-of-range `?chambers=` opens on
    99 instead of 1, the URL says what the page shows, and an unknown
    `?bom=` warns (on a full page load too).
  - Ticks and notes follow a part across builds; notes grow with their text;
    custom items validate their name and link inline. Two open Shopping List
    tabs stay in step: a tick, note, custom item, grow count or build sent in
    one shows in the other, and every change is written into what is stored,
    so one tab no longer undoes the other's.
  - The hardware tables line up; below 900 px of table each row becomes a
    card on screen. A printed list is a table again: the card layout is
    screen-only, so a Letter or A4 sheet no longer prints one tall card per
    row (a 4-chamber list ran to 20 pages). A print stylesheet hides the
    navigation and prints dark on white; the Buy column and the "notes &
    substitutes" disclosure stay off paper, notes print in full, cells are
    tighter and the columns size to their content; the note column is a
    fifth of the table.
  - The CSV writes "×N" and "(shared)" as the table does, one supplier URL
    per cell and "lb" for every pound, and defuses every formula-like cell
    (`-1+2`, a leading tab).
- **Sessions:** a new session shows as day 0 (it showed "20710d") and counts
  toward the 30-day yield, and the Day column and 30-day yield no longer read
  every session as day 0. The phase pill names the grow's phase ("primordia
  induction", not the "fruiting" bucket) and its chamber by name; rows show
  the session name; timeline tags name the event (NEW, PHASE, …) instead of
  truncating it ("SESSI"). "advance → <next phase>" shows the phase's exit
  reminder (the cold-water soak when leaving shiitake browning) before the
  confirm; browning segments read tan on the phase bar, and the browning
  events are tagged STEP and VISION.
- **Species:** cards show common names, size to their content and expand in
  place when opened, so Tab order matches the screen. The four categories
  have their own colours (green, amber, blue-violet, orchid; checked for
  colour-blind contrast), and the 8 novelty species get a filter chip, so
  the category KPI adds up to the 74 shown; KPI labels fit one line. Tags
  collapse to the 12 most used behind an "all 129 tags" toggle, and the tag
  counter is always announced. On a phone the filters and "recently viewed"
  fold behind one "filters" button, so the first card is on the first
  screen. Phases read "Substrate colonization" / "Primordia induction" and
  flush counts "~4 flushes"; inactive filter chips are legible (WCAG AA).
- **Other pages:** tables on Sessions, Transcripts, Inventory, Cultures and
  Contamination scroll inside their own column (from 1180 to about 1600 px
  they ran under the right-hand panel), and Sessions and Transcripts pin
  their row action instead of scrolling the page. The transcript preview
  renders bold, italic and code. Contamination pills follow one severity
  ladder (critical red, high amber) and list every entry; its upload buttons
  wrap at 390 px; a contamination check without a Claude key says so in
  words and links to Settings, and the log stacks on a phone. Long
  automation conditions wrap. Chamber tiles carry the chamber's name; the
  Quick overrides strip fits five tiles down to ~600 px of card; the CLOUD
  KPI no longer breaks mid-word; the Planner's cycle table fits its card at
  1440. Firmware: a push can carry the release's signed manifest and `.sig`
  ("signed release manifest (optional)" under update firmware; both or
  neither), and the status says whether the node or only this Pi checked it.
- **Navigation:** below 768 px the rail becomes a drawer behind a menu
  button on every page; the drawer is a modal dialog (focus kept inside, the
  page behind it inert, focus restored on close). The sidebar footer
  (version, uptime) is no longer clipped.
- **`scripts/sync_ui_builder_data.py` now verifies the bundle instead of
  patching a static copy.** `--check` confirms that the bundle requests
  `/api/builder/*` live and has none of the old static Builder's dead links or
  claims. It also confirms that the built-in copy matches this server: the
  tiers exactly as in `hardware_guides.py`, plus the models, diagrams and
  firmware envs. Without `--check`, the script rewrites only stale built-in
  data, in place. `tests/test_ui_builder_sync.py` enforces all of this and
  also checks the built-in copy against the API's actual responses.
- **+ new session works again on a Pi with chambers.** The Chamber select
  picked the first chamber as the list loaded, but the trigger went blank and
  an untouched form posted `chamber_id: 0`, which failed with a 500. The
  select keeps the picked chamber (the shared Select ignores the empty value
  Radix's hidden form `<select>` reports when value and items change in one
  render), and the form sends a missing or blank chamber as unassigned.
- Smaller dashboard fixes: the Settings quiet-hours row says the Pi sends
  every alert to ntfy (filter by priority in the ntfy app) instead of
  pointing at the cloud app; the Sessions stage chips' hints read "phases:
  …" ("rest (between flushes)" under harvest); an idle, unnamed chamber's
  header names it once; chamber names stay on one line in the inventory and
  Planner tables (the Planner's node count moved under the name); small text
  that read under 4.5:1 (Shopping List pack, price and note lines, the
  Planner's weekday header, the sidebar uptime, "not yet supported on this
  Pi", chamber tile badges, Automation rule stats, contaminant growth speed,
  "not edible", the selected Sessions row and Builder tier card) is brighter.
- **Education-and-research notice on the species pages.** The dashboard's
  species library and species wizard show one short note: "For education
  and research purposes only. Some species may be controlled where you live;
  you are responsible for following local law." The species library shows it
  above the list (its category chips can always pick the category) and in an
  active profile's details; the species wizard shows it when a
  recommendation is in that category; the species pickers on the new
  session, new culture and plan-a-grow forms show it while a species in that
  category is chosen. It names no species.
- **Active species are opt-in in the wizard and listed last in the library**,
  as on the cloud. `GET /api/species/recommend` leaves the `active`
  category out of the ranking unless `include_active=true`; the species
  wizard's "candidate pool" switch (off on every visit) sends it and shows
  the notice while it is on. The species library lists the other categories
  first, A to Z by common name, then the active category; before, it kept
  the profile file's order, which starts with that category.

### Docs and diagrams
- **All three tier wiring diagrams redrawn** to the cabling standard: inside vs
  outside the chamber with the wall grommet, the power strip and every AC
  cord, USB power paths with cable lengths, the 12 V PSU → pigtail → WAGO →
  fused branches with ratings, wire gauges on each run, the common ground
  (ESP32 GND → J1 "−") on every switch board, the STEMMA QT chain, fan
  extension leads, and on All the Things the HX711 / door-contact 22 AWG
  4-conductor runs, the 10 kΩ reed pull-up and the pump channel. Each has a
  one-channel end-to-end schematic. `wiring-overall-system.svg` marks what
  lives in the chamber and adds a power + cabling band.
- `docs/hardware-build-guide.md`: §7 is now *Power and cabling* (power strip,
  12 V distribution with fuse table, 5 V USB table, the chamber wall, and a
  table mapping every cabling / consumable BOM line to where it is used); the
  §5 channel schematic shows the fuse, wire gauges, the fan extension and the
  common ground; a *Tools you need* list; the S3 pin map (§8a) and the three
  S3 camera boards of earlier BOMs (§8b); a 12 V pre-power check in the
  bring-up list; new troubleshooting rows (dead board, swapped fan wires).
  New `docs/auth.md` (LAN-trust vs API-key mode, public paths).
- `models/README.md`: per-tier insert and screw totals; the BOM's insert and
  screw kits, the 18" (457 mm) duct tie and the VELCRO straps.
- **Docs brought in line with the code (2026-10).** `README.md`: React 19
  dashboard that loads over REST (no Socket.IO client, no PWA, no unit
  switch; the Builder's Claude guide generator is API-only), the real
  Socket.IO event names (`rule_fired`, not `rule_firing`; plus
  `actuator_state`, `node_status`, `node_log`, `node_ota`, `plug_online`),
  the node `ota` / `coredump/chunk` / `cmd/coredump_ack` /
  `cmd/ota_manifest` topics and the Shelly Gen2+ topics and setup,
  PlatformIO Core ≥ 6.2.0 + git for the core-3 platform, the OTA listener
  (`ota_service.cpp`, not `ArduinoOTA`) and signed node manifests, the
  extra drivers and the ESP32-S3 camera boards, and an upgrade note for
  nodes still on core-2.x images; the pairing code lives in Setup → § III
  Cloud link; unknown `server/.env` keys are ignored and `TZ` must be
  exported; no side-by-side experiment telemetry, chamber comparison view,
  label-printer presets, container labels or per-category ntfy topics; the
  Server Modules table lists all 20 packages and labels the two single-file
  routers; the cloud pairing steps; the Sessions page row names what the
  page has (a finished session's `report.md`; the drying log and
  `report.csv` are API-only — no drying tracker or report downloads);
  `labels/` makes QR code PNGs (no thermal-printer support); the wizard asks
  five questions (the API scores six inputs). `AGENTS.md`: the platform pin,
  the core-3 pitfalls, the espota handshake rule, Shelly Gen2 prefixes,
  coredump store-then-ack, OTA manifests, the `browning` phase and the
  current frontend stack; frame liveness is replay / out-of-order, not frame
  age; `labels/` is router-only. New `firmware/README.md` sections
  (platform, build, OTA, updating nodes from a core-2.x image, coredumps) and
  `config/mosquitto/README.md` (listeners, accounts, plug topic layouts,
  adding a topic). `docs/integrations/smart-plugs.md` gains a Shelly Gen2+
  section; the build guide the Gen2 setup, a troubleshooting row and node
  firmware updates; `docs/firmware-security.md`, `docs/data-flow.md` and
  `docs/dual-repo-architecture.md` (React 19 bundle, 74 species, no
  Capacitor shell) are corrected; the spec (Cordyceps / active-category rest FAE,
  the MQTT watchdog, the vision correction mark).
- **Release docs pass (2026-10).** `docs/architecture-overview.svg` matches
  the stack: a React 19 / Vite 8 / Tailwind v4 dashboard on REST (it showed
  React 18, a PWA, Zustand and a Socket.IO client), the Compose services,
  every server module, the autodetected sensor set, OV5640 and the S3 camera
  boards, Shelly Gen1 and Gen2+, 25 kHz 10-bit PWM.
  `docs/wiring-overall-system.svg` names OV5640, ntfy, the Shelly Gen2+
  prefix and the browser's REST link. The Recommended and All the Things
  diagrams point S3 camera boards to build guide §8b, which gains a pin table
  for the AI-Thinker and the three S3 camera boards; the build guide also
  covers the portal's NTP server field and the Firmware page's signed-manifest
  upload. `docs/data-flow.md` describes the current flows (adding node
  maintenance: OTA push and coredump store-then-ack) instead of per-release
  change lists; `docs/cloud-relay-flow.md` has the real command shape
  (`target_kind`), the Pi's checks in order and the real `ota_step` names;
  the Mermaid block in `docs/dual-repo-architecture.md` is valid again (its
  services subgraph did not parse). README gains a `**Version:**` line that
  `scripts/bump.sh` keeps current, the cloud command checks (`target_kind`,
  a 64-character channel), the Shelly `status/switch:<n>` topic, the NTP
  portal field and `SPOREPRINT_INTEGRATION_KEY_PATH`. The integrations docs
  list Tapo with the LAN drivers, the vendor write actions (since v4.1.2)
  and rule-driven vendor actions, and the Grafana weight and door metrics.
- `tests/test_docs_consistency.py` pins the README, build guide, SVGs,
  AGENTS.md, the spec's tracked reference pages (`docs/species-reference.md`,
  `docs/feature-status.md`, `docs/automation-rules.md`) and (when present)
  the git-ignored `CLAUDE.md` to the code,
  firmware and BOM: tier prices and what a second chamber adds, fuse ratings,
  WAGO parts and wire gauges, the common ground in every guide and diagram,
  the strip sizes, the per-tier insert sourcing, the table and species
  counts and categories, the `GrowPhase` list, the platform pin, the PWM
  spec, the Socket.IO event names, the Shelly Gen2 prefix and each 2026-10
  audit claim; since the release docs pass also the camera pin tables (build
  guide and `firmware/docs/drivers.md`) against `firmware/boards/`, the
  architecture diagram's stack and module boxes, the README `**Version:**`
  line against `server/pyproject.toml`, the cloud command gate
  (`target_kind`, channel pattern, `ota_step` names), the retention tiers in
  `docs/data-flow.md`, the Grafana metric list, the vendor write actions, and
  a parse check for every Mermaid flowchart.
- **Docs fix round (2026-10).** The Aranet, Pulse and vendor-skeleton docs
  say vendor readings are stored and exported but never drive automation
  rules or safety alerts (only MQTT node telemetry does). No doc shows a
  shipping mobile app any more: README, `docs/dual-repo-architecture.md`,
  `docs/cloud-relay-flow.md` and `docs/auth.md` drop the iOS/Android app,
  `guardWriteAction` and FCM push, and `wiring-overall-system.svg`'s
  bottom-right box is now *Remote Access (Browser)*. The cloud docs put
  FastAPI on internal `127.0.0.1:9001` and the relay's ownership recheck at
  60 s. README: remote control is premium only (no read-only free path), QR
  labels open the Sessions or Cultures page, `SPOREPRINT_OTA_PUBKEY_B64`
  also verifies signed node manifests on Docker, `SPOREPRINT_CLOUD_URL`
  takes `https://` (plain `http://` only to a LAN dev relay), and the
  Development and Contributing commands match `AGENTS.md`. The submodule SHA
  is pinned by its gitlink, not `.gitmodules`. `AGENTS.md`: no CI runs on
  push or PR, parallel PlatformIO and `uv sync` pitfalls, REST and relay
  payloads are additive-only too, the LAN-only CORS rule, the version
  strings `bump.sh` rewrites, every trigger for stale Builder data, and the
  general import-cycle rule; its frontend brief points at the monorepo.
- README: the Chambers page loads chamber readings and events when it opens
  (only the Pi system panel polls); Chamber inventory shows the maintenance
  log, lifetime stats and photos, and chambers are created and given nodes
  through `POST`/`PATCH /api/chambers` only; a chamber follows its active
  grow's targets; the dashboard rebuild runs `port_builder.py` in the
  server's environment. The Agrowtek notes say where its readings go
  (`agrowtek:<sensor id>`; `sensor_mappings` is not used yet). The partition
  tables' comments name the envs that build with them and no longer call core
  2.0.17 the pinned core. `AGENTS.md` lists the lint and vendored-Monocypher
  guard suites and says never to edit the vendored copy. A
  `.worktreeinclude` copies the operator's git-ignored `CLAUDE.md` into each
  Claude Code worktree.
- **The active category is described, never named, in public docs.** The
  README's Species Library lists it as "species that are controlled or
  restricted in many jurisdictions" (it named the genus) and carries the
  dashboard's education-and-research notice; `docs/species-reference.md` and
  `docs/feature-status.md` say the same. `tests/test_active_species_public_docs.py`
  builds every active profile's common, strain, scientific, genus and
  epithet names from `profiles.py` and fails if any tracked Markdown file or
  anything under `docs/` uses one (word-bounded, case-blind), and checks the
  notice is where the category is described.
- `docs/cloud-relay-flow.md` and `docs/dual-repo-architecture.md` list
  browser notifications from `sporeprint.ai` (Web Push) beside the Pi's ntfy
  for premium accounts (they said browser push was not live yet). README,
  `docs/architecture-overview.svg` and `docs/dual-repo-architecture.md` name
  Vite 8, which now builds the dashboard. `docs/dual-repo-architecture.md`
  also names Next.js 16 for the cloud web app and calls the paid side "the
  commercial layer" without a repository name.

### Dependencies and CI
- anthropic 0.94 → 1.11, fastapi 0.135 → 0.142, starlette 1.0 → 1.7
  (Host-header bypass of the API-key gate fixed), cryptography 45 → 50.0.2
  (wheels bundle OpenSSL 4.0.3; now the floor), pillow 11.3 → 12.3, icalendar
  6.3 → 7.3 (no code change: the calendar feeds use none of 7.0's moved or
  removed APIs), uvicorn 0.54, python-multipart 0.0.32, python-socketio 5.17 /
  engineio 4.14, pydantic-settings 2.15, ruff 0.16. `server/uv.lock`
  regenerated (it was missing four runtime dependencies).
- GitHub Actions pinned to commit SHAs at current majors; PlatformIO 6.2.0 in
  CI and release; the release job alone gets write access.
- **Firmware releases are signed.** A `firmware-vX.Y.Z` tag
  (`.github/workflows/firmware-release.yml`) now publishes, per image env, a
  zip with `firmware.bin`, `bootloader.bin`, `partitions.bin` and the signed
  release manifest `<env>.manifest.json` + `.sig`, every image built with the
  release verify key compiled in (the release notes print it). The signing
  key (secret `OTA_SIGNING_KEY`) reaches only one step in each of two jobs
  that run no build tooling, no third-party action and no write token: one
  derives the public key, the other signs. The PlatformIO builds get the
  public key only, and the job that creates the release holds a write token
  but never the key. The two key jobs run in a `firmware-release`
  environment, so the key can be scoped to release tags there
  (`docs/firmware-security.md`). The workflow fails closed without the
  secret, accepts only exact `firmware-vX.Y.Z` tags, refuses a tag whose
  `firmware/VERSION.txt` differs, and restores no build cache. Its key, sign
  and release jobs install only the hash-pinned `cryptography` wheels
  `server/uv.lock` records; the build installs PlatformIO 6.2.0 and its
  dependencies from the new hash-pinned `firmware/requirements-pio.txt`,
  creates the platform's own Python virtualenv from the new hash-pinned
  `firmware/requirements-penv.txt` and builds with uv offline (so the
  platform's open version floors fetch nothing from PyPI), then fetches the
  pioarduino platform zip and the framework and tool packages it builds
  with, and refuses any whose SHA-256 differs from the new
  `firmware/toolchain.lock.json` (`scripts/pin_firmware_toolchain.py`,
  which also refuses a platform whose virtualenv wants an unpinned package
  and fails the build if anything was installed from an unchecked URL or the
  virtualenv holds an unpinned package). The toolchain binaries come
  through Espressif's `idf_tools.py`, which checks them against the SHA-256
  in those packages. The first job records the tagged commit, and every later job
  stops unless the tag still names it, so a tag moved during a run releases
  nothing. The new
  `scripts/verify_firmware_release.py` checks every zip as the Pi and the
  node will (signature, canonical manifest, env, version, channel, SHA-256,
  size, cross-checked with the Pi's own verifier) and that each image is for
  its env's chip with the verify key, env and version compiled in; the
  workflow runs it after signing and again just before publishing, and
  anyone can run it on a downloaded zip. The release notes' USB flash
  commands erase the flash first, since the zips carry no OTA boot
  selection. Tests: the script against the committed manifest vectors and
  tampered zips; the workflow's triggers, permissions, key scoping,
  environment, SHA pins, tag guard and env list; and its sign, zip and
  verify scripts run under bash (`tests/test_verify_firmware_release.py`,
  `tests/test_firmware_release_workflow.py`); the toolchain lock and its
  checks (`tests/test_pin_firmware_toolchain.py`).
- `ruff check app/` passes again (unused imports and placeholder-less
  f-strings removed; E402 is ignored by design for `app/main.py` and the
  vendor `__init__.py` files) and `tests/test_lint.py` keeps it green.
- Every dependency checked against its latest stable release on 2026-10-06:
  the Python packages, base and service images, PlatformIO libraries
  (PubSubClient 2.8, ArduinoJson 7.4.3, Monocypher 4.0.3: already current)
  and workflow actions (already current). The Python base image stays on the
  3.12 line.
- The lint gate's rule set is pinned in `server/pyproject.toml`
  (`select = ["E4", "E7", "E9", "F"]`, the rules it has always checked): ruff
  0.16 widened its implicit default from 59 rules to 413, and a ruff upgrade
  must not change the gate by itself.
- The unused `vision` extra is gone from `server/pyproject.toml`: nothing
  imported its runtimes (the local CNN pass is still a stub), and its
  `tflite-runtime` has had no release since 2023 and no wheel for Python 3.12.
  The runtime the CNN loads comes back with the change that builds it. The
  stub result's `note` no longer tells you to install the extra.
- FastAPI 0.142 brings `opentelemetry-api`. It stays a no-op: the image
  installs no OpenTelemetry SDK or exporter, and compose forwards no `OTEL_*`
  variable, so no traces, metrics or logs leave the Pi.
- **Dependabot** (`.github/dependabot.yml`): weekly version updates for the
  server's uv lock, the server and ui base images, the compose service images
  and the workflow actions, with a release-age cooldown. uv and Actions
  minor/patch updates are grouped; image updates come one PR each. No CI
  runs on its pull requests (Actions are release-gated), so each one is
  verified locally before merging; PlatformIO pins and the firmware
  release's hash-pinned Python requirements stay manual.

## [5.0.0] - 2026-07-16

Production-wiring release, in lockstep with the cloud repo (v5.0.0). The Pi
server grows the endpoints the cloud-web + mobile surfaces needed to stop
rendering fixtures, the automation engine gains remote pause/suspend plus a
bounded manual override, and self-hosting becomes a single command. Firmware
is a version-only bump — no functional change (see `firmware/CHANGELOG.md`).

### Added
- **Pre-grow automation coverage** — `GET /api/chambers/{id}/automation-coverage`
  returns, per grow phase, the actuator requirements and whether each is
  actually satisfied by a paired actuator (with a named fallback, e.g.
  vent-with-fans for a missing dehumidifier). Lets the UI warn before a grow
  starts that the hardware can't hold the species' targets.
- **Node discovery + claim** — `GET /api/hardware/discover` lists every LAN
  node the Pi has heard from (the heartbeat registry), tagged
  claimed/unclaimed; `POST /api/hardware/claim` adopts an unclaimed,
  heard-from node.
- **Dated grow-cycle proposal** — `propose_cycle` walks a species' real phases
  from an inoculation date into a contiguous dated calendar with per-phase
  setpoints and a projected harvest date; served as JSON at
  `GET /api/planner/propose` and as a calendar feed at
  `GET /api/planner/propose.ics`.
- **Remote automation control** — the engine gains `set_paused` (whole-engine
  pause, persisted to `user_settings`) and `suspend_rule` (expiring
  single-rule suspension), both drivable from the cloud relay via the
  `system` / `automation` command targets.
- **One-command self-host** — `install.sh` installs Docker + Compose,
  generates MQTT credentials + self-signed TLS, writes a LAN-trust `.env`
  (`SPOREPRINT_ALLOW_UNAUTHENTICATED=true` — the single-household posture:
  pi-ui calls `/api` same-origin with no bearer, while MQTT stays
  credentialed), and brings the stack up healthy. The Pi server also ships as
  a signed (Ed25519) OTA bundle, published by the cloud repo's
  `server-release.yml` to `updates.sporeprint.ai`.

### Changed
- **Vision auto-analysis on camera ingest** — a new frame at
  `POST /api/vision/frame` now schedules a throttled (15-min per session),
  BYOK-gated Claude pass that raises green-mold / Trichoderma contamination
  and harvest-ready alerts on its own, rather than only analyzing on explicit
  request. Gated on an active session and the operator's own Claude key.
- **Manual overrides are bounded and auto-resume** — every `ManualOverride`
  is clamped to a 24h TTL at construction (a null or over-long expiry can no
  longer pin an actuator forever), and expired overrides are swept back out
  automatically so the rules engine resumes control. The cloud actuator path
  routes through this via `target_kind="automation"`.
- **`docker-compose.yml` hardened** — healthchecks on server/mqtt/ntfy,
  `restart: unless-stopped`, a non-root server (`USER appuser`) with a
  one-shot `init-perms` volume `chown`, read-only bind mounts for config and
  certs, and a credentialed + ACL'd broker.

### Fixed
- **Species-id lookup drift** — `get_profile` now canonicalizes the `_` vs `-`
  separator, so a stored id resolves to its built-in profile regardless of
  spelling. A plain `WHERE id = ?` had missed 63 of 74 species and returned
  `None`.

## [4.2.0] - 2026-06-12

### Added
- **Firmware v2** — see `firmware/CHANGELOG.md` for the full entry: one
  unified node image + a camera image, portal-based provisioning,
  autodetecting sensors (incl. SHT4x family, SCD30, MH-Z19C, HX711, reed
  switch), opt-in TLS MQTT, a 69-case host-native test suite, and the v1
  defect class fixes (WDT-vs-portal boot brick, publish truncation,
  HMAC key corruption).
- Pi server consumes the firmware observability topics nothing ever read:
  node log batches land in a retained `node_logs` table (+
  `GET /api/hardware/nodes/{id}/logs`), coredump chunks reassemble to
  `data/coredumps/` with an alert on completion (+ list/download
  endpoints), and node OTA lifecycle events forward as `node_ota`.
- `GET /api/provision/ca` serves the broker CA for the firmware's
  trust-on-first-use TLS pinning; `setup.sh` generates the local CA +
  server certificate and mosquitto gains an 8883 TLS listener.
- Hardware guides + builder data updated to v2 reality: the SHT4x family,
  SCD30, and MH-Z19C flip from "needs firmware driver" to supported;
  Tier 3's load cell and reed switch are live features; the ESP32-S3
  DevKitC-1 gains a build target (bench verification pending); the reed
  wiring now documents the required EXTERNAL 10K pull-up (GPIO 34-39
  have no internal pulls — the old instructions were physically
  impossible).

### Changed
- Heartbeat ingestion refreshes `node_type` on every heartbeat and stores
  the v2 `roles` list; cloud command routing consults roles so a combined
  sensors+relay node receives climate-targeted commands. (The old upsert
  never updated the type — rows decayed to 'unknown' and type-routed
  commands quietly failed.)
- Firmware bundle downloads serve the v2 images (unified node + camera);
  v1 bundle slugs alias to the unified node so old links keep working.
- `docs/firmware-security.md` rewritten for the v2 model (command
  signing, TLS TOFU, provisioning, watchdog policy); the secure-boot /
  flash-encryption opt-in walkthrough is unchanged.

### Fixed
- docker-compose bound the MQTT broker to the host loopback — LAN nodes
  could never reach 1883 at all. The broker now listens on the LAN
  (credentials + ACL unchanged) alongside the new TLS listener.

## [4.1.6] - 2026-06-11

### Changed
- Hardware guides refreshed (June 2026 audit): the ESP32-WROOM-32 38-pin
  DevKit is the documented node board — it matches the firmware build targets
  (`esp32dev`) and the GPIO map in every wiring diagram. ESP32-S3 boards are
  explicitly marked unsupported until S3 build envs ship. The AI-Thinker
  ESP32-CAM is the documented camera board (matches the `esp32cam` build
  target and pin map).
- SCD41 sourcing notes updated — Adafruit 5190 is in stock again; the old
  "avoid Adafruit" advice removed. SHT31-D notes clarify that SHT4x-family
  sensors share the I²C address but not the command set, and are not
  drop-ins until a driver ships.
- Prices re-baselined across all tiers (including 2026 Raspberry Pi shortage
  pricing). Tier cost estimates recomputed: ~$180 / ~$350 / ~$540.
- Tier 3 load cell and reed switch rows now say "firmware support planned" —
  the relay firmware does not read them yet.
- Wiring diagrams: node labels corrected to ESP32-WROOM-32 / micro-USB
  (previously ESP32-S3 / USB-C); camera labels corrected to ESP32-CAM
  (OV2640). No pin assignments changed.
- `models/esp32_case.scad` defaults now fit the ESP32-WROOM-32 38-pin DevKit
  (28x52mm, micro-USB cable cutout); ESP32-S3 dimensions remain available via
  parameters. `cam_mount.scad` and `power_supply_mount.scad` notes updated
  (incl. Mean Well GST60A12 sizing parameters).
- `models/sensor_mount.scad` redesigned as a three-bay enclosure sized for
  the canonical Adafruit breakouts (SHT31-D, SCD41, BH1750) with wire
  pass-through notches for the I2C daisy chain and engraved bay labels —
  the previous two-bay version could not physically fit the SHT31-D or
  SCD41 boards it was documented for.
- Every printable model now carries an engraved SporePrint wordmark
  (previously only the relay mount was branded). All 8 models render
  clean — the earlier non-manifold warnings on cam_mount, fan_duct, and
  relay_board_mount are resolved.

### Fixed
- `sensor_mount.scad` lid ventilation holes were subtracted from a
  zero-size cube — a geometric no-op — so printed lids had no vents at
  all despite airflow over the sensors being critical for accurate CO2
  readings. The vents are now a real cut through the lid plate.
- Setup steps now instruct setting the Pi hostname to `sporeprint` (Raspberry
  Pi Imager advanced options) so ESP32 nodes can reach the MQTT broker at
  `sporeprint.local` out of the box.

## [4.1.5] - 2026-05-03

### Added
- Pi-side integration health sweeper + state-snapshot pusher (#38).
- Session events for vendor integration rule fires — the timeline now shows
  which vendor device was driven and how (#37).

## [4.1.4] - 2026-05-03

Pi side of the v4.1.4 release: automation engine fires vendor write actions, integrations RPC frames are HMAC-verified.

### Added
- `app/automation/models.py` — `RuleAction` gains `vendor_slug` / `vendor_action` / `vendor_params` (all optional, default None preserves v3.x behaviour).
- `app/automation/engine.py` — `_fire_rule` routes vendor-action rules through `app.integrations._actions.dispatch`; native MQTT path untouched. Failure handling matches the existing audit trail (`automation_firings` row updates to `status='failed'` with the error string).
- `app/cloud/integrations_proxy.py` — verifies HMAC-SHA256 signatures on inbound `integrations_request` frames using `app.cloud.signing.verify_frame` with the device's `cloud_token`. Bad signatures return `{success: false, status: 401}` with a precise reason field. Unsigned frames still accepted during the v4.1.4 rollout window.

### Changed
- Lockstep version bump with cloud parent v4.1.4.

### Notes
- **Vendor write actions inherit the existing safety surface.** Manual overrides (`manual_overrides` table) lock vendor targets the same way they lock MQTT targets — set `target = "vendor:<slug>"` to scope.

## [4.1.3] - 2026-05-02

Adds TP-Link Tapo as the third LAN smart-plug driver alongside Wemo and Kasa. Dual-transport (free local KLAP / premium tplinkcloud.com cloud), mirroring Pulse's hybrid shape. Lockstep with cloud parent v4.1.3.

### Added
- `app/integrations/tapo/` — driver, config, KLAP cipher implementation. `set_power` + `set_dim` write paths exposed via the unified vendor-actions dispatcher. SHA-1 in the user-hash is a TP-Link wire-protocol requirement (documented in `klap.py` and `.semgrepignore`).

### Changed
- `app/integrations/__init__.py` imports the `tapo` sub-package so it self-registers on boot.
- `app/integrations/_actions.py` advertises tapo's `set_power` + `set_dim` actions.
- `ui/dist/` rebuilt to ship the parent monorepo's Tapo schema + dual-transport UI.

### Notes
- **Live-device verification needed** — the KLAP handshake + cipher round-trip are unit-tested; on-wire behaviour against real Tapo firmware will be verified by operators with paired devices.

## [4.1.2] - 2026-05-02

Vendor write paths land across the integrations grid; two new free-tier smart-plug drivers ship end-to-end. Lockstep with cloud parent v4.1.2.

### Added
- **`app/integrations/_actions.py`** — single-map dispatcher for vendor write actions. Each driver advertises its writable actions in `VENDOR_ACTIONS`; the dispatcher filters payload kwargs to what the method accepts so stray fields don't blow up the call.
- **Write methods on every existing v4.1.1 driver**:
  - `set_dim(fixture_id, percent)` — Fluence, Fohse, BIOS.
  - `set_setpoint(target_c, mode?)` — Trane.
  - `set_setpoint(humidity_pct)` — Quest, Anden.
  - `set_output(output_id, value)` — Agrowtek.
- **Wemo driver** (`app/integrations/wemo/`) — UPnP/SOAP on TCP/49153. On/off control + Wemo Insight power-monitoring poll. SOAP envelopes inline; no new pip dep.
- **Kasa driver** (`app/integrations/kasa/`) — encrypted JSON on TCP/9999. XOR cipher (rolling key seeded at 0xAB) implemented inline; round-trip tested. On/off + dim (HS220) + emeter power-monitoring.
- **Cloud RPC handler** at `app/cloud/integrations_proxy.py` learns a new `vendor_action` action type that forwards inner-action + payload to the dispatcher, so cloud-web writes route through the same Socket.IO futures map as reads.
- **`docs/integrations/smart-plugs.md`** — operator-facing setup for Wemo + Kasa plus the full vendor-actions table.

### Changed
- `app/integrations/__init__.py` imports `wemo` + `kasa` so they self-register on boot.
- `ui/dist/` rebuilt to ship the parent monorepo's vendor-actions UI block + the Wemo/Kasa schemas.

### Notes
- **Write paths join the same "needs live-device verification" caveat as v4.1.1 reads.** Tolerant pydantic + dispatcher payload-filter mean unknown shapes degrade gracefully; refinements based on real hardware are additive.

## [4.1.1] - 2026-05-02

Adds seven new vendor drivers as defensible skeletons covering the Growlink-style lighting / HVAC / controller surface. Lockstep with cloud parent v4.1.1.

### Added
- **`server/app/integrations/_http_skeleton.py`** — shared `HttpVendorDriver` base. Subclasses override `poll_once()` and `test_connection()`; the base handles asyncio task lifecycle, idempotent start/stop, and `disabled → ok → degraded → error` health transitions.
- **Seven new vendor drivers** (each in its own `app/integrations/<slug>/` subpackage):
  - **Agrowtek GCX** (free, LAN HTTP) — controller bridge polling `/api/sensors`.
  - **Trane Nexia / BAS** (premium, cloud) — HVAC telemetry against `mynexia.com`.
  - **Fluence FluenceID** (premium, cloud) — fixture telemetry.
  - **Quest dehumidifier** (free, LAN HTTP) — temperature / humidity / setpoint.
  - **Anden dehumidifier** (free, LAN HTTP) — same shape as Quest plus power monitor.
  - **Fohse FohseConnect** (premium, cloud) — fixture telemetry.
  - **BIOS Lighting** (free, LAN HTTP) — fixture dim / power / temperature.
- **`docs/integrations/lighting-hvac-skeletons.md`** — operator-facing overview of the skeleton approach, per-vendor notes, what's NOT in v4.1.1, workflow for refining a parser when an operator hits live hardware.

### Changed
- `app/integrations/__init__.py` imports the new vendor sub-packages so they self-register on boot.
- `ui/dist/` rebuilt from the parent monorepo's `frontend/packages/pi-ui` so the compiled LAN UI's `/integrations` page renders the new vendor schemas.

### Notes
- **Live-device verification needed.** Vendor API shapes inferred from documentation only. Tolerant pydantic models accept payload-shape variance; `test_connection` surfaces transport errors verbatim. Operators with paired hardware should report unexpected payloads so the parser gets refined without shipping speculative code.
- **Read-only.** v4.1.1 ships the read side (poll → telemetry pipeline) of every new driver. Vendor write paths land in v4.1.x.

## [4.1.0] - 2026-05-02

First cut of the v4.1 third-party-integration grid on the Pi. Drivers run locally on each Pi; data stays on the LAN unless a vendor's API requires the cloud (premium-gated).

### Added
- **`server/app/integrations/`** — driver framework: `IntegrationDriver` ABC, encrypted-at-rest settings store (per-Pi Fernet key), registry-backed `/api/integrations/*` HTTP surface, lifespan boot with per-driver failure isolation.
- **Grafana / Prometheus exporter** (free) — `/metrics` endpoint in Prometheus text format with chamber/sensor/session/contamination/actuator metrics. Optional bearer-token gate.
- **Aranet PRO LAN poller** (free) — polls the PRO base station's local API and merges its sensors into the existing telemetry pipeline.
- **Pulse Grow dual-transport driver** (free local / premium cloud):
  - Cloud transport against `api.pulsegrow.com` with email + password (encrypted at rest, exchanged for session token on first poll).
  - Local transport with UDP discovery on the LAN broadcast (port 5683 CoAP convention) + per-device HTTP polling. Operators can skip discovery entirely with `local_device_urls`.
- **Cloud RPC handler** at `app/cloud/integrations_proxy.py` — listens for `integrations_request` events on the cloud connector socket, dispatches to local registry handlers, emits `integrations_response`. Powers the cloud-web mirror in the parent repo.
- **Per-vendor docs** in `docs/integrations/{grafana,aranet,pulse}/README.md` covering setup, troubleshooting, and operator-facing contracts.
- **Starter Grafana dashboard JSON** at `docs/integrations/grafana/sporeprint-chamber-dashboard.json`.

### Changed
- `ui/dist/` rebuilt from the parent monorepo's `frontend/packages/pi-ui` so the compiled LAN UI ships the new Integrations page + sidebar entry.

### Notes
- **Pulse local-mode discovery probe needs live-device verification.** Parser is tolerant of unknown payload shapes (degrades to empty rather than crashing). Refinements based on real hardware will be additive parser branches in v4.1.x.

## [4.0.7] - 2026-05-02

Lockstep version bump — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.6] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.5] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.4] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.3] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.2] - 2026-05-01

Lockstep version bump only — no Pi-side, server, UI, or firmware changes.

## [4.0.1] - 2026-05-01

Lockstep version bump only — no Pi-side code, server, UI, or firmware changes in this release. All v4.0.1 deltas are in the parent cloud monorepo (cloud-web landing page, Dockerfile + start.sh runtime aliasing, middleware allow-list expansion, GHA deploy-job disable, jsdom lockfile sync, placeholder cleanup). The submodule pointer moves with the parent so `release-guard.sh`'s lockstep invariant stays green.

## [4.0.0] - 2026-04-30

Major version bump in lockstep with the cloud parent repo's v4 migration (Vite SPA at `/app/*` → Next.js 15 App Router at `/`). Pi-side scope this release: OTA progress event fan-out, Ed25519 OTA signing helpers, Pi UI v4 dist bundle, and a `/simplify` pass on the cloud connector + settings router. No GPIO / I2C / PWM pin changes; firmware-specific notes live in `firmware/CHANGELOG.md#400`.

### Added

- **OTA progress events.** `server/app/cloud/ota.py` now emits per-step progress via a new `_emit_step()` helper that calls `forward_event("ota_step", payload)` on the cloud relay. Cloud parent persists each step into the new `ota_progress_events` Supabase table so the mobile app + cloud-web shell can render a real progress bar instead of polling for terminal success/failure. `_promote_and_restart` was split into `_promote` and `_restart_unit` so each phase emits its own event.
- **OTA signing helpers in `scripts/`** — `generate-ota-keypair.py` (Ed25519 keypair generator) and `sign-ota-bundle.py` (signs an OTA tarball with the operator's private key). The cloud parent verifies the signature before promotion via `PUT /settings/ota-pubkey`. Operator workflow documented in `docs/firmware-security.md`.
- **Pi UI v4.0.0 dist bundle** in `ui/dist/`, compiled from the parent monorepo's `frontend/packages/pi-ui/`. Pi-served LAN UI now matches the cloud-web design system (warm substrate palette, JetBrains Mono numerics, shared SporePrintMark canvas).

### Changed

- **`server/app/cloud/ota.py` simplified** — removed the unused `_promote_and_restart` back-compat wrapper after callers were updated to the split `_promote` + `_restart_unit` pair. Stripped narrational comment overhead (-136 LOC).
- **`server/app/settings_router.py` simplified** — removed five redundant `try/except Exception → 500` patterns that just leaked exception text instead of letting FastAPI's default error handler do the right thing (-26 LOC).
- **`server/app/cloud/service.py`** — `forward_event()` extended to accept the new `ota_step` channel alongside the existing telemetry/alert channels.
- **Lockstep v4.0.0 version bump** with the cloud parent. No Pi-protocol break; v3.4.x Pis interoperate with a v4 cloud and vice-versa for telemetry, command signing, pairing, and HMAC. Web-app surface URL change (`/app/` → `/`) is parent-only.

### Fixed

- (none — `/simplify` cleanup + additive OTA-step plumbing only.)

## [3.4.10] - 2026-04-24

Lockstep version bump — no Pi or firmware changes. Firmware build unchanged.

## [3.4.9] - 2026-04-24

A fresh audit of v3.4.8. All Critical, High, Medium, Low + operator-feedback items closed in one pass. Firmware grew real defense-in-depth at the MQTT layer; the cloud relay gained tier/ownership re-checks + rate limiting + `cmd_id` correlation; the Pi server got structured logs + split MQTT ACL + synced dependency pins. Firmware-specific narrative in `firmware/CHANGELOG.md#349`.

### Added

- **HMAC verification of inbound MQTT commands on every ESP32 node** (`sporeprint_common/frame_verify.{h,cpp}`). The cloud-signed chain now extends past the broker to firmware. Shared canonical-JSON serialization is byte-identical to the Python `signing.py`. Uses mbedtls (part of ESP-IDF — no new dep).
- **NTP sync at WiFi connect** so the 30-second replay window on firmware command frames is meaningful (`wifi_manager.cpp`).
- **`scripts/provision-node.sh`** — generates an HMAC key, writes to `server/.env`, prints the `pio run` commands to bake the key into each node's NVS via `-DSPOREPRINT_PROVISION_HMAC`.
- **`esp_task_wdt` on climate / lighting / cam nodes** (M-6). Parity with relay_node; timeouts tuned per node (30 / 10 / 60 s).
- **`esp_reset_reason()` + wifi/mqtt reconnect counters** in every heartbeat (`heartbeat.cpp`).
- **OTA lifecycle MQTT events** on `sporeprint/<id>/ota` (start / success / error).
- **Minimum 12-char OTA password** (L-6).
- **Split Mosquitto users**: `sp-cmd` / `sp-telemetry` / `sp-3p`. Replaces the single `server readwrite #` account. `scripts/rotate-mqtt-creds.sh` rotates them.
- **`docs/firmware-security.md`** — operator guide for secure boot v2 + flash encryption + signed OTA.
- **Firmware `VERSION.txt`** + `SPOREPRINT_FW_VERSION` build flag — no more hardcoded `"0.1.0"`. `scripts/bump.sh` keeps it in lockstep.
- **`firmware/CHANGELOG.md`** — firmware changes now have their own narrative.
- **`.github/workflows/firmware-ci.yml`** — `pio run` on all four envs for every PR touching `firmware/**` (Risk 15).
- **Unity test-harness scaffold** at `firmware/test/` (Prescription 6.3.14 — opens the path).
- **`/api/vision/frame` whitelisted** in the Pi ApiKeyMiddleware (L-9).
- **Structured JSON logs on the Pi** with contextvar-based `request_id` threading (`logging_config.py` + `_request_id_mw.py`).
- **`_task_registry` wired** — every long-running supervisor registers + transitions status. Previously declared but never called.
- **`DesktopShell` component** (`app/src/components/web/DesktopShell.tsx`) — shared shell for the 18 desktop pages. Migration tracker in `app/src/pages/web/README.md`.

### Changed

- **Relay command handler refuses bare `{}` payloads** (M-5). Previously defaulted `state=on, pwm=255`.
- **Case-insensitive `state` parse** in relay_node.
- **`millis()` wrap-safe `offAt` compare** (L-1).
- **Cam `server_url` allow-list** (H-1). Allowed: paired Pi LAN, `sporeprint.local`, `sporeprint.ai`, RFC1918.
- **Climate alerts emit separately** — simultaneous conditions no longer collapse.
- **MQTT inbound buffer 512 → 1024 bytes** (L-2). Oversize frames now explicitly dropped with a Serial log.
- **`OfflineBuffer::BUFFER_FILE` constant removed**.
- **`safety_cutoffs` + `captureFail` + `captureSuccess` + `avgLatencyMs` counters now increment**.
- **Pi `pyproject.toml` gains upper-bound caps** on every dep to match cloud policy (L-3).

### Fixed

- **`mqtt_publish()` signs every cmd/\* frame** with `settings.mqtt_hmac_key` before publishing. Paired with firmware verify, the Pi↔ESP32 hop is now HMAC-authenticated end-to-end.

## [3.4.8] - 2026-04-23

Firmware CI hygiene — all four node builds now compile clean against a pinned `platformio/espressif32@6.13.0` platform. Pre-existing build breaks from mixed Arduino-ESP32 API usage fixed without changing any GPIO / I2C / PWM pin assignment. No protocol or runtime behavior change.

### Changed

- **`firmware/platformio.ini`:** pinned `platform = espressif32@6.13.0` (official, Arduino-ESP32 core 2.x). Previously unpinned — fresh `pio install` pulled whatever latest happened to be, and the code's mix of core-2.x and core-3.x APIs compiled against neither.
- **`firmware/src/relay_node/main.cpp`:** replaced core-3.x `ledcAttach(pin, freq, resolution)` with the core-2.x `ledcSetup(channel, freq, resolution)` + `ledcAttachPin(pin, channel)` idiom. GPIO assignments (`CHANNEL_PINS[] = {25, 26, 27, 14}`) unchanged.
- **`firmware/src/lighting_node/main.cpp`:** same PWM API swap. GPIO assignments unchanged.
- **`firmware/src/climate_node/main.cpp`:** ClosedCube SHT31D 1.5 `readSerialNumber()` returns `uint32_t` directly, not an `SHT31D` struct. Reworked the sensor-present probe to check the serial number is non-zero instead of inspecting a `.error` field that doesn't exist on the 1.5 API. I2C address (`0x44`) unchanged.

### Fixed

- All four PlatformIO envs (`relay_node`, `climate_node`, `lighting_node`, `cam_node`) build cleanly from a fresh `pio install`. Post-install dev setup also needs `python3 -m pip install intelhex` for esptool's bootloader-assembly step on macOS with Homebrew Python 3.14.

## [3.4.7] - 2026-04-23

Independent code audit. 12 fixes across firmware safety, server concurrency, UI error visibility, and ops hardening. No breaking protocol changes; mobile + cloud clients unchanged.

### Added

- **Toast notification system** — `ui/src/stores/toastStore.ts` + `ui/src/components/ui/Toaster.tsx`. Replaces 26 silent `.catch(() => {})` / `catch { /* ignore */ }` swallows across 13 pages/components. Fetch failures now log with context to the console and surface a dismissable toast in the UI. `reportFetchError(context, err, userMessage)` is the single entry point.
- **`allow_unauthenticated` config flag (`server/app/config.py`)** — explicit opt-in for running the Pi without `SPOREPRINT_API_KEY`. Default is `False`; the server refuses to boot when both the key is empty and the flag is false. When opted in, a loud startup WARNING replaces the silent LAN-trust behavior. `docker-compose.yml` defaults the env var to `false` — fresh stacks must set it to `true` explicitly or provide an api_key.
- **`_SESSION_UPDATE_COLUMNS` whitelist (`server/app/sessions/service.py`)** — defense-in-depth for the (already Pydantic-typed) update column set.
- **Docker healthchecks** — `server` (urllib → `/health`), `mqtt` (`mosquitto_sub` on `$SYS/broker/version`), `ntfy` (`wget /v1/health`). `depends_on` upgraded to the long form with `condition: service_healthy` so `server` waits for the broker to actually accept subscriptions and `ui` waits for the API to respond.
- **AbortController for Vision analyze** — `ui/src/pages/Vision.tsx` now cancels in-flight `POST /vision/frames/{id}/analyze` when the user clicks a different frame. `api.post`/`get`/etc. accept an optional `{ signal }` option. Prevents stale responses clobbering the newer frame's state.

### Changed

- **`sessions.update_session` collapsed from N-per-column UPDATEs to a single `UPDATE ... COALESCE(?, col) ...`** statement. Partial failure mid-loop can no longer half-write a row; also 1 DB round-trip instead of up to 12.
- **`automation.engine` — `_state_lock: asyncio.Lock`** guards read-modify-write spans on `_overrides`, `_rule_cache`, `_last_fired`. `_load_overrides_from_db` fetches into a fresh dict and atomically swaps under the lock so concurrent evaluators never observe a cleared cache. `get_overrides` expiry sweep is lock-protected.
- **`cloud.service` — `_replay_lock: asyncio.Lock`** guards `_seen_command_ids` OrderedDict. Check-and-insert is atomic; two concurrent frames carrying the same command id can no longer both pass the dedup test. Socket emit is done outside the lock.

### Fixed

- **Firmware FW-1 (`relay_node/main.cpp`):** MQTT `duration_sec` is now clamped to `[1, 3600]` seconds before computing the off-at deadline. Previously, a huge or negative payload could wrap the `millis()` arithmetic and latch a relay ON indefinitely — the worst failure mode for a heater/humidifier.
- **Firmware FW-2 (`relay_node/main.cpp`):** ESP32 task watchdog armed at 10 s. `loop()` resets on each iteration; any deadlock in MQTT/OTA/WiFi now triggers a reboot. Safe state on reset is all-channels-OFF (setup() enforces).
- **Firmware FW-3 (`wifi_manager.cpp`):** Captive portal now has a 10-minute timeout. An abandoned provisioning session reboots the node rather than leaving it stranded in AP mode forever.
- **Firmware FW-4 (`climate_node/main.cpp`):** `read_interval_ms` and `publish_interval_ms` MQTT payloads are clamped to sensible ranges (1s–10min read, 5s–1h publish) with Serial warn on out-of-range. A `read_interval_ms=0` payload previously would busy-loop `readSensors()` and starve the MQTT/OTA tasks.
- **README:** removed broken `ui/public/mushroom-logo.svg` `<img>` reference. Renamed two `CLAUDE.md` references to `AGENTS.md` (the file that actually exists in this repo).
- **Tests:** `server/tests/conftest.py` sets `SPOREPRINT_ALLOW_UNAUTHENTICATED=true` at import so the test process can boot under the new secure-by-default behavior.

## [3.4.6] - 2026-04-23

No Pi protocol or code changes. Lockstep version bump.

## [3.4.5] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.4] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.3] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.2] - 2026-04-22

No Pi protocol changes. Lockstep version bump.

### Changed

- **L-4 `_configure_token` multi-slot dict.** Pre-v3.4.2 carried a single `dict | None` global — a second parallel `/pair` would overwrite the first's token and invalidate it before the first client could `/configure`. Now keyed by token in `_configure_tokens` with TTL sweeps and a 32-entry hard cap. Parallel `/pair` sessions coexist; pair-spam attackers can't blow memory.

## [3.4.1] - 2026-04-21

No Pi-side functional changes. Lockstep version bump.

All Pi protocols (HMAC signing, pair-verify, MQTT auth, bearer API-key gate) remain byte-compatible with v3.3.3+ / v3.4.x clouds.

## [3.4.0] - 2026-04-21

No Pi-side functional changes. Lockstep version bump.

### Changed

- `scripts/bump.sh` now matches the cloud-side bump script: auto-inserts a CHANGELOG skeleton for the new version, updates the README's `**Version:**` banner if present, and prints a doc-drift warning for any lingering `v${CURRENT}` references in README / docs.

### Documentation

- README banner rewritten to explain the new commercial/OSS split: the Pi repo stays AGPL-3.0 free software; cloud-relay/mobile/web-app are paid. Pi-standalone users are unaffected.
- Added historical release callouts for v3.3.3 / v3.3.4.

## [3.3.4] - 2026-04-20

Cloud-side audit close-out — the Pi changes in this release are support endpoints for the cloud's updated pairing + command-signing flows.

### Added

- **`GET /api/cloud/pair-verify?configure_token=<tok>`** (`server/app/cloud/router.py`). Closes S-M-11: the cloud now calls this endpoint from its own network during `POST /devices/pair` to confirm the configure_token really was issued by this Pi. Prevents a hostile LAN host from tricking the mobile app into writing an attacker-chosen device_token into Supabase.
- Signing-frame rejection categories (`server/app/cloud/service.py`). The Pi now tags rejection reasons as `clock_skew`, `signature_mismatch`, or `bad_frame` so the cloud + mobile UI can distinguish a drifting RTC-less Pi from a real signature mismatch (P2-10 / E-2).

### Unchanged

- HMAC signing protocol, nonce-cache shape, bearer-token scheme, MQTT auth, OTA password gate — all stable since v3.3.1.

## [3.3.3] - 2026-04-19

Pi-side hardening for command-signing freshness + replay protection.

### Added

- Persistent replay-nonce cache — survives Pi reboots so a Pi that restarts mid-attack can't accept a previously-seen command id within its 30s HMAC window.
- `scripts/setup-pi.sh` now installs and configures `chrony` so the Pi's clock stays within ±30 s of the cloud. Prior: a Pi whose clock drifted (common after long power outages on an RTC-less unit) would silently reject signed commands as stale.

### Fixed

- Clock-drift rejections now log with enough detail for operators to tell "bad signature" apart from "your clock is wrong."

## [3.3.2] - 2026-04-18

Cloud-parity release following a second-pass audit. Pi-side hardening in v3.3.0/v3.3.1 was airtight; this release extends the same discipline to the rest of the system and closes the remaining audit items.

### Security

- **Nonce cache is now a real FIFO (P6).** `server/app/cloud/service.py::_seen_command_ids` switched from `set` with arbitrary `pop()` to `OrderedDict` with `popitem(last=False)`. A burst of >1024 distinct ids no longer lets an earlier id be replayed inside the 30s HMAC window.

### Fixed

- **Pi-local alerters forward to cloud push (P2).** `engine._check_safety_thresholds`, `vision.analyze_frame_claude`, and `main._node_liveness_sweeper` now call `forward_event(...)` alongside their local ntfy notification. Premium mobile subscribers actually receive push alerts when thresholds breach or a node goes offline. Prior: local ntfy fired, cloud push never did.
- **Safety watchdog survives Pi restart (P10).** A new `safety_watchdogs` SQLite table records each armed `safety_max_on_seconds` auto-off. On boot, `rehydrate_safety_watchdogs` re-arms watchdogs whose `expires_at` is in the future and publishes OFF immediately for any whose expiry elapsed while the Pi was down. Prior: a reboot with a heater ON left the actuator stuck ON with no watchdog.
- **`push_log.read` vs `is_read` inconsistency resolved (Q10).** The cloud layer standardized on `is_read` (matches CLAUDE.md); migration renames the column if an older deployment had `read`.

### Changed

- **Pi router raw-SQL refactor (P12).** `automation/router.py`, `vision/router.py`, `hardware/router.py` now delegate all DB access to service-layer helpers. New `hardware/service.py`; expanded `automation/service.py` and `vision/service.py`. Router files drop to ~100 LOC each. Closes 3 of the PV1-PV3 layering violations.
- **`manual_overrides` + `safety_watchdogs` share a transaction on override set.** Prior version held two separate connections concurrently and deadlocked under SQLite's single-writer contract; the watchdog cancel + DB delete now happen inline so the override + watchdog records stay coherent.

### Added

- `server/app/automation/service.py` — new CRUD helpers (`list_rules_with_created_at`, `get_rule`, `create_rule`, `update_rule`, `delete_rule`, `toggle_rule`, `list_firings`) extracted from the router.
- `server/app/hardware/service.py` — new module with `list_nodes`, `get_node`, `send_command` + the regex validators.
- `server/app/vision/service.py` — `get_active_session_id`, `insert_frame`, `update_analysis_local`, `update_analysis_claude`, `get_frame_by_id`, `apply_user_label`.
- `safety_watchdogs` SQLite table for persistent watchdog state.
- `server/tests/fixtures/signing_vectors.json` — shared golden-file fixture with the cloud side. Drift trips tests on whichever runtime moved.
- `server/tests/test_signing_golden.py` — asserts the Pi's `_canonical` + `verify_frame` match the fixture byte-for-byte.

### Migration

- **Apply database changes by restarting the server** — `init_db` creates `safety_watchdogs` automatically.
- **No breaking protocol changes** — v3.3.1 and v3.3.2 Pis interoperate with a v3.3.1 cloud; the command contract is unchanged.

## [3.3.1] - 2026-04-17

Incremental security release — closes S3 (cloud command signing) end-to-end.

> ### ⚠️ BREAKING CHANGE — v3.3.1 Pi requires a v3.3.1 cloud relay
>
> **The Pi now refuses unsigned command frames.** Consequences:
>
> - **v3.3.1 Pi ←→ v3.3.0 cloud**: every mobile-app command is rejected with `Signature check failed: missing signature`. Remote control is fully broken until both sides are upgraded.
> - **v3.3.0 Pi ←→ v3.3.1 cloud**: commands still execute (old Pi ignores the new signature field) but nothing is protected — the cryptographic guarantee only holds when both ends verify.
>
> Deploy both sides together. The HMAC key is the already-provisioned `device_token` from pairing — no new operator secret.

### Security

- **Cloud command frames are now HMAC-SHA256 signed (S3 full closure).** Every `command` frame forwarded by the cloud relay carries a `signature` field covering the canonical JSON form of the frame and a `ts` (epoch seconds). `cloud/service.on_command` verifies signature + replay window (`±30s`) BEFORE checking tier, command id, target, or channel. A compromised cloud relay, a third party with socket access, or anyone who has re-authed their device socket cannot forge commands without the Pi's `cloud_token`. Replaces the v3.3.0 defense-in-depth pattern (tier string + id LRU + target allowlist) as primary — those remain as second-line guards.

  New file: `server/app/cloud/signing.py` mirrors the cloud-side signer byte-for-byte.

  Regression coverage: `server/tests/test_cloud_signing.py` — tamper, wrong key, missing/stale/future `ts`, empty key, key-order stability.

### Migration

- **Both sides must be upgraded together.** An old Pi paired to a new cloud will refuse all commands (old Pi doesn't verify; new cloud sends signed frames that old Pi doesn't know about — but the Pi side gate is new, so "old" means pre-v3.3.1). A new Pi paired to an old cloud will refuse all commands (no signature present). There is no opt-out flag — this is the contract.
- **No operator action required beyond pulling both repos.** The shared secret (`device_token` / `cloud_token`) is already in place from pairing; nothing new to provision.

## [3.3.0] - 2026-04-17

Security + stability release closing every critical finding from an external code audit. **Upgrading is strongly recommended for any Pi running unattended.**

### Security

- **MQTT broker is no-anonymous by default.** `config/mosquitto/mosquitto.conf` now sets `allow_anonymous false`, a `password_file`, and a per-role `acl.conf`. `setup.sh` provisions the `server` credential on first run (random 40-char). Firmware nodes read their credentials from NVS via `MqttManager._connect` (`mqtt_user` / `mqtt_pass`). The broker is bound to `127.0.0.1` in `docker-compose.yml`; never expose port 1883 to the internet. Prior to this release, any device on the LAN could publish `sporeprint/relay-01/cmd/heater {state:"on",pwm:255}` directly to the broker and the relay would obey.

- **`/api/cloud/configure` requires a short-lived `configure_token`.** `/pair` now validates the 6-digit code (with an 8-attempt / 10-minute lockout) and issues a `configure_token` in the response. `/configure` rejects any request without a matching token, rejects values containing `\n` / `\r` / `=` (newline-injection defense), resolves the `.env` path from the package root (not process CWD, which `/` under systemd), and writes atomically via `tempfile + os.replace` with `chmod 600`. Prior: unauthenticated LAN POST could rewrite `.env` and plant arbitrary env vars on next restart.

- **Backend bearer-token auth (opt-in).** New `app/auth.py` `ApiKeyMiddleware` gates every `/api/*` route plus the Socket.IO `connect` handshake when `SPOREPRINT_API_KEY` is set. Whitelist: `/api/health`, `/api/cloud/pair`, `/api/cloud/pairing-code`. `setup.sh` generates a key on first run so fresh installs are authed by default. Closes free-Claude-billing exhaustion, API-key exfil-by-substitution on the settings router, and ntfy-topic hijack.

- **Vision upload path traversal closed.** `POST /api/vision/frame` validates `X-Node-Id` against `^[a-zA-Z0-9_-]{1,32}$` and asserts the resolved write path stays inside `vision_storage`. Prior: a header value of `../../etc/passwd_image` would attempt to break out of the storage dir.

- **Hardware command topic lockdown.** `POST /api/hardware/nodes/{id}/command` drops any caller-supplied `topic` field and constructs the topic server-side from the URL path. Channel must match the safe-charset regex.

- **Cloud command channel HMAC-signed (S3 — full closure in v3.3.1).** v3.3.0 hardened this with defense-in-depth (id-replay LRU, target regex, registered-target check). v3.3.1 closes the remaining gap: every command frame forwarded by the cloud relay is now HMAC-SHA256 signed over a canonical JSON form of the payload using the Pi's `cloud_token` as the key. `cloud/service.on_command` verifies the signature and a `ts` timestamp (30-second replay window) BEFORE any other check — a compromised relay or a third party with socket access cannot forge commands without the shared secret. The signing helper (`server/app/cloud/signing.py`) mirrors the cloud-side implementation byte-for-byte.

- **OTA password enforcement.** `OTAManager::begin` refuses to call `ArduinoOTA.begin()` when `ota_pass` is unset or equals the legacy default `"sporeprint"`. Nodes log a warning until the operator sets a strong password via the captive portal.

- **python-multipart bumped to `>=0.0.18`** to close CVE-2024-24762 (permitted by the previous `>=0.0.6` floor).

### Fixed

- **`safety_max_on_seconds` is now actually enforced (R15 / P14).** Previously the field existed on `AutomationRule` and was used by built-in templates, but nothing in the codebase ever turned an actuator off based on it. Now `_fire_rule` schedules a cancellable `asyncio.Task` (`_safety_auto_off`) whenever it successfully publishes `state='on'` with a non-zero `safety_max_on_seconds`. The task publishes `state='off'` after the declared delay and writes an `automation_firings` row with `rule_name='safety_max_on_seconds:<original>'` so the timeout is visible in the audit log. Pending watchdogs are cancelled when a subsequent rule publishes `state='off'` for the same `target:channel`, or when an operator sets a manual override (operator owns timing while the override is in place). New regression suite `test_safety_max_on.py` covers all four behaviours. Fire-risk closure.

- **Dead `server/app/websocket/` package removed (P11 / V19 / D1).** `register_events` and `broadcast_telemetry` had no callers — Socket.IO handlers and emits are centralised in `main.py` and the various service modules. The module was a trap for new contributors looking for "where do sockets get wired up." Gone.

- **Firmware uptime timestamps no longer corrupt history (DATA-1).** `mqtt._handle_message` treats any `ts < 2020-01-01` as firmware uptime-seconds (the `millis()/1000` written by the offline-buffer drain) and replaces it with the server's receive time. A counter (`uptime_ts_clamps`) surfaces on `/api/health/detail/system` so operators can see when it triggers. Prior: every WiFi reconnect on any node inserted 1970-epoch rows into `telemetry_readings`.

- **Automation audit log no longer lies during MQTT outages (SAFETY-2).** `_fire_rule` now inserts `automation_firings` with `status='pending'`, attempts `mqtt_publish` (which returns a bool), and only then updates the row to `status='sent'` (publish succeeded) or `status='failed'` with the error captured. Prior ordering was publish-first, log-second: during the 5-second MQTT reconnect window, the publish silently dropped but the audit row still recorded a successful fire.

- **Manual overrides survive reboots (SAFETY-1).** `manual_overrides` DB table is now the source of truth for `engine._overrides`. `set_override` / `clear_override` / `get_overrides` read-through and write-through; `ensure_overrides_loaded` hydrates the in-memory cache on first use and prunes expired rows. Prior: operator safety locks were RAM-only and silently evaporated on every Pi reboot.

- **MQTT consumer no longer dies silently (RELIABILITY-1).** `_handle_message` is wrapped in `try/except Exception` with `log.exception`. `start_mqtt` body is wrapped in a `while True` supervisor with a 5-second backoff and a restart counter exposed in the reliability metrics. Prior: a single malformed payload killed the subscriber until manual restart with no operator signal.

- **Critical alerters actually fire (OBS-1).** `temperature_alert` and `co2_alert` are now called from `engine._check_safety_thresholds` when readings breach phase ceilings by a safety margin (`temp_max_f + 5°F` / `co2_max_ppm + 1000ppm`). `contamination_alert` fires from `vision.analyze_frame_claude` when Claude reports `contamination_detected`. A new 60-second `_node_liveness_sweeper` in the lifespan task flips stale `hardware_nodes.status` to `offline` and calls `node_offline` once per outage (900s `last_seen` threshold). Prior: all of these alerters were defined but never called from anywhere in the codebase.

- **Retention rollup can't lose raw rows (DATA-3).** `_rollup_telemetry_5min / hourly`, `_rollup_weather_hourly`, and `_cleanup_old_rollups` now use `INSERT ... ON CONFLICT DO UPDATE` with weighted-mean merging (`(old_avg * old_count + new_avg * new_count) / total_count`; `MIN` / `MAX` kept monotonic; counts summed). Each rollup runs inside an explicit `BEGIN` / `COMMIT` / `ROLLBACK` block. Prior `INSERT OR IGNORE` + `DELETE` would delete raw rows that never made it into the aggregate when a retried run hit a pre-existing rollup row.

- **Cloud queue actually drops the oldest message on overflow (DATA-2).** `forward_telemetry` now `get_nowait()`s the stalest item, `put_nowait`s the new one, and increments `_queue_drops`. Count exposed via `get_cloud_status()`. Prior `except QueueFull: pass` silently discarded the newest payload without logging.

### Changed

- **`AsyncAnthropic` everywhere.** `vision`, `transcript`, `builder`, `contamination`, and `experiments` services use `anthropic.AsyncAnthropic(...)` with `await client.messages.create(...)`. Inline `import anthropic` hoisted to module top per AGENTS.md. Prior sync SDK froze the event loop for 3-15 seconds per Claude call, halting MQTT, telemetry, and Socket.IO during the freeze.

- **SQLite tuned for production.** `init_db` applies `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`. `get_db` re-applies connection-scoped pragmas on every acquisition. Referential integrity is now actually enforced — REFERENCES clauses were previously decorative.

- **`automation_firings` schema migration.** Added `status TEXT NOT NULL DEFAULT 'sent'` + `error TEXT` via `_add_column_if_missing`. New index on `status`. Historical rows remain readable as `status='sent'`.

- **`Settings.mqtt_username` / `mqtt_password` / `api_key`** — three new config fields. `.env.example` and `docker-compose.yml` plumbed accordingly.

- **`mqtt_publish` returns `bool`.** True when the publish landed, False when `_client is None` or the underlying publish raised. Callers can now tell success from silent drop.

- **Socket.IO `cors_allowed_origins="*"` is now explicitly justified in a comment** — the connect-handler auth check (`app.auth.socketio_auth_ok`) is the confidentiality gate. With `SPOREPRINT_API_KEY` unset, LAN attackers can still read telemetry via WS. Set the key to close that surface.

### Added

- `server/app/auth.py` — `ApiKeyMiddleware` + `socketio_auth_ok` bearer-token gate.
- `config/mosquitto/acl.conf` — per-role broker ACL (server has full authority; nodes restricted to their own namespace + `cmd/` read).
- `config/mosquitto/passwd.example` — placeholder with regen instructions.
- Reliability counters on `/api/health/detail/system.reliability`: `uptime_ts_clamps`, `mqtt_supervisor_restarts`.
- `server/tests/test_mqtt.py` — regression for the uptime-ts clamp.
- `server/tests/test_automation_fire.py` — regression for the rule-fire ordering (verifies `status='failed'` when the broker is down during publish).
- `test_override_persists_across_reload` — verifies overrides survive a simulated process restart.
- `_node_liveness_sweeper()` lifespan task (60s interval, 900s staleness threshold).

### Migration notes

- **Run `./setup.sh` after pulling.** It generates `SPOREPRINT_API_KEY` and the Mosquitto `server` credential in `.env` if they're blank. Nothing is overwritten.
- **Add MQTT creds to every firmware node before flashing v3.3.0.** Set `mqtt_user` / `mqtt_pass` in NVS (captive portal on first boot of a wiped device, or push via `ConfigStore`). Nodes without creds will fail to connect to the newly-authed broker.
- **Set a real OTA password on every node before it starts enforcing in v3.3.0 firmware.** Nodes running default `"sporeprint"` will refuse to call `ArduinoOTA.begin()` — they stay functional but cannot receive OTA updates until the operator sets a strong password.
- **Existing `manual_overrides` rows are now honored.** If you had rows in the table from a prior debug session, they will be loaded on next start. Clear any stale ones before upgrading if you don't want them applied.
