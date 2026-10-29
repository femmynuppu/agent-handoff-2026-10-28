"""Confined, content-addressed evidence and immutable research-only state.

Configuration is data, never authority to expand the compiled-in safety policy.
SQLite owns record ordering; verified evidence blobs own scientific content.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid


class SafetyError(ValueError):
    """A policy, integrity or immutable-record boundary was violated."""


def utcnow() -> str:
    """Return an aware UTC timestamp; never infer historical availability."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json_value(value: Any, ancestors: set[int] | None = None) -> None:
    """Reject lossy coercions, cycles, nonfinite numbers and invalid Unicode."""
    ancestors = set() if ancestors is None else ancestors
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise SafetyError("JSON numbers must be finite")
        return
    if type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise SafetyError("JSON strings must be valid UTF-8") from exc
        return
    if type(value) not in (dict, list):
        raise SafetyError("Only JSON-native values are accepted")
    marker = id(value)
    if marker in ancestors:
        raise SafetyError("Cyclic JSON is not allowed")
    ancestors.add(marker)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise SafetyError("JSON object keys must be strings")
                _json_value(key, ancestors)
                _json_value(item, ancestors)
        else:
            for item in value:
                _json_value(item, ancestors)
    finally:
        ancestors.remove(marker)


def canonical_json(value: Any) -> str:
    """Serialize finite, native JSON deterministically without ASCII escaping."""
    try:
        _json_value(value)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (RecursionError, OverflowError, ValueError) as exc:
        raise SafetyError("Invalid or excessively nested JSON") from exc


