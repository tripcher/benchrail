import re

from pydantic import BaseModel, field_validator, model_validator


class AgentEntry(BaseModel):
    id: str
    agent: str
    version: str = ""
    command: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v:
            raise ValueError("Agent id must not be empty")
        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError(f"Agent id {v!r} is not filesystem-safe")
        return v


class Manifest(BaseModel):
    agents: list[AgentEntry]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "Manifest":
        seen: set[str] = set()
        for entry in self.agents:
            if entry.id in seen:
                raise ValueError(f"Duplicate agent id: {entry.id!r}")
            seen.add(entry.id)
        if not self.agents:
            raise ValueError("agents[] must not be empty")
        return self
