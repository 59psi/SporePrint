"""Grow lifecycle: container types, the colonization fork, and CO2 physicality.

The product owner's spec: a grower inoculates *something* — agar, grow bag,
liquid culture, grain jar — and colonizes it. Then it forks:

    "For anything other than a grow bag, once fully colonized they are typically
     removed and placed in COLD STORAGE. A grow bag however would then move onto
     the fruiting stage: first pinning, then the flush."

So the container type decides the post-colonization phase. It also decides
whether CO2 control is even physically meaningful, because the CO2 sensor lives
in the CHAMBER, not inside the substrate container:

  - A sealed bag / jar during colonization holds its CO2 INSIDE. The chamber
    sensor reads room air; running FAE cannot change the bag's internal CO2 —
    it just dries the chamber. CO2 setpoints there are meaningless.
  - A monotub / open tray puts the substrate in the sensed volume, so the CO2
    reading is real and FAE genuinely acts on the mycelium.
  - A grow bag becomes "open" once it is cut for fruiting.
"""

# Culture / spawn vessels: sealed containers that DO NOT fruit in the chamber.
# Fully colonized, they go to the fridge (cold storage), not to pinning.
STORAGE_CONTAINERS = frozenset({"agar_plate", "liquid_culture", "grain_jar"})

# Bulk-substrate containers that FRUIT IN PLACE. A grow bag is sealed during
# colonization and cut open for fruiting; a monotub / tray is open throughout.
FRUITING_CONTAINERS = frozenset({"grow_bag", "monotub", "tray", "bulk_bag"})

# Colonization phases — the ones the fork happens *after*.
COLONIZATION_PHASES = frozenset(
    {"agar", "liquid_culture", "grain_colonization", "substrate_colonization"}
)

# Fruiting-side phases where a grow bag has been opened (substrate exposed to
# the sensed chamber air).
_OPEN_PHASES = frozenset({"primordia_induction", "fruiting", "rest"})


def co2_control_meaningful(container_type: str | None, phase: str) -> bool:
    """Is the chamber CO2 reading physically coupled to the substrate?

    Returns False when the substrate is sealed away from the sensor, so CO2
    rules would only churn the chamber without touching the mycelium.

    Unknown / None container defaults to True: legacy sessions predate this
    field and we must not silently disable their CO2 control. The wizard sets
    the field for new sessions.
    """
    if container_type in STORAGE_CONTAINERS:
        return False  # agar / LC / grain jar: always a sealed vessel
    if container_type == "grow_bag":
        # Sealed during colonization; cut open for fruiting.
        return phase in _OPEN_PHASES
    # monotub / tray / bulk_bag / unknown → substrate is in the sensed volume.
    return True


def is_grow_bag(container_type: str | None) -> bool:
    return container_type == "grow_bag"


def next_phase(current_phase: str, container_type: str | None) -> str:
    """The spec's phase fork, as a pure function.

    Colonization forks on the container: culture/spawn vessels → COLD_STORAGE,
    everything that fruits in place → PRIMORDIA_INDUCTION. After that the path is
    linear except for the flush cycle (fruiting ⇄ rest), which the harvest path
    drives with the species' expected flush count.
    """
    if current_phase in COLONIZATION_PHASES:
        if container_type in STORAGE_CONTAINERS:
            return "cold_storage"
        # grow bag, monotub, tray, or unknown → head for fruiting.
        return "primordia_induction"
    if current_phase == "primordia_induction":
        return "fruiting"
    if current_phase == "fruiting":
        return "rest"  # between-flush rest period
    if current_phase == "rest":
        return "fruiting"  # next flush
    if current_phase == "cold_storage":
        return "complete"
    return "complete"