def digest(value: Any) -> str:
    """SHA256 of canonical UTF-8 JSON (not of a repr or arbitrary file)."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_DOMAINS = ["www.bankofcanada.ca", "www.tradingview.com"]
_DATASET = {
    "provider": "Bank of Canada Valet",
    "series": "FXUSDCAD",
    "start_date": "2023-01-01",
    "end_date": "2025-12-31",
    "timezone": "America/Toronto",
    "units": "CAD per USD",
    "source_url": "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?start_date=2023-01-01&end_date=2025-12-31",
    "docs_url": "https://www.bankofcanada.ca/valet/docs",
    "terms_url": "https://www.bankofcanada.ca/terms/",
    "robots_url": "https://www.bankofcanada.ca/robots.txt",
}
DEFAULT_CONFIG = {
    "workspace_id": "SIQE_QUEST",
    "live_trading": False,
    "fine_tuning": False,
    "public_http_listener": False,
    "bind_host": "127.0.0.1",
    "allowed_domains": _DOMAINS,
    "dataset": _DATASET,
    "max_queue": 128,
    "max_depth": 3,
    "task_budget": 8,
    "max_attempts": 3,
    "memory_mb": 256,
    "cpu_seconds": 120,
    "max_tasks_per_cycle": 8,
    "max_network_requests_per_cycle": 4,
    "review_interval_seconds": 21600,
    "max_log_bytes": 1048576,
    "network_timeout_seconds": 20,
    "max_response_bytes": 4194304,
    "idle_seconds": 2,
}
# Hard maxima prevent a config file turning bounded research into unbounded work.
_BOUNDS = {
    "max_queue": (1, 4096),
    "max_depth": (1, 16),
    "task_budget": (1, 128),
    "max_attempts": (1, 10),
    "memory_mb": (32, 512),
    "cpu_seconds": (1, 300),
    "max_tasks_per_cycle": (1, 32),
    "max_network_requests_per_cycle": (1, 4),
    "review_interval_seconds": (60, 604800),
    "max_log_bytes": (1024, 16777216),
    "network_timeout_seconds": (1, 60),
    "max_response_bytes": (1024, 16777216),
    "idle_seconds": (1, 60),
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ACTION = re.compile(r"^[a-z][a-z0-9_]*(?:[.:][a-z][a-z0-9_]*)*$")
_SECRET_KEY = re.compile(
    r"password|passwd|secret|token|credential|authorization|cookie|api.?key|"
    r"private.?key|access.?key|client.?key|signature",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[^\s,;]+|"
    r"\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|credential)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)|"
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"
)
_URL = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def _redact_text(value: str) -> str:
    def clean_url(match: re.Match[str]) -> str:
        try:
            parts = urlsplit(match.group(0))
            host = parts.hostname or "redacted"
            if parts.port:
                host += f":{parts.port}"
            return urlunsplit(
                (
                    parts.scheme,
                    host,
                    parts.path,
                    "[REDACTED]" if parts.query else "",
                    "",
                )
            )
        except ValueError:
            return "[REDACTED URL]"

    return _SECRET_TEXT.sub("[REDACTED]", _URL.sub(clean_url, value))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _redact_text(key): "[REDACTED]"
            if _SECRET_KEY.search(key)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return _redact_text(value) if isinstance(value, str) else value


def _parse_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in items:
            if key in result:
                raise SafetyError("Duplicate JSON keys are not allowed")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                SafetyError("Nonfinite JSON is not allowed")
            ),
        )
        canonical_json(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SafetyError("Invalid persisted JSON") from exc


class _Connection(sqlite3.Connection):
    """A SQLite transaction context that also releases its owned connection."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    """Workspace-confined evidence store; every connection is independently owned.

    Files are not a cryptographic defense against the operating-system owner who
    can replace both database and blobs. Hash verification detects corruption of
    either retained copy; SQLite triggers prevent ordinary UPDATE/DELETE writes.
    """

    def __init__(self, root: Path | str):
        requested = Path(root).expanduser()
        if requested.is_symlink():
            raise SafetyError("Workspace root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        self.root = requested.resolve(strict=True)
        self._mkdir("state")
        self._mkdir("evidence")
        self._mkdir("evidence/blobs")
        self.config = self._load_config()
        # Never open/close an auxiliary descriptor for the database inode:
        # POSIX close() can release another SQLite connection's process locks.
        with self.connection() as conn:
            integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise SafetyError("Database integrity check failed; preserve state")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    UNIQUE(kind, record_key)
                );
                CREATE TRIGGER IF NOT EXISTS records_no_update
                BEFORE UPDATE ON records BEGIN
                    SELECT RAISE(ABORT, 'immutable record');
                END;
                CREATE TRIGGER IF NOT EXISTS records_no_delete
                BEFORE DELETE ON records BEGIN
                    SELECT RAISE(ABORT, 'immutable record');
                END;
            """)
            conn.commit()

    def path(self, relative: str) -> Path:
        """Resolve only workspace-relative paths, rejecting traversal and escapes."""
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise SafetyError("Expected a nonempty relative path")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SafetyError("Absolute paths and traversal are forbidden")
        try:
            resolved = (self.root / candidate).resolve()
            resolved.relative_to(self.root)
        except (ValueError, OSError, RuntimeError) as exc:
            raise SafetyError(
                "Path escapes the workspace or has invalid links"
            ) from exc
        return resolved

    def _mkdir(self, relative: str) -> None:
        current = self.root
        for part in Path(relative).parts:
            current /= part
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            if current.is_symlink() or not current.is_dir():
                raise SafetyError("Internal directories must be real directories")

    def _internal(self, relative: str) -> Path:
        """For managed state reject even an internal symlink, not only escapes."""
        confined = self.path(relative)
        current = self.root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink():
                raise SafetyError("Managed state cannot use symbolic links")
        return confined

    def _load_config(self) -> dict:
        filename = self._internal("config/research.json")
        config = copy.deepcopy(DEFAULT_CONFIG)
        if filename.exists():
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise SafetyError("Configuration must be a regular file")
                if os.fstat(stream.fileno()).st_size > 65536:
                    raise SafetyError("Configuration is too large")
                custom = _parse_json(stream.read())
            if type(custom) is not dict or set(custom) - set(config):
                raise SafetyError("Unknown configuration keys are forbidden")
            config.update(custom)
        if config["workspace_id"] != "SIQE_QUEST":
            raise SafetyError("Workspace identity cannot be changed")
        for key in ("live_trading", "fine_tuning", "public_http_listener"):
            if config[key] is not False:
                raise SafetyError(f"{key} is unconditionally disabled")
        if config["bind_host"] not in ("127.0.0.1", "::1", "localhost"):
            raise SafetyError("Public listeners are forbidden")
        domains = config["allowed_domains"]
        if (
            type(domains) is not list
            or not domains
            or any(
                type(domain) is not str or domain not in _DOMAINS for domain in domains
            )
            or len(set(domains)) != len(domains)
        ):
            raise SafetyError("Source permissions cannot exceed official allowlist")
        if config["dataset"] != _DATASET:
            raise SafetyError("The locked representative dataset cannot be changed")
        for key, (minimum, maximum) in _BOUNDS.items():
            if type(config[key]) is not int or not minimum <= config[key] <= maximum:
                raise SafetyError(f"{key} must be an integer in [{minimum}, {maximum}]")
        return config

    def connection(self) -> sqlite3.Connection:
        """Return a fresh connection; with commits/rolls back then closes it.

        Outside a with block the caller must close explicitly. A connection is
        single-use as a context manager; do not retain it across separate blocks.
        """
        database = self._internal("state/siqe.sqlite3")
        try:
            metadata = database.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata is not None and not stat.S_ISREG(metadata.st_mode):
            raise SafetyError("Database must be a regular file")
        for suffix in ("-wal", "-shm", "-journal"):
            self._internal("state/siqe.sqlite3" + suffix)
        conn = sqlite3.connect(
            database, timeout=15, isolation_level="DEFERRED", factory=_Connection
        )
        try:
            if metadata is None:
                os.chmod(database, 0o600, follow_symlinks=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("PRAGMA synchronous=FULL")
            return conn
        except BaseException:
            conn.close()
            raise

    def _blob_directory(self) -> int:
        directory = self._internal("evidence/blobs")
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def put_blob(
        self, content: bytes, media_type: str = "application/octet-stream"
    ) -> dict:
        """Publish complete bytes atomically without ever replacing an old blob."""
        if type(content) is not bytes:
            raise SafetyError("Blob content must be bytes")
        if (
            not isinstance(media_type, str)
            or not media_type
            or len(media_type) > 256
            or any(ord(char) < 32 for char in media_type)
        ):
            raise SafetyError("Invalid media type")
        sha256 = hashlib.sha256(content).hexdigest()
        reference = {
            "sha256": sha256,
            "path": f"evidence/blobs/{sha256}",
            "bytes": len(content),
            "media_type": media_type,
        }
        directory = self._blob_directory()
        temporary = ".pending-" + uuid.uuid4().hex
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
            try:
                os.link(
                    temporary,
                    sha256,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                os.fsync(directory)
            except FileExistsError:
                pass
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)
        # Existing content is verified rather than repaired or silently replaced.
        self.read_blob(reference)
        return reference

    def read_blob(self, reference: dict | str) -> bytes:
        """Read only content-addressed evidence and verify both name and bytes."""
        if isinstance(reference, str):
            sha256 = reference if _HASH.fullmatch(reference) else Path(reference).name
            relative = f"evidence/blobs/{sha256}"
            if reference != sha256 and reference != relative:
                raise SafetyError("Invalid evidence path")
            expected_size = None
        elif type(reference) is dict:
            sha256 = reference.get("sha256")
            relative = reference.get("path")
            expected_size = reference.get("bytes")
            if (
                type(expected_size) is not int
                or expected_size < 0
                or relative != f"evidence/blobs/{sha256}"
            ):
                raise SafetyError("Invalid evidence descriptor")
        else:
            raise SafetyError("Invalid evidence reference")
        if not isinstance(sha256, str) or not _HASH.fullmatch(sha256):
            raise SafetyError("Invalid evidence hash")
        self._internal(relative)
        directory = self._blob_directory()
        try:
            fd = os.open(
                sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise SafetyError("Evidence must be a regular file")
                content = stream.read()
        except OSError as exc:
            raise SafetyError("Evidence is missing or inaccessible") from exc
        finally:
            os.close(directory)
        if (
            hashlib.sha256(content).hexdigest() != sha256
            or expected_size is not None
            and len(content) != expected_size
        ):
            raise SafetyError("Evidence corruption detected")
        return content

    @staticmethod
    def _identity(kind: str, key: str) -> None:
        if (
            type(kind) is not str
            or not kind
            or len(kind) > 128
            or type(key) is not str
            or not key
            or len(key) > 1024
        ):
            raise SafetyError("Records need bounded, nonempty kind and key")
        if any(ord(char) < 32 for char in kind + key):
            raise SafetyError("Record identities cannot contain control characters")

    def _decode_record(self, row: sqlite3.Row) -> dict:
        try:
            envelope = _parse_json(row["content_json"])
            evidence = _parse_json(row["evidence_json"])
            raw = self.read_blob(evidence)
            if raw != canonical_json(envelope).encode("utf-8"):
                raise SafetyError("Record evidence differs from database")
            if (
                type(envelope) is not dict
                or set(envelope) != {"record_id", "kind", "key", "created_at", "value"}
                or type(envelope["value"]) is not dict
            ):
                raise SafetyError("Invalid record envelope")
            body = {key: value for key, value in envelope.items() if key != "record_id"}
            if digest(body) != envelope["record_id"]:
                raise SafetyError("Record identifier corruption detected")
            if (
                row["record_id"] != envelope["record_id"]
                or row["kind"] != envelope["kind"]
                or row["record_key"] != envelope["key"]
                or row["created_at"] != envelope["created_at"]
            ):
                raise SafetyError("Record metadata corruption detected")
            return {**envelope, "evidence": evidence}
        except (KeyError, TypeError, UnicodeError) as exc:
            raise SafetyError("Malformed persisted record") from exc

    def record(self, kind: str, key: str, value: dict) -> dict:
        """Append once per identity; equal content is idempotent, conflicts fail."""
        self._identity(kind, key)
        if type(value) is not dict:
            raise SafetyError("Record values must be JSON objects")
        serialized = canonical_json(value)
        if kind == "audit":
            serialized = canonical_json(_redact(_parse_json(serialized)))
        # Snapshot caller-owned mutable objects before waiting for the writer lock.
        snapshot = _parse_json(serialized)
        conn = self.connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM records WHERE kind=? AND record_key=?", (kind, key)
            ).fetchone()
            if row is not None:
                existing = self._decode_record(row)
                if canonical_json(existing["value"]) != serialized:
                    raise SafetyError(
                        "Immutable record conflict; use a new version key"
                    )
                conn.commit()
                return existing
            body = {"kind": kind, "key": key, "created_at": utcnow(), "value": snapshot}
            envelope = {"record_id": digest(body), **body}
            content = canonical_json(envelope)
            evidence = self.put_blob(content.encode("utf-8"), "application/json")
            conn.execute(
                """INSERT INTO records
                (record_id, kind, record_key, created_at, content_json, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    envelope["record_id"],
                    kind,
                    key,
                    envelope["created_at"],
                    content,
                    canonical_json(evidence),
                ),
            )
            conn.commit()
            return {**envelope, "evidence": evidence}
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, kind: str, key: str) -> dict | None:
        """Return verified evidence, never an unchecked database value."""
        self._identity(kind, key)
        conn = self.connection()
        try:
            row = conn.execute(
                "SELECT * FROM records WHERE kind=? AND record_key=?", (kind, key)
            ).fetchone()
            return self._decode_record(row) if row is not None else None
        finally:
            conn.close()

    def records(self, kind: str) -> list[dict]:
        """Return verified records in durable insertion order, not key order."""
        self._identity(kind, "listing")
        conn = self.connection()
        try:
            rows = conn.execute(
                "SELECT * FROM records WHERE kind=? ORDER BY sequence", (kind,)
            ).fetchall()
            return [self._decode_record(row) for row in rows]
        finally:
            conn.close()

    def audit(self, action: str, details: dict) -> dict:
        """Persist only redacted details as ordinary immutable audit evidence.

        Callers must label credentials with descriptive keys. Arbitrary opaque
        strings cannot be recognized as credentials; never submit raw secrets.
        """
        if type(action) is not str or not action or len(action) > 256:
            raise SafetyError("Invalid audit action")
        if type(details) is not dict:
            raise SafetyError("Audit details must be a JSON object")
        canonical_json(details)
        return self.record(
            "audit",
            uuid.uuid4().hex,
            {"action": _redact_text(action), "details": _redact(details)},
        )

    def authorize(self, action: str) -> None:
        """Deny everything outside explicit research namespaces, irrespective of config."""
        allowed = False
        if isinstance(action, str) and len(action) <= 256 and _ACTION.fullmatch(action):
            components = re.split(r"[.:_]", action)
            root = re.split(r"[.:]", action)[0]
            forbidden = {
                "trade",
                "trades",
                "trading",
                "buy",
                "sell",
                "order",
                "orders",
                "withdraw",
                "withdrawal",
                "withdrawals",
                "transfer",
                "deposit",
                "account",
                "accounts",
                "broker",
                "funds",
                "publication",
                "publish",
                "messaging",
                "external",
                "exec",
                "execute",
                "shell",
                "subprocess",
                "credential",
                "credentials",
                "finetune",
                "finetuning",
                "tuning",
                "live",
            }
            allowed = root in {
                "research",
                "read",
                "simulate",
                "knowledge",
                "report",
            } and not forbidden.intersection(components)
        if not allowed:
            # Invalid or secret-bearing action strings are not copied into the log.
            label = (
                action
                if isinstance(action, str)
                and len(action) <= 256
                and _ACTION.fullmatch(action)
                else "invalid_action"
            )
            self.audit(
                "authorization.denied",
                {"requested_action": label, "reason": "research_only_allowlist"},
            )
            raise SafetyError("Action denied by immutable research-only policy")
