import pytest

from inboxanchor.api.main import APPROVAL_REGISTRY, get_service
from inboxanchor.infra.database import Base, engine


@pytest.fixture(autouse=True)
def reset_state():
    get_service.cache_clear()
    APPROVAL_REGISTRY.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    get_service.cache_clear()
    APPROVAL_REGISTRY.clear()
