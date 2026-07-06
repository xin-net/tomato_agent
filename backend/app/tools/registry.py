from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    caller: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: Any, method_name: str = "observe") -> None:
        name = getattr(tool, "name", tool.__class__.__name__)
        description = getattr(tool, "description", "")
        caller = getattr(tool, method_name)
        self._tools[name] = ToolSpec(name=name, description=description, caller=caller)

    def call(self, name: str, **kwargs) -> Any:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")
        return self._tools[name].caller(**kwargs)

    def call_serialized(self, name: str, **kwargs) -> dict[str, Any]:
        result = self.call(name, **kwargs)
        return self.serialize(result)

    def serialize(self, result: Any) -> Any:
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if isinstance(result, list):
            return [self.serialize(item) for item in result]
        if isinstance(result, dict):
            return {key: self.serialize(value) for key, value in result.items()}
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return result

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": spec.name, "description": spec.description}
            for spec in self._tools.values()
        ]
