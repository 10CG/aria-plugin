# Forgejo API behavior notes (issue-groomer)

Live-verified external-API facts this skill's contract assumptions rest on.
Every call went through the house CLI wrapper (`/home/dev/.npm-global/bin/forgejo`,
internal endpoint 192.168.69.200:3000 first); exit 0 = 2xx with body on stdout,
exit 2 = HTTP error with `forgejo: HTTP <code> from <endpoint> ...` on stderr
(the exact 2xx code is therefore unobservable through wrapper policy).

- **Instance**: 10cg.local (Forgejo internal API) — **Version `11.0.16+gitea-1.22.0`** (`GET /version`)
- **Probe date**: 2026-10-19 (TASK-009, qa-engineer seat; 探测动作经主控授权)
- Re-verify: re-run the commands below verbatim; behavior is version-pinned,
  re-probe after any Forgejo upgrade.

---

## 1. Duplicate label add is a no-op (SC-5 前提实测)

**问题**: `labels.apply_payload.add` 的幂等前提 — "forgejo 对已有 label 的 add 为 no-op"
(spec proposal §3) — 是外部 API 行为断言, 须 live 实测一次, mock 不得编码 (SC-5)。

**目标**: 10CG/Aria#238 (本 spec tracker; 专用临时标签, 观察后删除还原 — 任务书授权的
fallback 探测路径)。临时标签 `probe-noop-20261019` (id 32), 探测后已从 issue 与仓库
标签表双双删除。

**命令** (verbatim, wrapper 形态):

```bash
forgejo POST /repos/10CG/Aria/labels -d '{"name":"probe-noop-20261019","color":"#5319e7","description":"TASK-009 no-op probe temp label (auto-removed after probe)"}'
forgejo POST /repos/10CG/Aria/issues/238/labels -d '{"labels":["probe-noop-20261019"]}'   # add #1 (fresh)
forgejo POST /repos/10CG/Aria/issues/238/labels -d '{"labels":["probe-noop-20261019"]}'   # add #2 (duplicate)
forgejo GET  '/repos/10CG/Aria/issues/238?type=issues'                                    # 观察 updated_at / labels
forgejo DELETE /repos/10CG/Aria/issues/238/labels/32                                      # 还原 (按 label id)
forgejo DELETE /repos/10CG/Aria/labels/32                                                 # 删除临时标签
```

**观察** (含第二轮精确分离实验 — 第一轮未在两次 add 之间拍中间态, 故重测):

| 步骤 | wrapper rc | 响应 | issue.updated_at | labels |
|---|---|---|---|---|
| create label | 0 (2xx) | label 对象 (id=32) | — | — |
| add #1 (fresh) | 0 (2xx) | `[{"id":32,"name":"probe-noop-20261019",...}]` | 2026-10-18T11:24:55Z → bumped | `[probe-noop-20261019]` ×1 |
| add #2 (duplicate) | 0 (2xx) | 同上, **恰好一次** | **不变** | `[probe-noop-20261019]` ×1 |
| 精确轮 U0 (remove 后) | 0 | — | 10:30:57Z | `[]` |
| 精确轮 U1 (fresh add) | 0 | label ×1 | 10:30:58Z (bump) | label ×1 |
| 精确轮 U2 (dup add) | 0 | label ×1 | **10:30:58Z (不变)** | label ×1 |
| remove + delete label | 0 | — | bumped (remove 所致) | `[]` / 标签表回 5 个原标签 |

**结论**:

1. `POST /repos/{o}/{r}/issues/{n}/labels {"labels":[name]}` 对 issue **已持有的 label 重复
   add = 完整 no-op**: 2xx、不报错、不产生重复、label 列表恰好一次, 连 `updated_at` 都不动
   (fresh add 会 bump `updated_at`, duplicate add 不会 — 两轮实验分离证实)。
2. add 的响应体 = issue **当前完整 label 列表** (非增量回执); 按标签 name 传参即可生效。
3. 因此差集 (`add = suggested − existing`) **不是** API 层幂等的必要条件, 但仍是应保留的
   正确做法: 每次 fresh add 都 bump `updated_at`, 全量重加会造成 tracker 时间戳污染与
   无谓通知面 — 差集最小化写放大。
4. **SC-5 纪律**: 此事实只活在本文件 (live 实测记录); 结构化测试的 mock **不得**把
   no-op 编码进断言逻辑 (防断言循环自证, spec 原文)。
