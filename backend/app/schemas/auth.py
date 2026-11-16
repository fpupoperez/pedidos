"""Caller identity carried on every JSON envelope."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class SessionAuth(BaseModel):
    """The caller session. Empty when authentication is not required."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, title="SessionAuth")

    tenant_id: str | None = Field(
        default=None,
        alias="tenantId",
        description="Tenant of the caller. Omitted when AUTH_REQUIRED is false.",
        examples=["orders"],
    )

    @model_serializer(mode="wrap")
    def _omit_empty(self, handler: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        """Drop an unset tenant so the wire value is {} rather than a null field."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}
