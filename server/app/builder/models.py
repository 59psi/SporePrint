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
    # multi-packs, cable and charger packs): `quantity` counts the UNITS this
    # tier needs per chamber, price_approx is the per-unit price within the
    # pack, pack_price is the price of the pinned pack and pack_size the units
    # in it. A line then costs ceil(units / pack_size) packs, so packs are
    # shared across chambers (one 100-pack of resistors covers 12 chambers).
    # pack_price "" = bought singly. Additive API fields.
    pack_price: str = ""
    # Units in one pinned pack; 0 = sold singly. A legacy line with
    # pack_price but no pack_size keeps the old rule: one pack covers the
    # line (one pack per chamber).
    pack_size: int = 0
    # One per installation rather than per chamber: the Pi side (Pi, its PSU,
    # cooler, microSD) and multi-use packs/spools (wire, connectors, inserts,
    # screws, consumables). The Builder's "chambers to build" multiplier
    # leaves these at their own quantity. Additive API field.
    shared: bool = False

    def units(self, chambers: int = 1) -> int:
        """Units to buy for ``chambers`` chambers (a shared line once)."""
        if chambers < 1:
            raise ValueError(f"chambers must be >= 1, got {chambers}")
        return self.quantity if self.shared else self.quantity * chambers

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
