# 把 ../src 挂上 sys.path — 教学示例的被测代码不打包安装, pytest 收集时需能
# import calculator (aria-plugin #118: 无此文件时按 README 跑 `pytest` 收集即
# ModuleNotFoundError)。放 tests/ 而非上层目录: conftest 收集受 rootdir/confcutdir
# 影响, 与被收集测试同目录的 conftest.py 在任何调用目录下都保证加载。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
