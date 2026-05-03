"""Pydantic models for the Aranet PRO API response.

Tolerant by design — PRO firmware versions vary in field names and
shapes, and the integration must not crash a poll because of an
unfamiliar measurement type. We declare the fields we actually use and
accept the rest under ``model_config["extra"] = "allow"`` so they round-
trip without error.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AranetMeasurement(BaseModel):
    """One reading from one sensor.

    `type` values seen in the wild: ``temperature``, ``humidity``,
    ``co2``, ``atmospheric_pressure``, ``radiation_dose_rate``,
    ``soil_moisture``, ``soil_ec``, ``soil_temperature``. We only map
    the first three into the SporePrint telemetry pipeline by default;
    the rest are surfaced through the discovery endpoint so the operator
    can confirm they're being read.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    value: float
    unit: str | None = None
    timestamp: str | float | None = None


class AranetSensor(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    type: str | None = None
    measurements: list[AranetMeasurement] = []


class AranetMeasurementsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sensors: list[AranetSensor] = []

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> "AranetMeasurementsResponse":
        # Some PRO firmware versions return ``data: {sensors: [...]}``
        # instead of ``sensors`` at the root. Normalise both shapes.
        if "sensors" in raw:
            return cls.model_validate(raw)
        if isinstance(raw.get("data"), dict) and "sensors" in raw["data"]:
            return cls.model_validate(raw["data"])
        # If neither shape matches, accept an empty response — better
        # than crashing a poll over a payload format the operator can't
        # easily debug from the Pi.
        return cls(sensors=[])
