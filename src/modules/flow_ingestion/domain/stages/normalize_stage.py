"""Frame normalization stage parsing and standardizing incoming telemetry dictionaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import (
    MalformedPayloadError,
    RateLimitExceededError,
)
from ..models import PipelineContext, TelemetryRecord
from .base import PipelineStage

_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "plant_id",
        "regulator_id",
        "sensor_id",
        "sequence_number",
        "timestamp_ns",
        "flow_rate_sccm",
        "pressure_bar",
        "temperature_celsius",
        "status_flags",
    }
)


class FrameNormalizationStage(PipelineStage):
    """Parses raw payload frames and normalizes them into immutable domain records."""

    @property
    def stage_name(self) -> str:
        """Returns the stage identifier."""
        return "frame_normalization"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Validates raw payload frames and normalizes them into domain records.

        Args:
            context: Incoming PipelineContext containing raw_payload.

        Returns:
            Updated PipelineContext populated with normalized TelemetryRecord objects.

        Raises:
            MalformedPayloadError: If frame schema or types are invalid.
            RateLimitExceededError: If physical parameters violate boundary limits.
        """
        payload = context.raw_payload
        if not isinstance(payload, Mapping) or not payload:
            raise MalformedPayloadError(
                "Payload must be a non-empty mapping",
                code="MALFORMED_PAYLOAD",
                status_code=400,
            )

        raw_frames: list[Mapping[str, Any]] = []

        if "frame" in payload:
            if not isinstance(payload["frame"], Mapping):
                raise MalformedPayloadError(
                    "Field 'frame' must be an object",
                    code="MALFORMED_PAYLOAD",
                    status_code=400,
                )
            raw_frames.append(payload["frame"])
        elif "frames" in payload:
            if not isinstance(payload["frames"], list):
                raise MalformedPayloadError(
                    "Field 'frames' must be a list",
                    code="MALFORMED_PAYLOAD",
                    status_code=400,
                )
            if not payload["frames"]:
                raise MalformedPayloadError(
                    "Field 'frames' must not be empty",
                    code="MALFORMED_PAYLOAD",
                    status_code=400,
                )
            for item in payload["frames"]:
                if not isinstance(item, Mapping):
                    raise MalformedPayloadError(
                        "Each frame in 'frames' must be an object",
                        code="MALFORMED_PAYLOAD",
                        status_code=400,
                    )
                raw_frames.append(item)
        else:
            raise MalformedPayloadError(
                "Payload must contain either 'frame' or 'frames'",
                code="MALFORMED_PAYLOAD",
                status_code=400,
            )

        normalized_records: list[TelemetryRecord] = []
        for raw in raw_frames:
            record = self._parse_record(raw)
            normalized_records.append(record)

        return context.with_records(tuple(normalized_records))

    def _parse_record(self, raw: Mapping[str, Any]) -> TelemetryRecord:
        """Validates and converts a single raw dictionary to TelemetryRecord."""
        missing = _REQUIRED_FIELDS - set(raw.keys())
        if missing:
            raise MalformedPayloadError(
                f"Missing required frame fields: {sorted(missing)}",
                code="MALFORMED_PAYLOAD",
                status_code=400,
                details={"missing": sorted(missing)},
            )

        try:
            plant_id = str(raw["plant_id"])
            regulator_id = str(raw["regulator_id"])
            sensor_id = str(raw["sensor_id"])

            if not isinstance(raw["sequence_number"], int) or isinstance(
                raw["sequence_number"], bool
            ):
                raise TypeError("sequence_number must be an integer")
            sequence_number = int(raw["sequence_number"])

            if not isinstance(raw["timestamp_ns"], int) or isinstance(
                raw["timestamp_ns"], bool
            ):
                raise TypeError("timestamp_ns must be an integer")
            timestamp_ns = int(raw["timestamp_ns"])

            if not isinstance(raw["flow_rate_sccm"], (int, float)) or isinstance(
                raw["flow_rate_sccm"], bool
            ):
                raise TypeError("flow_rate_sccm must be numeric")
            flow_rate_sccm = float(raw["flow_rate_sccm"])

            if not isinstance(raw["pressure_bar"], (int, float)) or isinstance(
                raw["pressure_bar"], bool
            ):
                raise TypeError("pressure_bar must be numeric")
            pressure_bar = float(raw["pressure_bar"])

            if not isinstance(raw["temperature_celsius"], (int, float)) or isinstance(
                raw["temperature_celsius"], bool
            ):
                raise TypeError("temperature_celsius must be numeric")
            temperature_celsius = float(raw["temperature_celsius"])

            if not isinstance(raw["status_flags"], int) or isinstance(
                raw["status_flags"], bool
            ):
                raise TypeError("status_flags must be an integer")
            status_flags = int(raw["status_flags"])

            # Domain physical boundary validation: flow rate and pressure cannot be negative
            if flow_rate_sccm < 0 or pressure_bar < 0:
                raise RateLimitExceededError(
                    f"Physical range violation: flow_rate={flow_rate_sccm}, pressure={pressure_bar}",
                    code="RATE_LIMIT_EXCEEDED",
                    status_code=422,
                    details={
                        "flow_rate_sccm": flow_rate_sccm,
                        "pressure_bar": pressure_bar,
                    },
                )

            return TelemetryRecord(
                plant_id=plant_id,
                regulator_id=regulator_id,
                sensor_id=sensor_id,
                sequence_number=sequence_number,
                timestamp_ns=timestamp_ns,
                flow_rate_sccm=flow_rate_sccm,
                pressure_bar=pressure_bar,
                temperature_celsius=temperature_celsius,
                status_flags=status_flags,
            )
        except RateLimitExceededError:
            raise
        except (ValueError, TypeError) as err:
            raise MalformedPayloadError(
                f"Invalid frame data types: {err}",
                code="MALFORMED_PAYLOAD",
                status_code=400,
            ) from err
