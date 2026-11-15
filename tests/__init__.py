"""测试包初始化：在 unittest 下也安装 conftest 中的存储句柄清理钩子。

上游把长连接释放与临时目录容错写在 ``conftest.py`` 里，只有 pytest 会自动加载；
CI 与本地都用 unittest 运行，未加载时 Windows 上未关闭的总库句柄会让用例清理
临时目录报 WinError 32。``python -m unittest tests.xxx`` 导入本包时即加载；
``discover -s tests`` 以顶层模块名导入用例，但会在运行前加载全部模块，
其中 ``from tests.xxx import`` 的用例会触发本包，钩子同样先于任何用例生效。

CI 的「校验前端锁文件下载源」在安装依赖前用裸 Python 运行不碰存储的用例；
缺少第三方依赖（如 ``rich``）时跳过钩子，缺少仓库自身模块仍照常报错。
"""
try:
    from tests import conftest as _conftest  # noqa: F401
except ModuleNotFoundError as error:
    if (error.name or '').split('.')[0] in {'module', 'tests'}:
        raise
