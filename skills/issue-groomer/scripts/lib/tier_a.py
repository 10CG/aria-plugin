#!/usr/bin/env python3
"""issue-groomer Tier A 机械规则引擎 (P1 MVP, 10CG/Aria#238, TASK-002).

只消费**显式编码信号** (DEC-20261018-001 裁定-7): title 前缀 / label 名 /
staleness 档 / 活跃度档。逐信号枚举 confidence (每条 issue 列出命中信号集,
非聚合分数); 不做任何语义猜测。

设计要点 (逐条对应 TASK-002 verification bullets):

- **裁定-1 (labels.yaml 落点)**: ``resolve_taxonomy(project_root)`` — 项目级
  ``<project_root>/.aria/labels.yaml`` 存在则**整体覆盖**内置默认层 (覆盖非合并:
  项目文件不与内置层做任何字段级合并); 缺省回落内置层
  (``config/labels-default.yaml``, 随插件分发)。**项目文件存在但非法
  (解析失败/SC-9 不一致) 时 fail-closed 抛 ValueError, 绝不静默回落内置层**
  — 静默回落等于拿一套错误的 taxonomy 跑完全量分类。
- **逐信号 confidence**: ``classify`` 返回的每条记录含 ``signals`` 列表, 每个信号
  带 ``source`` (格式固定: ``title-prefix:<规则>`` / ``label:<名>`` /
  ``staleness:<档>`` / ``activity:<档>``) + ``kind`` + ``value``; title-prefix/
  label 两类信号额外带其指向的分类键 ``category``。
  **category 的确定性裁决**: 仅由 title-prefix/label 两类信号决定 — 全部一致
  → 该分类; 零个此类信号 → ``"unknown"``; 多个且不一致 → ``"conflict"``
  (信号集原样枚举, 绝不任选其一 — 任选即隐性猜测)。
  **"无显式信号 → category=unknown + signals=[]" 的操作化定义**: 当 issue
  无 title 前缀命中、无已知 label、且 ``updated``/``comments_count`` 字段
  (可选) 均缺席时, 输出恰为 ``{"category": "unknown", "signals": []}``;
  若 staleness/activity 可计算 (语料形态下 ``updated`` 恒在), 它们作为信号
  枚举进列表, 但不参与 category 裁决 (它们不是分类信号)。
- **时钟 seam**: ``classify(..., now=None)`` — ``now`` 可注入 datetime/date
  (fixture 防时移 flaky); None = 系统时钟。时区规约: 输入日期带 offset 的
  统一转 naive UTC 再比较; 纯日期/naive datetime 原样比较 (语料快照为纯日期)。
  ``updated`` 晚于 ``now`` (未来时间/时钟偏移) 的异常形态确定性钳为最低龄档
  (不抛错, 不猜高档)。
- **SC-9 taxonomy 一致性自检 (实现面)**: ``validate_taxonomy`` 对三层做机械
  校验 — 前缀表 (layer 1) / 分类键→label 规范名映射 (layer 2) / label 信号名
  (layer 3) — 不一致返回具名失败清单, 加载与 classify 双侧 fail-closed。
  (TASK-008 持三层各注错的反事实 fixture。)
- **stdlib-only**: 不依赖 PyYAML (目标环境不保证)。labels.yaml 用本模块内的
  严格受限行级 parser (见 ``_parse_simple_yaml`` docstring 的受限语法文档),
  受控结构 + 拒绝一切未声明形态, 而非「尽量解析」。

受限 YAML 语法 (labels-default.yaml 头部同步文档化):
  1. 仅两层: 顶层 ``key: value`` 标量, 或顶层 ``key:`` 开块后**一层**缩进的
     ``subkey: value`` mapping / ``- item`` 列表 (一个块内二选一, 不得混用);
     更深嵌套、块内再嵌套、flow 序列 ``[a, b]``、多行标量均不支持 (报错)。
  2. 含 ``[`` 的键 (title 前缀) **必须加引号** (``"[bug]": bug``) — 与真 YAML
     的 flow 序列歧义对齐; 未加引号直接报错 (fail-closed, 逼作者写对)。
  3. 缩进只用空格, 同一块内缩进宽度恒定; tab 报错。
  4. 标量: 裸串 / 单双引号串 (引号内不剥注释); 纯整数 (``^-?\\d+$``) 转 int,
     其余一律 str。注释: 整行 ``#`` 与值尾 `` #`` (引号感知)。
  5. 任何层级重复键报错 (静默覆盖 = 配置面假绿)。

tier 结构 (确定性全分割, 边界含左不含右):
  - staleness (age = now - updated, 天): ``<7d`` [0,7) / ``7-30d`` [7,30) /
    ``30-90d`` [30,90) / ``>90d`` [90,∞)。分割证明: 四区间在 N0 上两两不交
    且并集为 N0; 负年龄 (异常) 钳 0 归最低档。
  - activity (comments_count): ``0`` (-∞,0] / ``1-2`` [1,2] / ``3-9`` [3,9] /
    ``10+`` [10,∞)。分割证明: 在 Z 上两两不交且并集为 Z; 负计数 (异常) 归
    ``0`` 档。``comments_count`` 缺席 → 不产 activity 信号 (缺席不是 0, 不猜)。

与 TASK-001 fetch 层的输入契约 (语料快照字段集为基准):
  ``{repo, number, title, labels, created, updated, comments_count?}`` —
  repo/number 必填 (缺席抛 ValueError 指名下标); title/labels 缺席按 ""/[]
  (缺席=无信号, 不是错误); title 在场但非 str / labels 在场但非 list ⇒
  ValueError (E-4, fail-closed); created 收下但 Tier A 不使用 (staleness 锚定
  updated = 最近活动时间); updated/comments_count 可选, 缺席不产对应信号,
  在场但形态非法 (非 str 日期 / 非整型计数) 抛 ValueError (fail-closed)。

下游 SOT: ``taxonomy_hash`` 供 TASK-004 指纹上下文面消费 — canonical 形态
**保留声明顺序** (前缀表/label 表的声明顺序影响信号枚举顺序, 重排也视为
taxonomy 变化, 保守触发重分类), 且不含 ``_meta`` (同内容不同来源同 hash)。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

TAXONOMY_VERSION = 1

# 内置默认层随插件分发: <skill>/config/labels-default.yaml
# (lib/ -> scripts/ -> issue-groomer/ -> config/)
BUILTIN_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "labels-default.yaml"

# 项目级覆盖层固定落点 (Phase 0 裁定-1: .aria/labels.yaml)
PROJECT_CONFIG_RELPATH = Path(".aria") / "labels.yaml"

# 分类信号 (参与 category 裁决) 与属性信号 (只枚举, 不裁决) 的 kind 集
CATEGORY_SIGNAL_KINDS = frozenset({"title-prefix", "label"})

# ---------------------------------------------------------------- 受限 yaml parser

_BARE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]*$")
_BARE_PREFIX_KEY_RE = re.compile(r"^\[[^\"\']*\]$")  # 未加引号的 "[bug]:" — 非法
_INT_VALUE_RE = re.compile(r"^-?\d+$")


class SimpleYamlError(ValueError):
    """受限行级 yaml parser 的结构错误 (带行号)。是 ValueError 的子类:
    调用方 (加载器) 统一以 ValueError 面 fail-closed。"""


def _strip_inline_comment(value: str) -> str:
    """剥值尾 `` #`` 注释, 引号感知 (引号内 # 保留)。

    对齐 state-scanner ``lib/detailed_tasks.py`` 的同名 SOT 语义 (quote-aware,
    要求 # 前有空白), 本模块物理持有自己的副本: issue-groomer 与 state-scanner
    是两个独立 skill, 跨 skill import 违反插件自包含纪律 (裁定-13 契约面
    plugin 外可及; 亦避免 lib 包路径耦合)。
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or value[i - 1].isspace():
                return value[:i].rstrip()
    return value


def _split_key(raw_key: str) -> str:
    """键合法性与去引号。裸键字符集 [A-Za-z0-9_./-] (label 名含 ``/``);
    引号键去一层引号后内容不限。返回规范化键; 非法抛 SimpleYamlError。"""
    k = raw_key.strip()
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'":
        inner = k[1:-1]
        if not inner:
            raise SimpleYamlError("empty quoted key")
        return inner
    if not k:
        raise SimpleYamlError("empty key")
    if _BARE_PREFIX_KEY_RE.match(k):
        raise SimpleYamlError(
            f"bracket key {k!r} must be quoted (e.g. '\"{k}\": value') — "
            "unquoted '[' keys are ambiguous with flow sequences"
        )
    if not _BARE_KEY_RE.match(k):
        raise SimpleYamlError(f"illegal bare key {k!r} (charset [A-Za-z0-9_./-] or quote it)")
    return k


def _split_value(raw_value: str) -> object:
    """值合法性 (剥注释后) 与类型归一: 引号串 → str; 纯整数 → int; 裸串 → str。"""
    v = _strip_inline_comment(raw_value).strip()
    if v == "":
        return None  # 块开行信号 (由调用方区分)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if _INT_VALUE_RE.match(v):
        return int(v)
    return v


def _parse_simple_yaml(text: str) -> dict:
    """解析受限 labels.yaml (语法见模块 docstring 第 1-5 条), 返回
    ``{key: scalar | dict | list[str]}``。保留声明顺序 (dict 插入序)。

    fail-closed: 任何未声明形态 (tab 缩进 / 深嵌套 / 块内混用 / 重复键 /
    未引号 bracket 键 / 悬空行) 抛 ``SimpleYamlError`` (含 1-based 行号),
    绝不「尽量解析」— 配置面的一处静默吞咽就是一套静默错误的分类规则。
    """
    result: dict = {}
    # 当前块状态: block_key = None → 顶层; 开块后 block_indent = -1 表示
    # 「已开块但类型未定」(惰性定型: 块内首行是 '- ' → 列表, 否则 mapping;
    # 到块结束仍无首行 → 空 mapping)。block 引用在首行定型后才挂到 result。
    block: dict | list | None = None
    block_key: str | None = None
    block_indent = -1

    def _finalize_pending_block() -> None:
        """空块收尾: `key:` 后直接遇顶层行/EOF → 空 mapping (语义校验层
        再决定空块是否合法, parser 只负责不静默丢键)。"""
        nonlocal block, block_key, block_indent
        if block_key is not None and block is None:
            result[block_key] = {}
        block, block_key, block_indent = None, None, -1

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.replace("\r", "")  # splitlines 已吃 \r\n; 防孤悬 \r
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < len(line) and line[indent] == "\t":
            raise SimpleYamlError(f"line {lineno}: tab in indentation (spaces only)")
        if indent == 0:
            _finalize_pending_block()  # 回到顶层 (先收尾上一个块)
            if ":" not in line:
                raise SimpleYamlError(f"line {lineno}: expected 'key: value' or 'key:' (no colon)")
            raw_k, _, raw_v = line.partition(":")
            key = _split_key(raw_k)
            if key in result:
                raise SimpleYamlError(f"line {lineno}: duplicate top-level key {key!r}")
            value = _split_value(raw_v)
            if value is None:
                block, block_key, block_indent = None, key, -1  # 开块, 类型/缩进待定
            else:
                result[key] = value
            continue

        # indent > 0: 必须处于某个已开块内
        if block_key is None:
            raise SimpleYamlError(f"line {lineno}: indented line outside any block")
        if block_indent < 0:
            # 块内首行: 钉死缩进宽度 + 定型 (list vs mapping) 并挂到 result
            block_indent = indent
            if stripped.startswith("- "):
                block = []
            else:
                block = {}
            result[block_key] = block
        if indent != block_indent:
            raise SimpleYamlError(
                f"line {lineno}: indent {indent} != block indent {block_indent} "
                f"(one nesting level only, constant width)"
            )
        if isinstance(block, list):
            if not stripped.startswith("- "):
                raise SimpleYamlError(f"line {lineno}: list item expected ('- ...') in block {block_key!r}")
            item = _split_value(stripped[2:])
            if item is None:
                raise SimpleYamlError(f"line {lineno}: empty list item in block {block_key!r}")
            if not isinstance(item, str):
                raise SimpleYamlError(f"line {lineno}: list items must be strings in block {block_key!r}")
            block.append(item)
        else:
            if stripped.startswith("- "):
                raise SimpleYamlError(
                    f"line {lineno}: '- item' inside mapping block {block_key!r} "
                    "(mapping and list items cannot mix in one block)"
                )
            if ":" not in stripped:
                raise SimpleYamlError(f"line {lineno}: expected 'subkey: value' in block {block_key!r}")
            raw_k, _, raw_v = stripped.partition(":")
            sub = _split_key(raw_k)
            if sub in block:
                raise SimpleYamlError(f"line {lineno}: duplicate key {sub!r} in block {block_key!r}")
            value = _split_value(raw_v)
            if value is None:
                raise SimpleYamlError(
                    f"line {lineno}: deeper nesting under {sub!r} not supported "
                    "(two levels max: top key -> one-level block)"
                )
            block[sub] = value
    _finalize_pending_block()  # 尾随空块收尾 (`key:` 后直接 EOF)
    return result


# ---------------------------------------------------------- taxonomy 形状与 SC-9

_TAXONOMY_SECTIONS = ("categories", "title_prefixes", "label_signals")


def parse_taxonomy(raw: object) -> dict:
    """受控形状收口: parser 输出 → taxonomy dict (恰含 version + 三节)。

    未知顶层键报错 (typo 防护: ``title_prefix`` 拼错若被静默忽略, 等于静默
    换上保守默认前缀表 — 配置面假绿的又一形态); 三节必须是 mapping (本
    schema 无列表节); version 必须 == TAXONOMY_VERSION。语义一致性另由
    ``validate_taxonomy`` (SC-9) 把关。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"taxonomy root must be a mapping, got {type(raw).__name__}")
    unknown = sorted(set(raw) - {"version", *_TAXONOMY_SECTIONS})
    if unknown:
        raise ValueError(f"unknown top-level key(s) {unknown} (allowed: version, {list(_TAXONOMY_SECTIONS)})")
    if raw.get("version") != TAXONOMY_VERSION or isinstance(raw.get("version"), bool):
        raise ValueError(f"version must be int {TAXONOMY_VERSION}, got {raw.get('version')!r}")
    for sec in _TAXONOMY_SECTIONS:
        if not isinstance(raw.get(sec), dict):
            raise ValueError(f"section {sec!r} must be a mapping, got {type(raw.get(sec)).__name__}")
    return {
        "version": raw["version"],
        "categories": dict(raw["categories"]),
        "title_prefixes": dict(raw["title_prefixes"]),
        "label_signals": dict(raw["label_signals"]),
    }


def validate_taxonomy(taxonomy: dict) -> list[str]:
    """SC-9 三层一致性自检 (实现面)。返回具名失败清单 (空 = 一致)。

    三层与检查项 (每条独立命名, TASK-008 各注错一份反事实):
      layer 1 前缀表   : prefix-unknown-category / prefix-empty-key
      layer 2 分类键表 : categories-empty / canonical-label-empty /
                         canonical-label-collision (两分类键 → 同一规范 label,
                         suggested 标签产生归属歧义)
      layer 3 label 表 : label-signal-unknown-category / label-signal-empty-key /
                         canonical-label-contradiction (label L 是分类 X 的规范
                         名、又在 label_signals 里指向 Y != X — 同一被观测 label
                         同时「被 X 建议」与「建议 Y」, 自相矛盾)
    """
    problems: list[str] = []
    categories: dict = taxonomy.get("categories", {})
    title_prefixes: dict = taxonomy.get("title_prefixes", {})
    label_signals: dict = taxonomy.get("label_signals", {})

    if not categories:
        problems.append("categories-empty: at least one category key required")
    seen_canonical: dict[str, str] = {}
    for cat_key, canonical in categories.items():
        if not isinstance(canonical, str) or not canonical.strip():
            problems.append(f"canonical-label-empty: category {cat_key!r} -> empty label")
            continue
        if canonical in seen_canonical:
            problems.append(
                f"canonical-label-collision: label {canonical!r} is canonical for both "
                f"{seen_canonical[canonical]!r} and {cat_key!r}"
            )
        else:
            seen_canonical[canonical] = cat_key
    for prefix, cat_key in title_prefixes.items():
        if not isinstance(prefix, str) or not prefix:
            problems.append("prefix-empty-key: empty title prefix")
        elif cat_key not in categories:
            problems.append(f"prefix-unknown-category: prefix {prefix!r} -> {cat_key!r} not in categories")
    for label, cat_key in label_signals.items():
        if not isinstance(label, str) or not label:
            problems.append("label-signal-empty-key: empty label name")
        elif cat_key not in categories:
            problems.append(f"label-signal-unknown-category: label {label!r} -> {cat_key!r} not in categories")
        elif label in seen_canonical and seen_canonical[label] != cat_key:
            problems.append(
                f"canonical-label-contradiction: label {label!r} is canonical for "
                f"{seen_canonical[label]!r} but signals {cat_key!r}"
            )
    return problems


def _validated(taxonomy: dict, source: str) -> dict:
    problems = validate_taxonomy(taxonomy)
    if problems:
        raise ValueError(f"labels.yaml taxonomy inconsistent ({source}): " + "; ".join(problems))
    return taxonomy


def load_taxonomy_text(text: str, source: str = "<text>") -> dict:
    """文本 → (解析 → 形状收口 → SC-9 校验后的) taxonomy dict。任何失败抛
    ValueError。返回副本内含 ``_meta`` (layer/source, 供报告溯源; 不入
    taxonomy_hash)。"""
    try:
        raw = _parse_simple_yaml(text)
    except SimpleYamlError as exc:
        raise ValueError(f"labels.yaml parse error ({source}): {exc}") from exc
    taxonomy = _validated(parse_taxonomy(raw), source)
    out = dict(taxonomy)
    out["_meta"] = {"layer": None, "source": source}
    return out


def load_taxonomy_file(path: str | Path) -> dict:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    tax = load_taxonomy_text(text, source=str(path))
    tax["_meta"]["layer"] = "explicit"
    return tax


def load_builtin_taxonomy() -> dict:
    """内置保守默认层 (随插件分发; 仅通用分类键 bug/feature/security/tracker)。"""
    tax = load_taxonomy_file(BUILTIN_CONFIG_PATH)
    tax["_meta"]["layer"] = "builtin"
    return tax


def resolve_taxonomy(project_root: str | Path | None = None) -> dict:
    """裁定-1 落点裁决: 项目级 ``<project_root>/.aria/labels.yaml`` 存在 →
    **整体覆盖** (整文件替换, 零字段合并); 不存在或 project_root 为 None →
    内置层。项目文件存在但非法 → ValueError (不静默回落)。

    覆盖语义由结构保证: 项目层解析产物整体替换内置层, 代码路径上不存在
    逐节回填 (merge) 的分支。
    """
    if project_root is not None:
        project_path = Path(project_root) / PROJECT_CONFIG_RELPATH
        if project_path.is_file():
            return load_taxonomy_file(project_path)  # layer 标 "explicit"
    return load_builtin_taxonomy()


def taxonomy_hash(taxonomy: dict) -> str:
    """taxonomy 内容指纹 (sha256 hex, 供 TASK-004 上下文面指纹消费)。

    canonical 形态: version + 三节按**声明顺序**的 [key, value] 对列表
    (重排声明顺序 = taxonomy 变化, 保守触发重分类); 排除 ``_meta`` (同内容
    不同来源 → 同 hash, 指纹只对内容敏感)。
    """
    payload = {
        "version": taxonomy.get("version"),
        "categories": list(taxonomy.get("categories", {}).items()),
        "title_prefixes": list(taxonomy.get("title_prefixes", {}).items()),
        "label_signals": list(taxonomy.get("label_signals", {}).items()),
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------- 档位函数

STALENESS_TIERS = ("<7d", "7-30d", "30-90d", ">90d")
ACTIVITY_TIERS = ("0", "1-2", "3-9", "10+")


def staleness_tier(age_days: int) -> str:
    """age (天) → staleness 档。分割: [0,7) / [7,30) / [30,90) / [90,∞) —
    在 N0 上两两不交、并集为 N0 (全分割); 负值由调用方钳 0。"""
    if age_days < 7:
        return "<7d"
    if age_days < 30:
        return "7-30d"
    if age_days < 90:
        return "30-90d"
    return ">90d"


def activity_tier(comments_count: int) -> str:
    """评论数 → 活跃度档。分割: (-∞,0] / [1,2] / [3,9] / [10,∞) — 在 Z 上
    两两不交、并集为 Z (全分割); 负计数归 ``0`` 档 (异常形态确定性钳位)。"""
    if comments_count <= 0:
        return "0"
    if comments_count <= 2:
        return "1-2"
    if comments_count <= 9:
        return "3-9"
    return "10+"


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_datetime(value: object, issue_index: int, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"issue[{issue_index}].{field} must be an ISO date/datetime string, got {type(value).__name__}")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _to_naive_utc(datetime.fromisoformat(raw))
    except ValueError as exc:
        raise ValueError(f"issue[{issue_index}].{field} unparseable ISO datetime: {value!r}") from exc


def _resolve_now(now: datetime | date | None) -> datetime:
    if now is None:
        # 模块 UTC 纪律兑现: 系统时钟取 UTC 再剥 tz — datetime.now() 的
        # 本地钟在非 UTC 主机上会系统性偏移 staleness 档 (比较基线是
        # naive UTC, 见 docstring 时钟 seam 段)。
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if isinstance(now, datetime):
        return _to_naive_utc(now)
    if isinstance(now, date):
        return datetime(now.year, now.month, now.day)
    raise ValueError(f"now must be datetime/date/None, got {type(now).__name__}")


# ---------------------------------------------------------------------- classify

def classify(
    issues: list[dict],
    taxonomy: dict | None = None,
    now: datetime | date | None = None,
) -> list[dict]:
    """Tier A 机械粗分 (裁定-7)。

    参数:
      issues: TASK-001 fetch 层形态 ``{repo, number, title, labels, created,
        updated, comments_count?}`` (字段语义见模块 docstring 输入契约段)。
      taxonomy: ``load_*``/``resolve_taxonomy`` 产物; None = 内置默认层。
        传入的 dict 照样过 SC-9 (防手搓 taxonomy 绕过自检)。
      now: 时钟 seam; None = 系统时钟。

    返回: 每条 issue 一个 ``{repo, number, category, signals}``; signals 顺序
    确定不变: title-prefix (taxonomy 声明序) → label (issue 上 label 序) →
    staleness → activity。
    """
    if taxonomy is None:
        taxonomy = load_builtin_taxonomy()
    _validated(taxonomy, source="classify argument")
    now_dt = _resolve_now(now)
    title_prefixes: dict = taxonomy["title_prefixes"]
    label_signals: dict = taxonomy["label_signals"]

    results: list[dict] = []
    for idx, issue in enumerate(issues):
        repo = issue.get("repo")
        number = issue.get("number")
        if repo is None or number is None:
            raise ValueError(f"issue[{idx}] missing required identity field(s): repo={repo!r} number={number!r}")
        raw_title = issue.get("title")
        if raw_title is None:
            title = ""  # 缺席 = 无信号, 不是错误 (输入契约)
        elif isinstance(raw_title, str):
            title = raw_title
        else:
            # E-4: 非 str title (int/dict/...) 显式 ValueError — 前缀匹配
            # str.startswith 对非 str 会 AttributeError 炸穿, 静默跳过更糟。
            raise ValueError(
                f"issue[{idx}].title must be a string or absent, got {type(raw_title).__name__}"
            )
        labels = issue.get("labels") or []

        signals: list[dict] = []
        for prefix, cat_key in title_prefixes.items():
            if title.startswith(prefix):
                signals.append(
                    {"source": f"title-prefix:{prefix}", "kind": "title-prefix", "value": prefix, "category": cat_key}
                )
        if not isinstance(labels, list):
            raise ValueError(f"issue[{idx}].labels must be a list, got {type(labels).__name__}")
        for label in labels:
            cat_key = label_signals.get(label)
            if cat_key is not None:
                signals.append({"source": f"label:{label}", "kind": "label", "value": label, "category": cat_key})

        if issue.get("updated") is not None:
            updated = _parse_datetime(issue["updated"], idx, "updated")
            age_days = (now_dt - updated).days
            if age_days < 0:
                age_days = 0  # 未来时间/时钟偏移异常 → 确定性钳最低龄档
            tier = staleness_tier(age_days)
            signals.append({"source": f"staleness:{tier}", "kind": "staleness", "value": tier})

        if issue.get("comments_count") is not None:
            count = issue["comments_count"]
            if isinstance(count, bool) or not isinstance(count, int):
                raise ValueError(
                    f"issue[{idx}].comments_count must be an int, got {type(count).__name__}"
                )
            tier = activity_tier(count)
            signals.append({"source": f"activity:{tier}", "kind": "activity", "value": tier})

        category_values = [s["category"] for s in signals if s["kind"] in CATEGORY_SIGNAL_KINDS]
        distinct = dict.fromkeys(category_values)  # 保序去重
        if len(distinct) == 1:
            category = next(iter(distinct))
        elif not distinct:
            category = "unknown"
        else:
            category = "conflict"

        results.append({"repo": repo, "number": number, "category": category, "signals": signals})
    return results
