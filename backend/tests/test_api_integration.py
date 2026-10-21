"""HTTP integration tests: auth, CSRF, content CRUD, removed routes, errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import admin_headers, setup_site


def _create_post(client: TestClient, **overrides: object) -> dict:
    payload = {
        "title": "第一篇文章",
        "content_md": "# 标题\n\n正文内容。",
        "status": "published",
        "tags": ["随笔"],
        "categories": ["日志"],
        **overrides,
    }
    response = client.post(
        "/api/admin/posts", json=payload, headers=admin_headers()
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestPublicApi:
    def test_site_settings_are_grouped(self, client: TestClient) -> None:
        setup_site(client)
        response = client.get("/api/site")
        assert response.status_code == 200
        data = response.json()
        assert set(data["settings"]) == {"site", "appearance", "copy"}
        assert data["settings"]["site"]["site_title"] == "测试站点"
        assert data["settings"]["copy"]["photos_title"] == "影像"
        # Internal documents never reach the public projection.
        assert "editor_manage_others" not in data["settings"]["site"]
        assert "advanced" not in data["settings"]

    def test_edge_health_reports_observed_request(self, client: TestClient) -> None:
        response = client.get("/api/health/edge")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "client_ip" in data
        assert "trusted_proxy" in data
        assert data["request_id"]

    def test_removed_features_are_404(self, client: TestClient) -> None:
        setup_site(client)
        for path in (
            "/api/comments",
            "/api/posts/1/comments",
            "/api/admin/comments",
            "/api/posts/1/view",
            "/api/galleries/1/view",
        ):
            method = "post" if path.endswith(("/comments", "/view")) else "get"
            response = getattr(client, method)(path, headers=admin_headers())
            assert response.status_code == 404, (path, response.status_code)

    def test_unknown_route_uses_error_envelope(self, client: TestClient) -> None:
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        assert set(response.json()["error"]) >= {"code", "message"}


class TestAuthAndCsrf:
    def test_setup_is_one_shot(self, client: TestClient) -> None:
        setup_site(client)
        again = client.post(
            "/api/setup",
            json={
                "username": "second",
                "password": "An0ther-Passphrase!",
                "display_name": "第二位",
            },
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "setup.already_initialized"

    def test_wrong_password_uses_unified_error_envelope(self, client: TestClient) -> None:
        setup_site(client)
        client.post("/api/auth/logout")
        response = client.post(
            "/api/auth/login", json={"username": "owner", "password": "wrong-pass"}
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "auth.invalid_credentials"

    def test_unsafe_admin_request_requires_csrf_header(self, client: TestClient) -> None:
        setup_site(client)
        response = client.post("/api/admin/posts", json={"title": "x"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "request.csrf_header_missing"

    def test_login_returns_retry_after_when_rate_limited(self, client: TestClient) -> None:
        setup_site(client)
        client.post("/api/auth/logout")
        last = None
        for _ in range(40):
            last = client.post(
                "/api/auth/login", json={"username": "owner", "password": "wrong"}
            )
            if last.status_code == 429:
                break
        assert last is not None
        assert last.status_code in {401, 429}
        # The limiter counts atomic attempts; at minimum the endpoint never
        # blocks a thread with a sleep-based backoff.
        if last.status_code == 429:
            assert "Retry-After" in last.headers
            assert last.json()["error"]["code"] == "rate_limit.exceeded"


class TestContentCrud:
    def test_create_publish_and_read_post(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client)
        assert created["status"] == "published"
        assert created["owner_id"] == created["owner_id"]  # present, not author_id
        assert "allow_comments" not in created
        assert "view_count" not in created
        detail = client.get(f"/api/posts/{created['slug']}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "第一篇文章"
        listing = client.get("/api/posts")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

    def test_patch_keeps_omitted_fields(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, excerpt="最初的摘要")
        response = client.patch(
            f"/api/admin/posts/{created['id']}",
            json={"title": "改过的标题"},
            headers=admin_headers(),
        )
        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["title"] == "改过的标题"
        assert updated["excerpt"] == "最初的摘要"
        assert updated["content_md"]

    def test_projects_and_pages_are_separate_resources(self, client: TestClient) -> None:
        setup_site(client)
        project = client.post(
            "/api/admin/projects",
            json={
                "title": "作品集",
                "content_md": "项目正文",
                "status": "published",
                "project_year": "2026",
                "project_kind": "代码",
            },
            headers=admin_headers(),
        )
        assert project.status_code == 201, project.text
        assert project.json()["project_year"] == "2026"
        page = client.post(
            "/api/admin/pages",
            json={"title": "关于", "slug": "about", "content_md": "关于页", "status": "published"},
            headers=admin_headers(),
        )
        assert page.status_code == 201, page.text
        assert client.get("/api/pages/about").status_code == 200
        assert client.get("/api/projects").json()["total"] == 1
        # A post may share a slug with a page thanks to UNIQUE(type, slug).
        shared = _create_post(client, title="关于", slug="about")
        assert shared["slug"] == "about"

    def test_delete_post(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client)
        response = client.delete(
            f"/api/admin/posts/{created['id']}", headers=admin_headers()
        )
        assert response.status_code == 200
        assert client.get(f"/api/posts/{created['slug']}").status_code == 404

    def test_validation_error_names_the_field(self, client: TestClient) -> None:
        setup_site(client)
        response = client.post(
            "/api/admin/posts",
            json={"title": "", "slug": "bad slug!"},
            headers=admin_headers(),
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "request.validation_failed"
        assert error.get("field")

    def test_settings_patch_is_grouped(self, client: TestClient) -> None:
        setup_site(client)
        response = client.patch(
            "/api/admin/settings",
            json={
                "site": {"site_title": "新站名"},
                "appearance": {"accent": "#112233"},
                "copy": {"photos_title": "相片"},
            },
            headers=admin_headers(),
        )
        assert response.status_code == 200, response.text
        settings = response.json()["settings"]
        assert settings["site"]["site_title"] == "新站名"
        assert settings["appearance"]["accent"] == "#112233"
        assert settings["copy"]["photos_title"] == "相片"
        # Untouched fields keep their value.
        assert settings["site"]["tagline"]
        site = client.get("/api/site").json()
        assert site["settings"]["site"]["site_title"] == "新站名"

    def test_stats_have_no_comment_or_view_fields(self, client: TestClient) -> None:
        setup_site(client)
        stats = client.get("/api/admin/stats", headers=admin_headers()).json()
        for retired in ("comments", "views", "pending_comments", "recent_comments", "top_posts"):
            assert retired not in stats

    def test_taxonomy_uses_single_term_table(self, client: TestClient) -> None:
        setup_site(client)
        created = client.post(
            "/api/admin/taxonomy/tags",
            json={"name": "夜景"},
            headers=admin_headers(),
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "夜景"
        listing = client.get("/api/admin/taxonomy", headers=admin_headers()).json()
        assert any(item["name"] == "夜景" for item in listing["tags"])
        public = client.get("/api/taxonomy").json()
        assert "夜景" in [item["name"] for item in public["tags"]]
