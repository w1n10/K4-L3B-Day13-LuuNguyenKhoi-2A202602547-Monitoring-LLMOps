from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyObservation:
        def update(self, **kwargs: Any) -> "_DummyObservation":
            return self

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        @contextmanager
        def start_as_current_observation(self, **kwargs: Any):
            yield _DummyObservation()

        def flush(self) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


@contextmanager
def start_observation(*, name: str, as_type: str, **kwargs: Any) -> Iterator[Any]:
    """Tạo child observation (retriever/generation/...) nằm dưới observation hiện tại.

    Nếu bước bên trong raise, observation được đánh dấu ERROR để waterfall chỉ ra
    đúng span lỗi, rồi exception được raise tiếp cho caller xử lý.
    """
    with get_langfuse_client().start_as_current_observation(
        name=name, as_type=as_type, **kwargs
    ) as observation:
        try:
            yield observation
        except Exception as exc:
            observation.update(level="ERROR", status_message=type(exc).__name__)
            raise


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
