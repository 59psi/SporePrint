import math
import re

from pydantic import BaseModel

_USD_RE = re.compile(r"^\$(\d[\d,]*(?:\.\d+)?)$")


def usd(price: str) -> float:
    """Parse a BOM price string such as ``"$1,234.56"`` to a float.

    Raises ValueError for anything else (``"~$10"``, ``"$10-12"``), so a
    malformed price_approx fails loudly instead of silently costing $0.
    """
    m = _USD_RE.match(price.strip())
    if not m:
        raise ValueError(f"not a plain dollar price: {price!r}")
    return float(m.group(1).replace(",", ""))


class Component(BaseModel):
    name: str
    role: str
    quantity: int = 1
    price_approx: str
    url: str
    category: str  # "controller" | "sensor" | "actuator" | "power" | "plug" | "misc"
    notes: str = ""
    # Pack-sold lines (resistors, diodes, MOSFETs, dev-board and camera
    # multi-packs, cable and charger packs, insert and screw kits, wire by
    # the foot): `quantity` counts the UNITS this tier needs per chamber,
    # price_approx is the per-unit price within the pack, pack_price is the
    # price of the pinned pack and pack_size the units in it. A line then
    # costs ceil(units / pack_size) packs, so packs are shared across
    # chambers (one 100-pack of resistors covers 12 chambers). A mixed kit
    # counts the size the chambers use up first (its notes say which).
    # pack_price "" = bought singly. Additive API fields.
    pack_price: str = ""
    # Units in one pinned pack; 0 = sold singly. A legacy line with
    # pack_price but no pack_size keeps the old rule: one pack covers the
    # line (one pack per chamber).
    pack_size: int = 0
    # One per installation rather than per chamber: the Pi side (Pi, its PSU,
    # cooler, microSD), bench tools, and a kit only the Pi case draws on. The
    # Builder's "chambers to build" multiplier leaves these at their own
    # quantity. Anything the chambers use up (inserts, screws, WAGO splices,
    # wire by the foot, zip ties, heat-shrink, grommets) is a per-chamber
    # pack line instead, so N chambers buy enough packs at any N — a bulk
    # pack that covers 16 chambers would under-buy for 17, and the Builder
    # takes up to 99. Additive API field.
    shared: bool = False
    # Units of a per-chamber pack line that the one-per-installation side
    # (the Pi case) takes from the SAME packs, bought once: N chambers need
    # quantity x N + shared_units units, i.e. ceil((quantity x N +
    # shared_units) / pack_size) packs. 0 = none. Only on a pack line that is
    # not shared. Additive API field.
    shared_units: int = 0
    # What quantity, shared_units and pack_size count when it is not whole
    # pieces of the named part: a measure ("ft" of wire, "g" of solder) or
    # one piece of a mixed kit ("strap", "chamber set", "M3 insert"). The
    # dashboard words the line with it — "420 ft · 5 packs of 100 ft · $0.26
    # / ft", not "×420 · 5 packs of 100 · $0.26 ea". "" = pieces of the part.
    # Only on a pack line. Additive API field.
    unit: str = ""

    def units(self, chambers: int = 1) -> int:
        """Units to buy for ``chambers`` chambers (a shared line once; a
        per-chamber line plus the Pi side's ``shared_units`` once)."""
        if chambers < 1:
            raise ValueError(f"chambers must be >= 1, got {chambers}")
        if self.shared:
            return self.quantity
        return self.quantity * chambers + self.shared_units

    def packs(self, chambers: int = 1) -> int:
        """Packs to buy for ``chambers`` chambers; 0 for a line bought singly."""
        units = self.units(chambers)
        if not self.pack_price:
            return 0
        if self.pack_size > 0:
            return math.ceil(units / self.pack_size)
        # Legacy pack line: one pack covers the line, once per chamber.
        return 1 if self.shared else chambers

    def line_cost(self, chambers: int = 1) -> float:
        """What this BOM line really costs to buy for ``chambers`` chambers, in
        dollars: whole packs for a pack-sold line, else unit price x units.
        The Builder's TS helpers (pi-ui lib/builder-data.ts) use this rule."""
        if self.pack_price:
            return usd(self.pack_price) * self.packs(chambers)
        return usd(self.price_approx) * self.units(chambers)


class WiringConnection(BaseModel):
    from_device: str
    from_pin: str
    to_device: str
    to_pin: str
    note: str = ""


class CapabilityGroup(BaseModel):
    """A grouped capability breakdown for a tier (Monitoring, Automation, etc.)."""
    title: str
    items: list[str]


class HardwareTier(BaseModel):
    id: str
    name: str
    tagline: str
    estimated_cost: str
    what_you_get: list[str]
    best_for: str = ""
    species_support: str = ""
    capability_groups: list[CapabilityGroup] = []
    limitations: list[str] = []
    components: list[Component]
    wiring: list[WiringConnection]
    wiring_diagram: str
    firmware_targets: list[str]
    setup_steps: list[str]

    def parts_cost(self, chambers: int = 1) -> float:
        """Sum of every line's real cost for ``chambers`` chambers (whole packs
        for pack-sold lines, shared lines once).

        estimated_cost is a rounded, human-written string; tests hold it
        within 10% of the one-chamber figure so the two cannot drift apart.
        """
        return sum(c.line_cost(chambers) for c in self.components)
