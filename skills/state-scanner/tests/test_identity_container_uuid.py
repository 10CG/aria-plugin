"""SC-3 — ``get_container_uuid()`` 取 uuid 字段, 不受 label 影响.

Spec: ``openspec/changes/a1-entry-claim-duplicate-work-guard`` TASK-004 (parent 2.1).

Why a dedicated accessor: ``get_container_id()`` returns ``label if label else
uuid`` (``lib/identity.py:222``), so a container whose operator set a cosmetic
label reports *that label* as its identity.  The A.1 carry-id contract
(proposal §2.1: ``<spec-slug>-<container_uuid>``) needs the uuid segment
specifically — a track-id must not change when someone edits the label line.

怎么会红 (每条用例的失败路径):
  - baseline (aria ``d69091d`` .. ``7dd0135``): ``get_container_uuid`` 不存在 ⇒
    本文件 import 即 ``ImportError`` ⇒ 全部用例红。
  - 最省事的坏实现 ``return get_container_id(home_dir)`` ⇒
    ``test_returns_uuid_field_even_when_label_is_set`` 拿到 label 而非 uuid ⇒ 红。
  - ``test_fixture_discriminates_get_container_id_delegation`` 是该夹具的区分力
    证明 (断言旧 accessor 在同一夹具上确实返回 label); 若哪天 ``get_container_id``
    改成也返回 uuid, 这条转红 —— 提示上一条已丧失区分力, 不再能抓住委派型坏实现。
  - 兜底两臂把 ``:242`` (hostname, 写不进去) 与 ``:244`` (新生成 uuid, 写得进去)
    分开钉: 只实现其中一条的实现在另一条上红。
"""
import contextlib
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from lib.identity import (  # noqa: E402
    get_container_uuid,
    get_container_id,
    _hostname,
)

_UUID = "1a2b3c4d"
_LABEL = "devbox-A1-very-long-label"


def _write_fixture(home: Path, uuid: str = _UUID, label: str = _LABEL) -> Path:
    """Write a container-id file in ``_write_container_file`` (:126-137) format."""
    path = home / ".aria" / "container-id"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Aria container identity (auto-generated 2026-09-05T00:00:00Z)\n"
        "# Edit the `label` line to add a human-readable tag"
        ' (e.g. "devbox-A" / "laptop")\n'
        f"uuid: {uuid}\n"
        f"label: {label}\n"
        "created_at: 2026-09-05T00:00:00Z\n",
        encoding="utf-8",
    )
    return path


class TestGetContainerUuid(unittest.TestCase):
    """SC-3: uuid 字段优先于 label, 且兜底路径可辨."""

    def test_returns_uuid_field_even_when_label_is_set(self):
        """SC-3 主断言: label 非空时仍返回 uuid 字段."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_fixture(home)

            self.assertEqual(get_container_uuid(home_dir=home), _UUID)

    def test_fixture_discriminates_get_container_id_delegation(self):
        """坏实现臂: 同一夹具上旧 accessor 返回 label ⇒ 夹具确有区分力.

        这条守的是上一条的**可证伪性**, 不是产品行为: 若它转红, 说明
        ``get_container_id`` 也开始返回 uuid, 委派型坏实现将不再被抓住。
        """
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_fixture(home)

            self.assertEqual(get_container_id(home_dir=home), _LABEL)
            self.assertNotEqual(_LABEL, _UUID)

    def test_empty_label_leaves_uuid_unchanged(self):
        """label 为空串时两个 accessor 一致 —— 区分力只来自 label 非空的夹具."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_fixture(home, label="")

            self.assertEqual(get_container_uuid(home_dir=home), _UUID)
            self.assertEqual(get_container_id(home_dir=home), _UUID)

    def test_generates_and_persists_new_uuid_when_file_absent(self):
        """``:244`` 臂: home 可写且无文件 ⇒ 新 8-hex uuid 且文件被创建."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / ".aria" / "container-id"
            self.assertFalse(path.exists())

            got = get_container_uuid(home_dir=home)

            self.assertRegex(got, r"^[0-9a-f]{8}$")
            self.assertTrue(path.exists(), "新生成路径必须落盘 (与 hostname 兜底可辨)")
            self.assertIn(f"uuid: {got}", path.read_text(encoding="utf-8"))
            self.assertNotEqual(got, _hostname())

    @unittest.skipIf(os.geteuid() == 0, "root 绕过 chmod, 只读夹具不成立")
    def test_falls_back_to_hostname_when_home_unwritable(self):
        """``:242`` 臂: 无文件且 home 不可写 ⇒ 返回 hostname, 且不落盘."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            os.chmod(home, 0o500)
            try:
                # 产品行为会往 stderr 打一行 WARNING (与 get_container_id 一致);
                # 吞掉它只为保持测试输出干净, 不改变被测行为。
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    got = get_container_uuid(home_dir=home)
                self.assertIn("falling back to hostname", err.getvalue())

                self.assertEqual(got, socket.gethostname())
                self.assertFalse((home / ".aria").exists())
            finally:
                os.chmod(home, 0o700)


if __name__ == "__main__":
    unittest.main()
