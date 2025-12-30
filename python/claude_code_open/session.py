"""Session manager for Python Claude Code API surface."""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import Message


SESSION_DIR = Path.home() / ".claude" / "sessions"
MAX_SESSIONS = 100
SESSION_EXPIRY_DAYS = 30


@dataclass
class SessionMetadata:
    id: str
    name: Optional[str]
    created_at: int
    updated_at: int
    working_directory: str
    model: str
    message_count: int
    token_usage: Dict[str, int]
    tags: Optional[List[str]] = None
    summary: Optional[str] = None
    parent_id: Optional[str] = None
    fork_point: Optional[int] = None
    branches: Optional[List[str]] = None
    fork_name: Optional[str] = None
    merged_from: Optional[List[str]] = None
    cost: Optional[float] = None
    has_exited_plan_mode: Optional[bool] = None
    needs_plan_mode_exit_attachment: Optional[bool] = None
    active_plan_id: Optional[str] = None
    plan_history: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "workingDirectory": self.working_directory,
            "model": self.model,
            "messageCount": self.message_count,
            "tokenUsage": self.token_usage,
            "tags": self.tags,
            "summary": self.summary,
            "parentId": self.parent_id,
            "forkPoint": self.fork_point,
            "branches": self.branches,
            "forkName": self.fork_name,
            "mergedFrom": self.merged_from,
            "cost": self.cost,
            "hasExitedPlanMode": self.has_exited_plan_mode,
            "needsPlanModeExitAttachment": self.needs_plan_mode_exit_attachment,
            "activePlanId": self.active_plan_id,
            "planHistory": self.plan_history,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SessionMetadata":
        return SessionMetadata(
            id=data.get("id", ""),
            name=data.get("name"),
            created_at=data.get("createdAt", 0),
            updated_at=data.get("updatedAt", 0),
            working_directory=data.get("workingDirectory", ""),
            model=data.get("model", ""),
            message_count=data.get("messageCount", 0),
            token_usage=data.get("tokenUsage", {"input": 0, "output": 0, "total": 0}),
            tags=data.get("tags"),
            summary=data.get("summary"),
            parent_id=data.get("parentId"),
            fork_point=data.get("forkPoint"),
            branches=data.get("branches"),
            fork_name=data.get("forkName"),
            merged_from=data.get("mergedFrom"),
            cost=data.get("cost"),
            has_exited_plan_mode=data.get("hasExitedPlanMode"),
            needs_plan_mode_exit_attachment=data.get("needsPlanModeExitAttachment"),
            active_plan_id=data.get("activePlanId"),
            plan_history=data.get("planHistory"),
        )


@dataclass
class SessionData:
    metadata: SessionMetadata
    messages: List[Message] = field(default_factory=list)
    system_prompt: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "messages": self.messages,
            "systemPrompt": self.system_prompt,
            "context": self.context,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SessionData":
        return SessionData(
            metadata=SessionMetadata.from_dict(data.get("metadata", {})),
            messages=data.get("messages", []),
            system_prompt=data.get("systemPrompt"),
            context=data.get("context"),
        )


def generate_session_id() -> str:
    timestamp = int(time.time() * 1000)
    return f"{_to_base36(timestamp)}-{secrets.token_hex(4)}"


def generate_user_id() -> str:
    return secrets.token_hex(32)


def ensure_session_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def get_session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def save_session(session: SessionData) -> None:
    ensure_session_dir()
    session.metadata.updated_at = _timestamp_ms()
    session.metadata.message_count = len(session.messages)

    path = get_session_path(session.metadata.id)
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    cleanup_old_sessions()


def load_session(session_id: str) -> Optional[SessionData]:
    path = get_session_path(session_id)
    if not path.exists():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return SessionData.from_dict(content)
    except json.JSONDecodeError:
        return None


