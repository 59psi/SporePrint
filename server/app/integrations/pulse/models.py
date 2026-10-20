"""Pydantic models for the Pulse Grow cloud API.

Pulse's v2 cloud API returns measurements with stable type names —
``temperature``, ``humidity``, ``vpd``, ``dew_point``, ``light``. We
declare what we use and accept extras so a future field addition does
not crash the poller. A device or measurement that does not validate is
dropped on its own, so it cannot fail the whole poll; a null value is kept
as None and not stored; numeric ids are read as strings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .._samples import valid_items


class PulseLoginResponse(BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    token: str | None = None
    # Some Pulse API revisions wrap the token in a `data` envelope.
    @classmethod
    def from_payload(cls, raw: Any) -> "PulseLoginResponse":
        if isinstance(raw, dict):
            if "token" in raw:
                return cls.model_validate(raw)
            if isinstance(raw.get("data"), dict) and "token" in raw["data"]:
                return cls.model_validate(raw["data"])
        return cls(token=None)


class PulseDevice(BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    id: str
    name: str | None = None
    type: str | None = None


class PulseDeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    devices: list[PulseDevice] = []

    @field_validator("devices", mode="before")
    @classmethod
    def _drop_invalid_devices(cls, value: Any) -> list[BaseModel]:
        return valid_items(PulseDevice, value)

    @classmethod
    def from_payload(cls, raw: Any) -> "PulseDeviceListResponse":
        if isinstance(raw, list):
            return cls(devices=raw)
        if isinstance(raw, dict):
            if "devices" in raw:
                return cls.model_validate(raw)
            if isinstance(raw.get("data"), list):
                return cls(devices=raw["data"])
        return cls(devices=[])


class PulseMeasurement(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    value: float | None = None
    unit: str | None = None
    timestamp: str | float | None = None


class PulseRecentDataResponse(BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    device_id: str | None = None
    measurements: list[PulseMeasurement] = []

    @field_validator("measurements", mode="before")
    @classmethod
    def _drop_invalid_measurements(cls, value: Any) -> list[BaseModel]:
        return valid_items(PulseMeasurement, value)

    @classmethod
    def from_payload(
        cls, raw: Any, device_id: str
    ) -> "PulseRecentDataResponse":
        if isinstance(raw, dict):
            body = raw
            if "measurements" not in body and isinstance(raw.get("data"), dict):
                body = raw["data"]
            if "measurements" in body:
                return cls.model_validate({**body, "device_id": device_id})
        return cls(device_id=device_id, measurements=[])
