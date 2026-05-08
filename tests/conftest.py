import pytest

from inboxanchor.api.main import APPROVAL_REGISTRY, get_service
from inboxanchor.api.v1.routers.frontend import (
    FRONTEND_BLOCK_REGISTRY,
    FRONTEND_RUN_CACHE,
    FRONTEND_SERVICE_CACHE,
    STREAM_HUB,
)
from inboxanchor.infra.database import Base, engine


@pytest.fixture(autouse=True)
def reset_state():
    get_service.cache_clear()
    APPROVAL_REGISTRY.clear()
    FRONTEND_RUN_CACHE.clear()
    FRONTEND_SERVICE_CACHE.clear()
    FRONTEND_BLOCK_REGISTRY.clear()
    STREAM_HUB.last_event_at = None
    STREAM_HUB.subscribers.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    get_service.cache_clear()
    APPROVAL_REGISTRY.clear()
    FRONTEND_RUN_CACHE.clear()
    FRONTEND_SERVICE_CACHE.clear()
    FRONTEND_BLOCK_REGISTRY.clear()
    STREAM_HUB.last_event_at = None
    STREAM_HUB.subscribers.clear()
