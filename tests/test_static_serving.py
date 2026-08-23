"""Serving the built frontend.

One service serves both the API and the bundle, which is what keeps hosting
within budget. The risk in that arrangement is a catch-all route swallowing
genuine API mistakes, so that case is tested explicitly.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import WEB_DIR, app

client = TestClient(app)

# On a fresh clone the bundle has not been built yet. Skipping with a clear
# reason beats three confusing failures that suggest something is broken.
pytestmark = pytest.mark.skipif(
    not (WEB_DIR / "index.html").exists(),
    reason="frontend not built - run: cd frontend && npm ci && npm run build",
)


def test_root_serves_the_built_bundle():
    response = client.get("/")
    assert response.status_code == 200
    assert "HBA Platform" in response.text


def test_a_deep_client_route_falls_back_to_the_bundle():
    """A single-page app owns its own routing, so deep links must not 404.

    Someone opening /affiliates/12 directly, or refreshing on it, has to get
    the app rather than an error.
    """
    response = client.get("/affiliates/12")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


def test_an_unknown_api_route_still_returns_404():
    """The fallback must never swallow a genuine API mistake.

    Without this, a typo in a frontend fetch would receive the HTML shell with
    a 200, and the failure would surface much later as a confusing parse error
    instead of an obvious 404.
    """
    assert client.get("/api/does-not-exist").status_code == 404


def test_unknown_api_routes_return_json_not_html():
    response = client.get("/api/nope")
    assert "text/html" not in response.headers.get("content-type", "")


def test_real_api_routes_are_unaffected():
    assert client.get("/api/health/live").json() == {"status": "ok"}


def test_static_assets_are_served():
    index = client.get("/").text
    # Vite fingerprints the bundle, so find the reference rather than guess it.
    start = index.index("/assets/")
    asset_path = index[start : index.index('"', start)]
    response = client.get(asset_path)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
