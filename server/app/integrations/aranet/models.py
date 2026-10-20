"""Pydantic models for the Aranet PRO API response.

Tolerant by design — PRO firmware versions vary in field names and
shapes, and the integration must not crash a poll because of an
unfamiliar measurement type. We declare the fields we actually use and
accept the rest under ``model_config["extra"] = "allow"`` so they round-
trip without error. A sensor or measurement that does not validate (a
missing type, a value that is not a number) is dropped on its own, so it
cannot take its siblings down with it; a null value (a sensor with no
reading yet) is kept as None and simply not stored. Numeric ids are read
as strings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .._samples import valid_items


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
    value: float | None = None
    unit: str | None = None
    timestamp: str | float | None = None


class AranetSensor(BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    id: str
    name: str | None = None
    type: str | None = None
    measurements: list[AranetMeasurement] = []

    @field_validator("measurements", mode="before")
    @classmethod
    def _drop_invalid_measurements(cls, value: Any) -> list[BaseModel]:
        return valid_items(AranetMeasurement, value)


class AranetMeasurementsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sensors: list[AranetSensor] = []

    @field_validator("sensors", mode="before")
    @classmethod
    def _drop_invalid_sensors(cls, value: Any) -> list[BaseModel]:
        return valid_items(AranetSensor, value)

    @classmethod
    def from_payload(cls, raw: Any) -> "AranetMeasurementsResponse":
        # Some PRO firmware versions return ``data: {sensors: [...]}``
        # instead of ``sensors`` at the root. Normalise both shapes.
        if isinstance(raw, dict):
            if "sensors" in raw:
                return cls.model_validate(raw)
            if isinstance(raw.get("data"), dict) and "sensors" in raw["data"]:
                return cls.model_validate(raw["data"])
        # If neither shape matches, accept an empty response — better
        # than crashing a poll over a payload format the operator can't
        # easily debug from the Pi.
        return cls(sensors=[])
