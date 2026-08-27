"""
伪造 PIL 模块。

在子进程启动时注入虚拟的 PIL 模块到 sys.modules，避免加载真实的
图像处理库。用于减少进程管理器等非图像处理场景的启动开销。
"""

import sys
from types import ModuleType


_fake_pil_module = None
_fake_image_module = None


def import_fake_pil_module():
    global _fake_pil_module, _fake_image_module
    if 'PIL' in sys.modules or 'PIL.Image' in sys.modules:
        return

    fake_pil_module = ModuleType('PIL')
    fake_pil_module.Image = ModuleType('PIL.Image')
    fake_pil_module.Image.Image = type('MockPILImage', (), dict(__init__=None))
    _fake_pil_module = fake_pil_module
    _fake_image_module = fake_pil_module.Image
    sys.modules['PIL'] = fake_pil_module
    sys.modules['PIL.Image'] = fake_pil_module.Image


def remove_fake_pil_module():
    if sys.modules.get('PIL') is _fake_pil_module:
        sys.modules.pop('PIL', None)
    if sys.modules.get('PIL.Image') is _fake_image_module:
        sys.modules.pop('PIL.Image', None)
