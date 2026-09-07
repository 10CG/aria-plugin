"""pytest 套件声明 — 本文件的存在本身就是它的功能, 不要因为"看起来是空的"而删掉。

**为什么需要它** (`10CG/aria-plugin#187`):

`aria/skills/run_all_tests.sh` 用 `is_pytest_suite()` 三分派套件, 第一条判据是
`[ -f "$1/conftest.py" ]`。本目录的 `test_archive_tracker_verify.py` 是 **pytest 风格
裸函数** (`def test_x(): assert ...`), 顶层**不 import pytest** ⇒ 没有本文件时两条判据
都不命中 ⇒ 落 `python3 -m unittest discover` 分支 ⇒ **收集到 0 个测试** ⇒ 打印
`OK (0 tests)` 且退出码 0 ⇒ 计入 pass_count。

那个绿在任何情况下都亮 (测试全红也是 `0 tests OK`, 因为它们根本没被收集) ⇒ 零信息量。

**本目录的具体后果**: `archive_tracker_verify.py` 是 openspec-archive Step 7「SHA 回链
填充」的**唯一断言宿主** —— Step 7 的填充动作本身由 AI 按自然语言指令执行, 实测 6 个
tracker issue 呈 4 种形态, 其中 `10CG/Aria#185` 被替换成一句完全不含 SHA 的话而无人发现。
若这些测试从未被 canonical runner 收集, 该宿主的回归就无人看守。

**回归判据**: 删掉本文件后, `bash aria/skills/run_all_tests.sh` 里 `openspec-archive`
那行会从 `OK (N tests)` 变回 `OK (0 tests)`。若看到 0, 说明本文件被删或 harness 判据被改。

`run_all_tests.sh` 本身「0 个测试却报 OK」的判据缺陷属 `10CG/aria-plugin#187`, 由该 issue
自己的 cycle 处理; 本文件只做本套件的最小止血。
"""