def delete_session(session_id: str) -> bool:
    path = get_session_path(session_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def list_sessions(
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
    sort_by: str = "updatedAt",
    sort_order: str = "desc",
    tags: Optional[List[str]] = None,
) -> List[SessionMetadata]:
    ensure_session_dir()
    sessions: List[SessionMetadata] = []

    for file in SESSION_DIR.glob("*.json"):
        try:
            content = json.loads(file.read_text(encoding="utf-8"))
            sessions.append(SessionMetadata.from_dict(content.get("metadata", {})))
        except json.JSONDecodeError:
            continue

    filtered = sessions
    if search:
        search_lower = search.lower()
        filtered = [
            session
            for session in filtered
            if (session.name or "").lower().find(search_lower) != -1
            or (session.summary or "").lower().find(search_lower) != -1
            or search_lower in session.id
        ]

    if tags:
        filtered = [
            session
            for session in filtered
            if session.tags and any(tag in tags for tag in session.tags)
        ]

    reverse = sort_order.lower() == "desc"
    filtered.sort(key=lambda s: getattr(s, _snake_case(sort_by), 0) or 0, reverse=reverse)

    return filtered[offset : offset + limit]


def cleanup_old_sessions() -> None:
    now = _timestamp_ms()
    expiry_ms = SESSION_EXPIRY_DAYS * 24 * 60 * 60 * 1000

    sessions = list(SESSION_DIR.glob("*.json"))
    if len(sessions) <= MAX_SESSIONS:
        for file in sessions:
            try:
                content = json.loads(file.read_text(encoding="utf-8"))
                metadata = SessionMetadata.from_dict(content.get("metadata", {}))
                if now - metadata.updated_at > expiry_ms:
                    file.unlink(missing_ok=True)
            except json.JSONDecodeError:
                continue
        return

    sessions.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for file in sessions[MAX_SESSIONS:]:
        file.unlink(missing_ok=True)


def create_session(
    name: Optional[str],
    model: str,
    working_directory: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> SessionData:
    now = _timestamp_ms()
    metadata = SessionMetadata(
        id=generate_session_id(),
        name=name,
        created_at=now,
        updated_at=now,
        working_directory=working_directory or os.getcwd(),
        model=model,
        message_count=0,
        token_usage={"input": 0, "output": 0, "total": 0},
    )
    return SessionData(metadata=metadata, messages=[], system_prompt=system_prompt)


def add_message_to_session(
    session: SessionData,
    message: Message,
    token_usage: Optional[Dict[str, int]] = None,
) -> None:
    session.messages.append(message)
    session.metadata.message_count = len(session.messages)
    session.metadata.updated_at = _timestamp_ms()
    if token_usage:
        session.metadata.token_usage["input"] += token_usage.get("input", 0)
        session.metadata.token_usage["output"] += token_usage.get("output", 0)
        session.metadata.token_usage["total"] = (
            session.metadata.token_usage["input"] + session.metadata.token_usage["output"]
        )


def export_session_to_json(session: SessionData) -> str:
    return json.dumps(session.to_dict(), ensure_ascii=False, indent=2)


def export_session_to_markdown(session: SessionData) -> str:
    lines = [f"# Session {session.metadata.name or session.metadata.id}"]
    for message in session.messages:
        role = message.get("role", "")
        lines.append(f"\n## {role.title()}\n")
        content = message.get("content", "")
        if isinstance(content, str):
            lines.append(content)
        else:
            for block in content:
                if block.get("type") == "text":
                    lines.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    lines.append(str(block.get("content", "")))
    return "\n".join(lines)


def export_session_to_file(session_id: str, path: str, format: str = "json") -> bool:
    session = load_session(session_id)
    if not session:
        return False

    content = export_session_to_json(session) if format == "json" else export_session_to_markdown(session)
    Path(path).write_text(content, encoding="utf-8")
    return True


def get_session_for_directory(directory: str) -> Optional[SessionData]:
    sessions = list_sessions(limit=50, sort_by="updatedAt")
    for session in sessions:
        if session.working_directory == directory:
            loaded = load_session(session.id)
            if loaded:
                return loaded
    return None


def fork_session(session_id: str, from_message_index: Optional[int], name: Optional[str], tags: Optional[List[str]]) -> Optional[SessionData]:
    session = load_session(session_id)
    if not session:
        return None

    fork_point = from_message_index if from_message_index is not None else len(session.messages)
    forked_messages = session.messages[:fork_point]
    forked = create_session(
        name=name or session.metadata.name,
        model=session.metadata.model,
        working_directory=session.metadata.working_directory,
        system_prompt=session.system_prompt,
    )
    forked.messages = list(forked_messages)
    forked.metadata.parent_id = session.metadata.id
    forked.metadata.fork_point = fork_point
    forked.metadata.tags = tags or session.metadata.tags
    save_session(forked)

    session.metadata.branches = list({*(session.metadata.branches or []), forked.metadata.id})
    save_session(session)
    return forked


def merge_sessions(target_session_id: str, source_session_id: str, strategy: str = "append") -> Optional[SessionData]:
    target = load_session(target_session_id)
    source = load_session(source_session_id)
    if not target or not source:
        return None

    if strategy == "replace":
        target.messages = list(source.messages)
    elif strategy == "interleave":
        merged: List[Message] = []
        for index in range(max(len(target.messages), len(source.messages))):
            if index < len(target.messages):
                merged.append(target.messages[index])
            if index < len(source.messages):
                merged.append(source.messages[index])
        target.messages = merged
    else:
        target.messages.extend(source.messages)

    target.metadata.merged_from = list({*(target.metadata.merged_from or []), source.metadata.id})
    save_session(target)
    return target


class SessionManager:
    def __init__(self, auto_save: bool = True, auto_save_interval_ms: int = 30_000) -> None:
        self.current_session: Optional[SessionData] = None
        self.auto_save = auto_save
        self.auto_save_interval_ms = auto_save_interval_ms
        self._last_auto_save = _timestamp_ms()

    def start(
        self,
        name: Optional[str],
        model: str,
        working_directory: Optional[str] = None,
        system_prompt: Optional[str] = None,
        resume: bool = False,
    ) -> SessionData:
        if resume:
            resumed = get_session_for_directory(working_directory or os.getcwd())
            if resumed:
                self.current_session = resumed
                return resumed

        self.current_session = create_session(name, model, working_directory, system_prompt)
        return self.current_session

    def resume(self, session_id: str) -> Optional[SessionData]:
        session = load_session(session_id)
        if session:
            self.current_session = session
        return session

    def get_current(self) -> Optional[SessionData]:
        return self.current_session

    def add_message(self, message: Message, token_usage: Optional[Dict[str, int]] = None) -> None:
        if not self.current_session:
            return
        add_message_to_session(self.current_session, message, token_usage)
        self._maybe_auto_save()

    def save(self) -> None:
        if self.current_session:
            save_session(self.current_session)

    def end(self) -> None:
        self.save()
        self.current_session = None

    def export(self, format: str = "markdown") -> Optional[str]:
        if not self.current_session:
            return None
        return (
            export_session_to_json(self.current_session)
            if format == "json"
            else export_session_to_markdown(self.current_session)
        )

    def fork(
        self,
        from_message_index: Optional[int] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[SessionData]:
        if not self.current_session:
            return None
        forked = fork_session(self.current_session.metadata.id, from_message_index, name, tags)
        if forked:
            self.current_session = forked
        return forked

    def merge(self, source_session_id: str, strategy: str = "append") -> bool:
        if not self.current_session:
            return False
        merged = merge_sessions(self.current_session.metadata.id, source_session_id, strategy)
        if merged:
            self.current_session = merged
            return True
        return False

    def rename(self, new_name: str) -> bool:
        if not self.current_session:
            return False
        self.current_session.metadata.name = new_name
        self.current_session.metadata.updated_at = _timestamp_ms()
        self.save()
        return True

    def update_tags(self, tags: List[str], mode: str = "replace") -> bool:
        if not self.current_session:
            return False

        current_tags = self.current_session.metadata.tags or []
        if mode == "replace":
            self.current_session.metadata.tags = list(tags)
        elif mode == "add":
            self.current_session.metadata.tags = list({*current_tags, *tags})
        elif mode == "remove":
            self.current_session.metadata.tags = [tag for tag in current_tags if tag not in tags]
        self.current_session.metadata.updated_at = _timestamp_ms()
        self.save()
        return True

    def update_cost(self, input_tokens: int, output_tokens: int, model: Optional[str] = None) -> None:
        if not self.current_session:
            return
        model_name = model or self.current_session.metadata.model
        cost_per_million = {"input": 3.0, "output": 15.0}
        if "opus" in model_name:
            cost_per_million = {"input": 15.0, "output": 75.0}
        elif "haiku" in model_name:
            cost_per_million = {"input": 0.25, "output": 1.25}

        cost = (input_tokens / 1_000_000) * cost_per_million["input"] + (
            output_tokens / 1_000_000
        ) * cost_per_million["output"]

        self.current_session.metadata.cost = (self.current_session.metadata.cost or 0.0) + cost

    def get_summary(self) -> Optional[Dict[str, Any]]:
        if not self.current_session:
            return None
        metadata = self.current_session.metadata
        return {
            "id": metadata.id,
            "name": metadata.name,
            "messageCount": metadata.message_count,
            "tokenUsage": metadata.token_usage,
            "cost": metadata.cost,
            "createdAt": metadata.created_at,
            "updatedAt": metadata.updated_at,
            "model": metadata.model,
            "tags": metadata.tags,
            "hasBranches": bool(metadata.branches),
            "branchCount": len(metadata.branches or []),
        }

    def _maybe_auto_save(self) -> None:
        if not self.auto_save:
            return
        now = _timestamp_ms()
        if now - self._last_auto_save >= self.auto_save_interval_ms:
            self.save()
            self._last_auto_save = now


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def _to_base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while value:
        value, idx = divmod(value, 36)
        result = chars[idx] + result
    return result or "0"


def _snake_case(name: str) -> str:
    translated = []
    for char in name:
        if char.isupper():
            translated.append("_" + char.lower())
        else:
            translated.append(char)
    return "".join(translated).lstrip("_")
