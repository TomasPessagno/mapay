import pytest


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Per-process caches (beliefs, /layers answers) must not leak between tests' fake databases."""
    from app.routers import layers
    from app.routing import pre_route
    pre_route.clear_belief_cache()
    layers._layers_cache.clear()
    yield
