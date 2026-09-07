"""pytest 套件声明 — 本文件的存在本身就是它的功能, 不要因为"看起来是空的"而删掉。

**为什么需要它** (aria-plugin#187, 2026-09-06 实测):

`aria/skills/run_all_tests.sh` 用 `is_pytest_suite()` 三分派套件:

    [ -f "$1/conftest.py" ] && return 0
    grep -lq '^import pytest\\|^from pytest' "$1"/test_*.py 2>/dev/null && return 0
    return 1

本目录的 `test_fetch_gate.py` 是 **pytest 风格裸函数** (`def test_x(): assert ...`),
顶层**不 import pytest**。在本文件出现之前, 两条判据都不命中 ⇒ 落
`python3 -m unittest discover` 分支 ⇒ **收集到 0 个测试** ⇒ 打印 `OK (0 tests)` 且退出码 0
⇒ 计入 pass_count。

后果 (实测): 这 11 个测试**从未被 canonical runner 跑过**, 其中包括两条审计升级来的要求 ——
`R1 I4` (upm_source_file == None null-guard) 与 **`R1 I7` (凭证不泄漏: 含 token 的失败 stderr
不得出现在 warning/message 里)**。后者是 Rule #7 secret 卫生的机器可验证守卫。

这个绿在任何情况下都亮 (测试全红也是 0 tests OK, 因为它们根本没被收集) ⇒ 零信息量的绿。

**回归判据**: 删掉本文件后, `bash aria/skills/run_all_tests.sh` 里 `phase-d-closer` 那行会从
`OK (11 tests)` 变回 `OK (0 tests)`。若看到 0, 说明本文件被删或 harness 判据被改。

`run_all_tests.sh` 本身「0 个测试却报 OK」的判据缺陷属 aria-plugin#187, 由该 issue 自己的
cycle 处理; 本文件只做最小止血。
"""
