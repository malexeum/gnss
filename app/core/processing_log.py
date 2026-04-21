from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class LogEntry:
    timestamp: str
    level: str
    module: str
    params: Dict[str, Any]
    summary: str


class ProcessingLog:
    def __init__(self, version: str = "0.1.0"):
        self.version: str = version
        self.entries: List[LogEntry] = []

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def add(
        self,
        module: str,
        params: Optional[Dict[str, Any]] = None,
        summary: str = "",
        level: str = "INFO",
    ) -> None:
        entry = LogEntry(
            timestamp=self._now_iso(),
            level=str(level).upper(),
            module=str(module),
            params=params or {},
            summary=str(summary),
        )
        self.entries.append(entry)

    def add_warning(self, message: str, module: str = "core") -> None:
        self.add(module=module, params={}, summary=message, level="WARNING")

    def add_error(self, message: str, module: str = "core") -> None:
        self.add(module=module, params={}, summary=message, level="ERROR")

    def clear(self) -> None:
        self.entries.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "entries": [asdict(e) for e in self.entries],
        }

    def to_text(self) -> str:
        lines = [f"GNSS processing log. Version: {self.version}", ""]
        for e in self.entries:
            params_str = ", ".join(f"{k}={v!r}" for k, v in (e.params or {}).items())
            if params_str:
                lines.append(f"[{e.timestamp}] {e.level:<7} {e.module}: {e.summary} ({params_str})")
            else:
                lines.append(f"[{e.timestamp}] {e.level:<7} {e.module}: {e.summary}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: str | Path, fmt: str = "txt") -> Path:
        fmt = fmt.lower()
        path = Path(path)
        if fmt == "txt":
            if path.suffix.lower() != ".txt":
                path = path.with_suffix(".txt")
            path.write_text(self.to_text(), encoding="utf-8")
            return path
        if fmt == "json":
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
            path.write_text(self.to_json(), encoding="utf-8")
            return path
        raise ValueError(f"Неизвестный формат журнала: {fmt!r}")
