<!-- 冻结快照 | 来源: 10CG/Aria#185 | 标题: [Archive Tracker] subprocess-decode-hardening — SUPERSEDED 归档残值备忘 (gua | 抓取时刻(UTC): 2026-09-07T14:33:26Z | 不实时抓 API -->
<!-- archive-tracker:subprocess-decode-hardening -->

# Archive tracker: subprocess-decode-hardening (SUPERSEDED-BY-SHIP) — 残值备忘

spec 于 post_spec 两轮收敛后被并发轨 **aria-plugin v1.66.2** 直接修复覆盖 (aria `de1eba5`, Closes aria-plugin#147), owner 2026-08-21 裁定归档 design-only。本 issue 承载归档残值 (owner 裁定: traps#5 当场修, 其余立案):

## 已完成 (不待办)
- ✅ traps.md #5 崩溃点措辞勘正 — aria `6e2adc8` (2026-08-21, 文档级随下次 ship)

## 备忘待办 (低优先, 无期限)
- [ ] **guard 谓词范围缺口**: `tests/test_subprocess_decode_guard.py` 只扫 `skills/**` (排除 tests/examples); `hooks/` 生产 python 不在面内 — 当前零命中 (hooks 现均为 bash), 若未来 hooks 引入 python subprocess 调用会静默逃逸守卫。修法: `_production_python_files()` 扩 `hooks/**`。
- [ ] **L4 层 4 点未统一模式** (fetch_gate.py / closeout_trigger.py / identity.py / ss collectors/_common.py:406): guard 析取谓词 (errors= 或 ValueError 族 except) 下合规, 仅剩风格不统一; 顺路清理即可, 不值独立 cycle。

## 过程记录指针
- spec 归档: `openspec/archive/2026-08-21-subprocess-decode-hardening/` (proposal.md v3.1 头含 superseded/residual_delta 机读块)
- post_spec 审计: `.aria/audit-reports/post_spec-R{1,2}-1787225614997-subprocess-decode-hardening-*` (R1 3×REVISE 9 实质点 → R2 0C → 确认轮 3/3 PASS, 2 轮收敛)
- 语料: `.aria/notes/2026-08-20-census-147.md` (AST 普查 @ aria 3b97c35 + R1 勘正附录)

> 归档 SHA 回链: 归档提交落地后追评补充
