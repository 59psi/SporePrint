from pydantic import BaseModel


class Component(BaseModel):
    name: str
    role: str
    quantity: int = 1
    price_approx: str
    url: str
    category: str  # "controller" | "sensor" | "actuator" | "power" | "plug" | "misc"
    notes: str = ""


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
