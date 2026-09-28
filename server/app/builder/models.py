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
    # Price of the smallest pack you can actually buy, for parts that are
    # only sold in packs (resistors, diodes, MOSFETs, dev-board multi-packs).
    # price_approx stays the per-unit price; when pack_price is set, one pack
    # covers `quantity` and the tier cost counts pack_price once instead of
    # price_approx x quantity. Empty = bought singly. Additive API field.
    pack_price: str = ""

    def line_cost(self) -> float:
        """What this BOM line really costs to buy, in dollars."""
        if self.pack_price:
            return usd(self.pack_price)
        return usd(self.price_approx) * self.quantity


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

    def parts_cost(self) -> float:
        """Sum of every line's real cost (pack-only parts counted once).

        estimated_cost is a rounded, human-written string; tests hold it
        within 10% of this figure so the two cannot drift apart again.
        """
        return sum(c.line_cost() for c in self.components)
