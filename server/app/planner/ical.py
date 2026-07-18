"""iCal projection of a species-derived proposed grow cycle.

Turns a ProposedCycle (from planner.service.propose_cycle) into an RFC-5545
calendar: one all-day VEVENT per dated phase plus a harvest marker. Sharing the
proposer means the projection is driven by the species' real phases instead of a
hardcoded phase order, and every event gets a deterministic, collision-free UID.
"""

from .models import ProposedCycle


def cycle_to_ical(cycle: ProposedCycle) -> str:
    """Render a proposed cycle as an iCal (text/calendar) feed."""
    from icalendar import Calendar, Event  # lazy — mirrors sessions.generate_ical

    cal = Calendar()
    cal.add("prodid", "-//SporePrint//Grow Cycle Proposal//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"SporePrint plan — {cycle.common_name}")

    slug = cycle.species_id
    start_iso = cycle.start_date.isoformat()

    for ph in cycle.phases:
        s = ph.setpoints
        ev = Event()
        ev.add("summary", f"{cycle.common_name} — {ph.label}")
        ev.add("dtstart", ph.start_date)
        ev.add("dtend", ph.end_date)
        ev.add(
            "description",
            f"{ph.label}: {ph.duration_days} days "
            f"({ph.min_days}-{ph.max_days} expected)\n"
            f"Temp {s.temp_min_f:.0f}-{s.temp_max_f:.0f}F, "
            f"RH {s.humidity_min:.0f}-{s.humidity_max:.0f}%, "
            f"CO2 <={s.co2_max_ppm}ppm, "
            f"light {s.light_hours_on:.0f}h {s.light_spectrum}, "
            f"FAE {s.fae_mode}",
        )
        # Stable per (species, inoculation date, phase) — safe to re-import.
        ev["uid"] = f"proposal-{slug}-{start_iso}-{ph.phase}@sporeprint"
        cal.add_component(ev)

    if cycle.harvest_date is not None:
        ev = Event()
        ev.add("summary", f"{cycle.common_name} — Expected Harvest")
        ev.add("dtstart", cycle.harvest_date)
        ev.add("dtend", cycle.harvest_date)
        ev["uid"] = f"proposal-{slug}-{start_iso}-harvest@sporeprint"
        cal.add_component(ev)

    return cal.to_ical().decode()
