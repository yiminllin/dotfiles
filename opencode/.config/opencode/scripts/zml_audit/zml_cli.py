from __future__ import annotations

from .backends import BackendResult as ZmlResult
from .backends import ZmlCliBackend as ZmlCli


__all__ = ["ZmlCli", "ZmlResult"]
