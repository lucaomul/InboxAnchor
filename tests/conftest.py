import pytest

from inboxanchor.api.main import APPROVAL_REGISTRY, get_service
from inboxanchor.api.v1.routers.frontend import (
    FRONTEND_ACTIVE_RUNS,
    FRONTEND_BLOCK_REGISTRY,
    FRONTEND_FORCE_REFRESH_PROVIDERS,
    FRONTEND_PROGRESS,
    FRONTEND_PROVIDER_ERRORS,
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
    FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    FRONTEND_PROVIDER_ERRORS.clear()
    FRONTEND_PROGRESS.clear()
    FRONTEND_ACTIVE_RUNS.clear()
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
    FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    FRONTEND_PROVIDER_ERRORS.clear()
    FRONTEND_PROGRESS.clear()
    FRONTEND_ACTIVE_RUNS.clear()
    STREAM_HUB.last_event_at = None
    STREAM_HUB.subscribers.clear()
