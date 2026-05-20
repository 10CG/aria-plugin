"""state-scanner skill 共享 lib 包。

P2 Layer L (multi-terminal-coordination) 新增:
- claim_schema:Layer L claim YAML schema v1 + ClaimRecord + parse/serialize (TASK-010)
- identity:三段身份 (owner / container_id / session_id) + 持久化 (TASK-011)
- track_id:确定性 track-id 派生函数 (TASK-014)

后续 P2 task 将加入:
- constants (TASK-018, HEARTBEAT_INTERVAL / STALE_TTL / CLOCK_SKEW_WARN_THRESHOLD)
- coordination_ref (TASK-012/013, orphan ref CRUD)
- reconcile (TASK-015, 4 规则裁决协议)
- claim_lifecycle (TASK-018, acquire / heartbeat / release)
- failure_handlers (TASK-019, 失败矩阵 7 路径)
"""
from __future__ import annotations

from .claim_schema import (
    ClaimRecord,
    SCHEMA_VERSION_CURRENT,
    STATUS_ENUM,
    STATUS_WRITABLE,
    parse_claim,
    serialize_claim,
)
from .identity import (
    Identity,
    get_container_id,
    get_identity,
    get_owner,
    get_session_id,
)
from .coordination_ref import (
    BOOTSTRAP_COMMIT_MSG,
    EMPTY_TREE_SHA,
    REF_NAME,
    REMOTE_REF,
    BootstrapResult,
    bootstrap,
)
from .track_id import (
    MAX_TRACK_ID_LENGTH,
    NON_ASCII_FALLBACK_PREFIX,
    SHA_HEX_LENGTH,
    derive_track_id,
    is_ascii,
)

__all__ = [
    # claim_schema (TASK-010)
    "ClaimRecord",
    "SCHEMA_VERSION_CURRENT",
    "STATUS_ENUM",
    "STATUS_WRITABLE",
    "parse_claim",
    "serialize_claim",
    # identity (TASK-011)
    "Identity",
    "get_container_id",
    "get_identity",
    "get_owner",
    "get_session_id",
    # coordination_ref (TASK-012)
    "BOOTSTRAP_COMMIT_MSG",
    "EMPTY_TREE_SHA",
    "REF_NAME",
    "REMOTE_REF",
    "BootstrapResult",
    "bootstrap",
    # track_id (TASK-014)
    "MAX_TRACK_ID_LENGTH",
    "NON_ASCII_FALLBACK_PREFIX",
    "SHA_HEX_LENGTH",
    "derive_track_id",
    "is_ascii",
]
