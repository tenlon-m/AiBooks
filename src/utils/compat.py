"""第三方库兼容性补丁.

本模块只放「必须在导入其他重依赖之前执行」的运行时补丁，
每个补丁都必须幂等且失败不影响启动。

背景（six + PySide6 + matplotlib 的导入崩溃）：

    matplotlib.dates -> dateutil.rrule -> `from six.moves import _thread, range`

`six` 用 ``_SixMetaPathImporter`` 动态生成 ``six.moves.*`` 伪模块，这类模块
``__spec__.origin`` 为 ``None`` 且 ``__spec__.loader`` 是 ``_SixMetaPathImporter``。
CPython 的 ``importlib._bootstrap._module_repr_from_spec`` 把
「origin 为 None 且有 loader」一律当作命名空间包处理，直接访问 ``loader._path``：

    return f'<module {name!r} (namespace) from {list(spec.loader._path)}>'

而 ``_SixMetaPathImporter`` 没有 ``_path``，于是 ``repr(module)`` 抛出
``AttributeError``。

PySide6 的 ``shibokensupport`` 会安装 import hook，对每个新导入的模块调用
``inspect.getsource()`` 判断它是否用到 PySide；``inspect.getfile()`` 在模块没有
``__file__`` 时会执行 ``raise TypeError(f'{object!r} is a built-in module')``，
格式化 ``{object!r}`` 即触发上面的 ``repr()`` → 抛出的是 ``AttributeError`` 而非
``TypeError``，不在 shiboken 的捕获范围内，最终冒泡成启动崩溃：

    AttributeError: '_SixMetaPathImporter' object has no attribute '_path'

该崩溃与是否打包无关，只取决于「PySide6 的 import hook 是否已安装」与
「six.moves.* 是否已被导入过」的先后顺序，因此在源码运行与 PyInstaller 打包后
都可能触发，且在不同机器上表现不一致。
"""
from __future__ import annotations

_SIX_FIX_DONE = False


def apply_six_namespace_fix() -> bool:
    """给 ``six._SixMetaPathImporter`` 补上 ``_path`` 属性，修复伪模块的 repr().

    补上之后 ``repr(six.moves.x)`` 正常返回，``inspect.getfile()`` 会按预期抛出
    ``TypeError``，而 ``TypeError`` 正是 PySide6 shiboken 已经捕获的异常类型。

    必须在 **PySide6 之前**（或至少在任何 ``six.moves.*`` 被导入之前）调用。

    Returns:
        bool: 是否成功应用补丁。six 未安装或已打过补丁时返回 False。
    """
    global _SIX_FIX_DONE
    if _SIX_FIX_DONE:
        return False
    try:
        import six
    except ImportError:
        return False

    importer = getattr(six, "_SixMetaPathImporter", None)
    if importer is None:
        return False

    if not hasattr(importer, "_path"):
        # 命名空间包语义下 _path 是一组搜索路径；six 的伪模块没有真实路径，置空即可
        importer._path = ()  # type: ignore[attr-defined]

    _SIX_FIX_DONE = True
    return True
