"""Phase 5: FTS5 search over content (trigram tokenizer + LIKE fallback).

Two layers are covered:
* HTTP: `/api/search` and `/api/posts?q=` through the real FastAPI stack;
* DB: the `content_fts` triggers stay in sync on insert / update / delete.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import db, now_iso
from app.posts import FTS_MIN_TOKEN_LENGTH, _search_clause
from tests.conftest import admin_headers, setup_site


def _create_post(client: TestClient, **overrides: object) -> dict:
    payload = {
        "title": "城市夜景",
        "content_md": "这是关于影像与光的记录。",
        "status": "published",
        **overrides,
    }
    response = client.post("/api/admin/posts", json=payload, headers=admin_headers())
    assert response.status_code == 201, response.text
    return response.json()


def _search(client: TestClient, q: str) -> dict:
    response = client.get("/api/search", params={"q": q})
    assert response.status_code == 200, (q, response.text)
    return response.json()


def _ids(items: list[dict]) -> set[int]:
    return {int(item["id"]) for item in items}


class TestSearchClause:
    """The compiled predicate chooses FTS only when the trigram can answer."""

    def test_long_chinese_term_uses_fts(self) -> None:
        clause = _search_clause("关于影像")
        assert clause.uses_fts is True
        assert clause.args[0] == '"关于影像"'
        assert "content_fts MATCH ?" in clause.sql

    def test_short_term_falls_back_to_like(self) -> None:
        clause = _search_clause("影像")
        assert len("影像") < FTS_MIN_TOKEN_LENGTH
        assert clause.uses_fts is False
        assert "p.content_md LIKE ?" in clause.sql

    def test_punctuation_is_stripped_and_tokens_are_quoted(self) -> None:
        clause = _search_clause('abc "def" *ghi* a:b')
        # 'a'/'b' tokens are 1 char, so the whole query degrades to LIKE.
        assert clause.uses_fts is False
        long_clause = _search_clause('abc "def" *ghi*')
        assert long_clause.uses_fts is True
        assert long_clause.args[0] == '"abc" "def" "ghi"'

    def test_only_punctuation_is_an_empty_query(self) -> None:
        clause = _search_clause('*** "":')
        assert clause.uses_fts is False


class TestChineseSearch:
    def test_two_character_query_matches_body_substring(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, content_md="这是关于影像与光的记录。")
        # 2 characters < trigram minimum: LIKE fallback must still find it.
        data = _search(client, "影像")
        assert created["id"] in _ids(data["articles"])

    def test_longer_query_uses_fts_and_matches_body(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, content_md="这是关于影像与光的记录。")
        data = _search(client, "关于影像")
        assert created["id"] in _ids(data["articles"])

    def test_title_substring_is_searchable(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, title="雨后的城市街道", content_md="正文。")
        assert created["id"] in _ids(_search(client, "城市街道")["articles"])

    def test_latin_substring_and_case_insensitivity(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(
            client,
            title="Night Scenery",
            content_md="A quiet street with light.",
        )
        for query in ("quiet", "street", "Scen", "SCENERY"):
            assert created["id"] in _ids(_search(client, query)["articles"]), query


class TestSearchWrites:
    def test_patch_is_reflected_immediately(self, client: TestClient) -> None:
        setup_site(client)
        # A fixed excerpt keeps the old body term out of the index after PATCH;
        # the server otherwise regenerates the excerpt only when it is sent.
        created = _create_post(client, content_md="最初的草稿文字。", excerpt="固定的摘要")
        assert created["id"] in _ids(_search(client, "草稿文字")["articles"])

        patched = client.patch(
            f"/api/admin/posts/{created['id']}",
            json={"content_md": "更新后的全新记述。"},
            headers=admin_headers(),
        )
        assert patched.status_code == 200, patched.text
        # The trigger replaced the FTS row: the old term is gone, the new one
        # is found right away.
        assert created["id"] not in _ids(_search(client, "草稿文字")["articles"])
        assert created["id"] in _ids(_search(client, "全新记述")["articles"])

    def test_delete_removes_the_document(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, title="将被删除的篇章", content_md="删除测试正文。")
        assert created["id"] in _ids(_search(client, "删除测试")["articles"])
        deleted = client.delete(f"/api/admin/posts/{created['id']}", headers=admin_headers())
        assert deleted.status_code == 200
        assert created["id"] not in _ids(_search(client, "删除测试")["articles"])


class TestSearchContract:
    def test_special_characters_never_500(self, client: TestClient) -> None:
        setup_site(client)
        _create_post(client)
        for query in (
            "***",
            '"',
            "'",
            "a AND b",
            "NEAR(",
            "-- comment",
            "%%",
            "a:b*",
            "(unbalanced",
            "   ",
            "!!",
        ):
            response = client.get("/api/search", params={"q": query})
            assert response.status_code == 200, (query, response.text)
            posts = client.get("/api/posts", params={"q": query})
            assert posts.status_code == 200, (query, posts.text)

    def test_empty_query_returns_no_results(self, client: TestClient) -> None:
        setup_site(client)
        _create_post(client)
        assert _search(client, "")["articles"] == []
        assert _search(client, "   ")["articles"] == []

    def test_posts_listing_uses_the_same_search(self, client: TestClient) -> None:
        setup_site(client)
        created = _create_post(client, content_md="影像与文字的记录。")
        listing = client.get("/api/posts", params={"q": "影像"})
        assert listing.status_code == 200
        data = listing.json()
        assert created["id"] in _ids(data["items"])
        assert data["total"] == 1

    def test_pagination_and_total_are_correct_with_fts(self, client: TestClient) -> None:
        setup_site(client)
        first = _create_post(client, title="共同关键词一", content_md="共同关键词的内容。")
        second = _create_post(client, title="共同关键词二", content_md="另一段共同关键词。")
        page = client.get("/api/posts", params={"q": "共同关键词", "per_page": 1, "page": 1}).json()
        assert page["total"] == 2
        assert page["pages"] == 2
        assert len(page["items"]) == 1
        assert page["items"][0]["id"] in {first["id"], second["id"]}

    def test_metadata_search_still_matches(self, client: TestClient) -> None:
        setup_site(client)
        project = client.post(
            "/api/admin/projects",
            json={
                "title": "作品集",
                "content_md": "项目正文。",
                "status": "published",
                "project_year": "2026",
                "project_kind": "代码",
            },
            headers=admin_headers(),
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        # Year is metadata only; the body does not contain "2026".
        assert project_id in _ids(_search(client, "2026")["projects"])

        # A 2-character tag name goes through the LIKE fallback of the body
        # predicate, but the OR-ed taxonomy clause must still find it.
        tagged = _create_post(client, title="无关键词标题", content_md="正文内容。", tags=["随笔"])
        assert tagged["id"] in _ids(_search(client, "随笔")["articles"])


class TestFtsTriggers:
    """The DB-level contract: triggers keep `content_fts` in sync."""

    @staticmethod
    def _fts_count(post_id: int) -> int:
        with db() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM content_fts WHERE post_id = ?",
                    (post_id,),
                ).fetchone()["n"]
            )

    @staticmethod
    def _fts_ids(term: str) -> set[int]:
        with db() as conn:
            rows = conn.execute(
                "SELECT post_id FROM content_fts WHERE content_fts MATCH ?",
                (f'"{term}"',),
            ).fetchall()
        return {int(row["post_id"]) for row in rows}

    def test_insert_update_delete_keep_the_index_in_sync(self, client: TestClient) -> None:
        setup_site(client)
        now = now_iso()
        with db() as conn:
            owner_id = int(conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"])
            cur = conn.execute(
                """INSERT INTO posts(type, title, slug, content_md, content_html,
                                     owner_id, created_at, updated_at)
                   VALUES ('post', '触发器标题', 'trigger-post', '触发器正文内容', '', ?, ?, ?)""",
                (owner_id, now, now),
            )
            post_id = int(cur.lastrowid)

        assert self._fts_count(post_id) == 1
        assert post_id in self._fts_ids("触发器正文")

        with db() as conn:
            conn.execute(
                "UPDATE posts SET content_md = ? WHERE id = ?",
                ("更新后的索引内容", post_id),
            )
        # The update trigger replaced the old row instead of duplicating it.
        assert self._fts_count(post_id) == 1
        assert post_id not in self._fts_ids("触发器正文")
        assert post_id in self._fts_ids("更新后的索引")

        with db() as conn:
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        assert self._fts_count(post_id) == 0

    def test_metadata_only_update_does_not_touch_the_index(self, client: TestClient) -> None:
        """`UPDATE OF` limits the update trigger to the indexed text columns."""
        setup_site(client)
        now = now_iso()
        with db() as conn:
            owner_id = int(conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"])
            cur = conn.execute(
                """INSERT INTO posts(type, title, slug, content_md, content_html,
                                     owner_id, created_at, updated_at)
                   VALUES ('post', '稳定标题', 'stable-post', '稳定正文', '', ?, ?, ?)""",
                (owner_id, now, now),
            )
            post_id = int(cur.lastrowid)
        with db() as conn:
            conn.execute("UPDATE posts SET featured = 1 WHERE id = ?", (post_id,))
        assert self._fts_count(post_id) == 1
        assert post_id in self._fts_ids("稳定正文")
