from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    directory = Path.home() / ".claude"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sessions_path() -> Path:
    return _state_dir() / "sessions.json"


@dataclass
class SessionStats:
    message_count: int
    total_cost: str = "$0.00"


@dataclass
class Session:
    session_id: str
    created_at: str
    working_directory: str
    name: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def get_stats(self) -> SessionStats:
        return SessionStats(message_count=len(self.messages))


class SessionManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _sessions_path()
        self._cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text(encoding="utf-8"))
                return self._cache
            except json.JSONDecodeError:
                self._cache = {"sessions": []}
                return self._cache
        self._cache = {"sessions": []}
        return self._cache

    def _save(self) -> None:
        data = self._load()
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_session(self, working_directory: str, name: str | None = None) -> Session:
        session_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        session = Session(
            session_id=session_id,
            created_at=created_at,
            working_directory=working_directory,
            name=name,
            messages=[],
        )
        sessions = self._load().setdefault("sessions", [])
        sessions.append(self._serialize(session))
        self._save()
        return session

    def list_sessions(self, limit: int = 20, search: str | None = None) -> list[Session]:
        sessions = [self._deserialize(s) for s in self._load().get("sessions", [])]
        if search:
            sessions = [
                s for s in sessions
                if search.lower() in s.session_id.lower()
                or (s.name and search.lower() in s.name.lower())
                or search.lower() in s.working_directory.lower()
            ]
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    def load_session(self, session_id: str) -> Session | None:
        for session_data in self._load().get("sessions", []):
            if session_data.get("session_id") == session_id:
                return self._deserialize(session_data)
        return None

    def save_session(self, session: Session) -> None:
        data = self._load()
        sessions = data.get("sessions", [])
        for idx, item in enumerate(sessions):
            if item.get("session_id") == session.session_id:
                sessions[idx] = self._serialize(session)
                self._save()
                return
        sessions.append(self._serialize(session))
        self._save()

    def fork_session(self, session: Session) -> Session:
        forked = Session(
            session_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            working_directory=session.working_directory,
            name=session.name,
            messages=list(session.messages),
        )
        self.save_session(forked)
        return forked

    @staticmethod
    def _serialize(session: Session) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "working_directory": session.working_directory,
            "name": session.name,
            "messages": session.messages,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> Session:
        return Session(
            session_id=data.get("session_id", str(uuid.uuid4())),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            working_directory=data.get("working_directory", ""),
            name=data.get("name"),
            messages=data.get("messages", []),
        )


session_manager = SessionManager()
