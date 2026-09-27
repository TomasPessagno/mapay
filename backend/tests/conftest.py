import pytest


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Per-process caches (beliefs, /layers answers) must not leak between tests' fake databases."""
    from app.briefings import builder
    from app.routers import layers
    from app.routing import pre_route
    from app.scheduling import best_time
    pre_route.clear_belief_cache()
    best_time.clear_cache()
    builder._route_cache.clear()
    layers._layers_cache.clear()
    yield
