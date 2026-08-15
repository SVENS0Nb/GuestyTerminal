"""Load the pure integration modules without requiring Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PACKAGE = "custom_components.guesty_terminal"
PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "guesty_terminal"


def _load_module(name: str):
    full_name = f"{PACKAGE}.{name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PACKAGE_PATH / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(PACKAGE_PATH.parent)]
sys.modules.setdefault("custom_components", custom_components)

package = types.ModuleType(PACKAGE)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE] = package

_load_module("const")
models = _load_module("models")
