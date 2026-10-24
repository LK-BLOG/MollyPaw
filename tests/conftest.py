"""pytest 全局配置。

两个职责：
  1. 挂上两个仓库的 import 路径（主项目 + 中继）。
  2. **把数据目录强制隔离到临时目录** —— 这是防止"测试覆盖用户配置"
     这类事故的关键，见下方 autouse fixture。

第 2 点是被真实事故逼出来的：早先的测试直接构造 AgentCore，
而 AgentCore.save_config() 会写 `data/config.json`（dev 模式的数据目录），
于是测试夹具的假 api_key / approval_mode 把开发者的真配置覆盖了。
"""
import os
import shutil
import sys
import tempfile

import pytest

_PC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RELAY_ROOT = os.path.join(os.path.dirname(_PC_ROOT), "MollyPaw-Relay")

for path in (_PC_ROOT, _RELAY_ROOT):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

# 必须在 import agent.paths 之前设好 —— 但 conftest 是每个测试文件 import 前
# 才加载的，而 agent.paths 是运行时才读环境变量，所以这里设也来得及。
_ISOLATED = tempfile.mkdtemp(prefix="mollypaw-test-data-")
os.environ["MOLLYPAW_DATA_DIR"] = _ISOLATED


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir():
    """整个测试会话共享一个隔离数据目录。

    autouse：任何测试都不用记得加这个 fixture，也就没人能忘记。
    """
    previous = os.environ.get("MOLLYPAW_DATA_DIR")
    os.environ["MOLLYPAW_DATA_DIR"] = _ISOLATED
    yield _ISOLATED
    if previous is None:
        os.environ.pop("MOLLYPAW_DATA_DIR", None)
    else:
        os.environ["MOLLYPAW_DATA_DIR"] = previous
    shutil.rmtree(_ISOLATED, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_data_dir(isolated_data_dir):
    """每个测试前清空隔离目录，避免测试之间通过数据文件串味。"""
    for name in os.listdir(isolated_data_dir):
        if name in ("relay",):
            continue  # 中继目录里有测试自己管理的设备库
        target = os.path.join(isolated_data_dir, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            try:
                os.remove(target)
            except OSError:
                pass
    yield isolated_data_dir


def pytest_configure(config):
    """兜底断言：跑测试时数据目录绝不能落在项目里。"""
    import agent.paths as paths

    real = os.path.abspath(paths.data_dir())
    project_data = os.path.abspath(os.path.join(_PC_ROOT, "data"))
    appdata = os.path.abspath(
        os.path.join(os.environ.get("APPDATA", ""), "MollyPaw")
    )
    assert real != project_data, (
        f"测试的数据目录指向了项目 data/（{real}）—— 会覆盖用户配置，拒绝开跑"
    )
    assert real != appdata, (
        f"测试的数据目录指向了 %APPDATA%/MollyPaw（{real}）—— 会覆盖用户数据，拒绝开跑"
    )


@pytest.fixture(scope="session")
def main_module():
    """import main，但把 webview 换成假的。

    main 会 import webview，而 pywebview 在 Linux 上 **import 时**就探测
    X display，没有 display 就抛：
        Xlib.error.DisplayNameError: Bad display name
    CI 的 Ubuntu runner 就是这样挂的（setup 阶段就炸）。

    这些测试要验的是 HTTP 接口与业务逻辑，跟真窗口没关系，
    所以换掉 webview 即可（不引额外依赖，也不需要 xvfb）。
    """
    import sys
    import types

    fake = types.ModuleType("webview")
    fake.Window = object
    fake.start = lambda *a, **kw: None
    fake.create_window = lambda *a, **kw: None
    real = sys.modules.get("webview")
    sys.modules["webview"] = fake
    try:
        import main as _main
        yield _main
    finally:
        if real is not None:
            sys.modules["webview"] = real
        else:
            # 之前从没 import 过真 webview —— 必须把假模块摘掉，
            # 否则后面 test_webview_api 拿到的就是 fake.Window，
            # 报"destroy/show/restore/hide 不存在"（实际是假模块没有）。
            sys.modules.pop("webview", None)
