# pre-merge gate 的实测坑 (改这段代码前先读)

> 半页。**每一条都是实测踩出来的, 没有一条能靠读代码想出来。**
> 来源: aria-plugin #137 的九轮审计 —— 那 2800 行规格里真正救过命的就是下面这些。
> 完整推导过程见 `openspec/archive/2026-08-16-premerge-gate-branch-existence/` (复盘材料, 非流程)。

## 一、`git ls-remote` 的三个反直觉行为

| # | 坑 | 后果 |
|---|---|---|
| 1 | **零命中也返 `rc=0`** | 拿退出码判「分支存不存在」⇒ 永远判存在 ⇒ 检查变摆设 |
| 2 | **`--exit-code` 无命中返 `rc=2`** | 会被 catch-all 的 `except` 误分类成「核验失败」而不是「分支不存在」 |
| 3 | **参数被当 glob** | `mast*` / `m[a]ster` / `maste?` 都会命中 `master` ⇒ 拿它做存在性判据等于放行一切近似名 |

**⇒ 判据只能落在「解析出的 ref 名列表」上做精确字符串比对** (`"refs/heads/" + branch` 是否在列表里)。
退出码只用来判「这次核验做成了没有」, ⛔ 永远不用来判「分支存不存在」。

## 二、解码与异常

| # | 坑 | 后果 |
|---|---|---|
| 4 | **`UnicodeDecodeError` 不是 `OSError` 的子类** (`issubclass(...)` = `False`) | 传 `text=True` 让 subprocess 自己解码时, 远端返回非 UTF-8 stderr ⇒ 该异常**裸抛穿过** `gate_check()`, 而 `(TimeoutExpired, FileNotFoundError, OSError)` 这个元组接不住。#147 起有 repo-wide 守卫 `tests/test_subprocess_decode_guard.py`: 新增 `text=True` 调用点若无 `errors=` 又没接 ValueError 族即红 |
| 5 | **`errors="surrogateescape"` 解码永不抛, 但会留下孤立代理码位** | 那些码位在**下游 `json.dumps` 时**才炸 `UnicodeEncodeError` —— 离现场很远, 极难定位 |

**⇒ 自己用 `capture_output=True` 取 bytes + `surrogateescape` 解码 (⛔ 不传 `text=True`), 并在出口做净化**
(`s.encode("utf-8","replace").decode("utf-8")`), 使返回值能过 `encode(strict)` / `json.dumps`。

## 三、位置与结构

| # | 坑 | 后果 |
|---|---|---|
| 6 | **核验必须在三道早退之后、path coverage 之前** | 放到覆盖评估之后 ⇒ 不存在的分支会先跑完整个覆盖评估; 误放进 `if cfg.get("path_coverage_enabled", True):` 块内 ⇒ **关掉覆盖评估的调用方连这道核验一起失去** —— 那是紧邻插入点最自然的误植位置 |
| 7 | **测试隔离必须在 mixin 一处统一打桩** | 单次 `git ls-remote` 到远端实测 **8.7 秒**, 而 28 处打桩 backend 的既有测试都会走到核验 ⇒ 不统一打桩, 套件从 1.6 秒变分钟级, 且判决随网络可达性漂移。先例见 `_ProbeCacheResetMixin` 对 `evaluate_path_coverage` 的处理 (#122) —— **照抄, ⛔ 不逐条改 28 个测试** |

## 四、两条不写代码但会咬人的

- **重试只对 timeout。** `rc != 0` / `FileNotFoundError` 是确定性失败, 重试只是白等 (最坏 60 秒)。
  重试轴复用 `ci_backends/aether.py` 的 `RETRY_BACKOFF`, ⛔ 不在本模块另造一套。
- **`main()` 里的 `remote=args.remote` 那一行是承重的。** 只加 `add_argument("--remote")` 而漏接线,
  CLI 传参会被静默忽略 —— 看起来加了参数, 其实没接上。测试必须走真实 CLI 入口才抓得到。

## 五、这道 gate 的根本形状 (为什么会有 #137)

**backend 结构上无法区分「分支不存在」与「分支没有正在跑的构建」** —— 两者都返 `InFlightStatus(runs=[])`
⇒ 都判 green。所以只要 `--main-branch` 传了一个远端上不存在的名字, 这条腿就**恒真**。
本项目主干叫 `master` 而缺省值是 `main`, 于是它恒真了很久。

⚠️ **本次修复只加固了 `gate_check()` 这一份实现。** SKILL.md §C.2.4 里那条「AI 照着敲命令」的散文流程
是**同一算法的第二份实现**, 它没有这道核验。⇒ **不得据本次修复认为 #137 已闭环。**
