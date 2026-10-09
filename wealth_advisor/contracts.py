"""Interfaces shared by agents and replaceable tool implementations."""
from dataclasses import dataclass, field
from typing import Any, Protocol


class ToolError(ValueError):
    """Recoverable tool failure, independent of adapter implementation."""


class CRMTool(Protocol):
    def fetch(self, client_id: str) -> dict[str, Any]: ...


class AnalysisTool(Protocol):
    def analyze(self, client: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]: ...


class MemoryTool(Protocol):
    def recent(self, client_id: str) -> list[dict[str, Any]]: ...
    def save(self, result: dict[str, Any]) -> None: ...
    def get(self, run_id: str) -> dict[str, Any]: ...
    def review(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]: ...


class EventTool(Protocol):
    def emit(self, run_id: str, event: str, **details: Any) -> None: ...


@dataclass
class Tools:
    crm: CRMTool
    analysis: AnalysisTool
    memory: MemoryTool
    events: EventTool


@dataclass
class Session:
    """Short-term memory; each run owns an independent instance."""
    run_id: str
    client: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Agent(Protocol):
    name: str
    def execute(self, session: Session, tools: Tools) -> None: ...
