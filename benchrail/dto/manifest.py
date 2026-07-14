import re

from benchrail.pydantic_compat import BaseModel, field_validator, model_validator


class AgentEntry(BaseModel):
    id: str
    agent: str
    version: str = ""
    command: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v:
            msg = "Agent id must not be empty"
            raise ValueError(msg)
        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            msg = f"Agent id {v!r} is not filesystem-safe"
            raise ValueError(msg)
        return v


class Manifest(BaseModel):
    agents: list[AgentEntry]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "Manifest":
        seen: set[str] = set()
        for entry in self.agents:
            if entry.id in seen:
                msg = f"Duplicate agent id: {entry.id!r}"
                raise ValueError(msg)
            seen.add(entry.id)
        if not self.agents:
            msg = "agents[] must not be empty"
            raise ValueError(msg)
        return self
