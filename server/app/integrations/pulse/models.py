"""Pydantic models for the Pulse Grow cloud API.

Pulse's v2 cloud API returns measurements with stable type names —
``temperature``, ``humidity``, ``vpd``, ``dew_point``, ``light``. We
declare what we use and accept extras so a future field addition does
not crash the poller.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PulseLoginResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    token: str | None = None
    # Some Pulse API revisions wrap the token in a `data` envelope.
    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> "PulseLoginResponse":
        if "token" in raw:
            return cls.model_validate(raw)
        if isinstance(raw.get("data"), dict) and "token" in raw["data"]:
            return cls.model_validate(raw["data"])
        return cls(token=None)


class PulseDevice(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    type: str | None = None


class PulseDeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    devices: list[PulseDevice] = []

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> "PulseDeviceListResponse":
        if "devices" in raw:
            return cls.model_validate(raw)
        if isinstance(raw, list):
            return cls(devices=[PulseDevice.model_validate(d) for d in raw])
        if isinstance(raw.get("data"), list):
            return cls(
                devices=[PulseDevice.model_validate(d) for d in raw["data"]]
            )
        return cls(devices=[])


class PulseMeasurement(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    value: float
    unit: str | None = None
    timestamp: str | float | None = None


class PulseRecentDataResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    device_id: str | None = None
    measurements: list[PulseMeasurement] = []

    @classmethod
    def from_payload(
        cls, raw: dict[str, Any], device_id: str
    ) -> "PulseRecentDataResponse":
        if "measurements" in raw:
            obj = cls.model_validate(raw)
            obj.device_id = device_id
            return obj
        if isinstance(raw.get("data"), dict) and "measurements" in raw["data"]:
            obj = cls.model_validate(raw["data"])
            obj.device_id = device_id
            return obj
        return cls(device_id=device_id, measurements=[])