5. 残留披露: 探测净副作用 = Aria#238 的 `updated_at` 前移至 2026-10-19T10:32:24Z;
   title/body/labels/comments (0 条) 均未变 — `updated_at` 非 issue 指纹分量, 无下游影响。

---

## 2. Comments 端点忽略 limit/page (SC-2 关键, 推翻 spec 前提)

**问题**: proposal §1 写 "comments 端点默认按创建序返回 (首页 = 最旧 50 条)" — 该前提
来自 limit=50 的推测, 未经实测。TASK-009 再生成命令的首次 smoke run 即在此翻车
(page=2 整页重复触发 fail-closed), 顺带钉死了真实行为。

**实验** (三组, 全部 rc=0):

1. aria-plugin#110 (3 条评论), `?limit=1` + `page=1..4`: 四次响应**完全相同**且都返回
   **全部 3 条** — `limit` 与 `page` 双双被忽略。
2. 10cg.local#12 (52 条评论, 跨 50 边界): 无参数 / `?limit=50&page=1` / `?limit=50&page=2`
   三次响应完全相同, 均为**全部 52 条** — 单响应无 50 条上限 (观测上限 ≥52, 更高未观测)。
3. Aria#233 (1 条评论), `page=2`/`page=3`: 返回**同一页内容而非空数组** — 越界页不空。

**行为表** (`GET /repos/{o}/{r}/issues/{n}/comments`, 本实例本版本):

| 维度 | 实测行为 |
|---|---|
| `limit` 参数 | 忽略 (limit=1 返回全量) |
| `page` 参数 | 忽略 (所有页返回同一全量列表; 越界不空、不报错) |
| 单响应上限 | 无 50 上限 (52 条一次性返回; 更大上界未观测) |
| 排序 | `created_at` 升序, 最旧在前 (52 条样本全序验证) |
| 编辑信号 | 真实语料 6 条评论零 edited (updated_at>created_at) — state-10 fixture 必须合成 |

**对 TASK-001 / SC-2 的指示**:

- "empty page = 终止条件" 对 comments 端点**永不触发**; 全分页 walk 若照搬 issue-list
  语义会死循环或误报。正确终止 = issue 对象 `comments` 计数字段满足 (collected >= count)
  或整页去重后零新行且计数已满足; 计数不满足 = 数据不可达 ⇒ fail-closed 报错。
- **>50-comment 截断反例 fixture 的真实形态** = "服务端忽略分页参数" 而非 "首页截断 50" —
  mock 应编码本行为 (全量返回), 且 expected-count 终止逻辑必须有负向测试
  (collected < count 时必须报错, 不得静默写半份语料)。
- 排序语义钉死: 升序最旧在前 ⇒ "取最新评论" = 全量取 `max(updated_at)`, 与 proposal
  的处置方向一致 (该结论现在有实测背书)。

---

## 3. 其他已核事实 (顺带钉死)

1. **issue-list 端点分页正常**: `/repos/{o}/{r}/issues?state=open&type=issues&limit=50&page=N`
   — page 生效 (Aria 54 条 = 50+4 两页), 越界页返回**空数组**, empty-page 终止成立。
   与 comments 端点行为**不一致**, 不可类比外推。
2. **PR 混同防御仍是双保险**: 现代 Forgejo 对真 issue 返回 `"pull_request": null`
   (Aria#238 实测), PR 才是非空对象; `type=issues` 参数 + 客户端过滤 (`pull_request`
   为非空 dict, 或 URL 含 `/pulls/`) 两者都要 (state-scanner issue_scan QA-C2 结论,
   本 instance 复核一致)。
3. **labels API 族**: 创建 `POST .../labels` (返回带 id 的对象); issue 加标
   `POST .../issues/{n}/labels` (响应 = 当前全量列表); 按标签 id 移除
   `DELETE .../issues/{n}/labels/{id}`; 删标签 `DELETE .../labels/{id}`。
4. **默认 token scope 提示**: 本机默认 FORGEJO_TOKEN 无 `read:organization`
   (`GET /orgs/10CG/repos` → 403), 逐仓 `/repos/10CG/<name>` 读写正常 — 语料再生成
   不依赖 org 级枚举 (18 仓名单内置于 `scripts/regen_corpus.py`)。

---

**语料再生成** (三份快照 live 重取, 全分页 + 本文行为适配):
`python3 aria/skills/issue-groomer/scripts/regen_corpus.py` (默认写 scratchpad, 日期=今天;
`--date 2026-10-18` 原位恢复 canonical 三件套; `--repos <names...>` 子集 smoke)。
