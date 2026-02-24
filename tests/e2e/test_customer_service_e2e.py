"""E2E tests for Customer Service session lifecycle."""

from __future__ import annotations

import asyncio


class TestCustomerServiceE2E:
    """Full lifecycle: create → chat → history → list → delete."""

    def test_full_lifecycle(self, app_client):
        """Create session → send message → get history → list → delete."""
        # 1. Create session
        res = app_client.post("/api/customer-service/sessions", json={"customer_id": "C001"})
        assert res.status_code == 200
        data = res.json()
        assert data["success"]
        session_id = data["data"]["session_id"]
        assert len(session_id) == 32  # UUID hex

        # 2. Send chat message
        res = app_client.post(
            "/api/customer-service/chat",
            json={
                "session_id": session_id,
                "message": "你好",
            },
        )
        assert res.status_code == 200
        chat_data = res.json()["data"]
        assert chat_data["reply"]
        assert chat_data["session_id"] == session_id

        # 3. Get history
        res = app_client.get(f"/api/customer-service/sessions/{session_id}/messages")
        assert res.status_code == 200
        messages = res.json()["data"]["messages"]
        assert len(messages) == 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        # 4. List sessions
        res = app_client.get("/api/customer-service/sessions")
        assert res.status_code == 200
        sessions = res.json()["data"]
        assert any(s["session_id"] == session_id for s in sessions)

        # 5. Delete session
        res = app_client.delete(f"/api/customer-service/sessions/{session_id}")
        assert res.status_code == 200
        assert res.json()["data"]["deleted"]

        # Verify deleted
        res = app_client.get(f"/api/customer-service/sessions/{session_id}/messages")
        assert res.status_code == 404

    def test_chat_without_session_returns_404(self, app_client):
        """Chat with non-existent session should return 404."""
        res = app_client.post(
            "/api/customer-service/chat",
            json={
                "session_id": "nonexistent",
                "message": "hello",
            },
        )
        assert res.status_code == 404

    def test_delete_nonexistent_session_returns_404(self, app_client):
        """Deleting a non-existent session returns 404."""
        res = app_client.delete("/api/customer-service/sessions/nonexistent")
        assert res.status_code == 404

    def test_session_list_filter_by_customer(self, app_client):
        """List sessions filtered by customer_id."""
        # Create sessions for different customers
        r1 = app_client.post("/api/customer-service/sessions", json={"customer_id": "CUST_A"})
        r2 = app_client.post("/api/customer-service/sessions", json={"customer_id": "CUST_B"})
        r3 = app_client.post("/api/customer-service/sessions", json={"customer_id": "CUST_A"})

        sid_a1 = r1.json()["data"]["session_id"]
        sid_b = r2.json()["data"]["session_id"]
        sid_a2 = r3.json()["data"]["session_id"]

        # Filter by CUST_A
        res = app_client.get("/api/customer-service/sessions?customer_id=CUST_A")
        assert res.status_code == 200
        items = res.json()["data"]
        session_ids = [s["session_id"] for s in items]
        assert sid_a1 in session_ids
        assert sid_a2 in session_ids
        assert sid_b not in session_ids

    def test_multiple_messages_in_history(self, app_client):
        """Send multiple messages and verify order in history."""
        res = app_client.post("/api/customer-service/sessions", json={})
        sid = res.json()["data"]["session_id"]

        messages = ["第一条", "第二条", "第三条"]
        for msg in messages:
            app_client.post(
                "/api/customer-service/chat",
                json={
                    "session_id": sid,
                    "message": msg,
                },
            )

        res = app_client.get(f"/api/customer-service/sessions/{sid}/messages")
        history = res.json()["data"]["messages"]
        # 3 user + 3 assistant = 6
        assert len(history) == 6
        user_msgs = [m["content"] for m in history if m["role"] == "user"]
        assert user_msgs == messages


class TestConcurrency:
    """Test distributed lock prevents race conditions."""

    def test_concurrent_chat_lock(self, app_client, fake_redis):
        """When lock is held, second request should get 429."""
        # Create session
        res = app_client.post("/api/customer-service/sessions", json={})
        sid = res.json()["data"]["session_id"]

        # Manually acquire lock
        asyncio.get_event_loop().run_until_complete(
            fake_redis.set(f"cs:session:lock:{sid}", "1", nx=True, ex=30)
        )

        # Now try to chat — should be 429
        res = app_client.post(
            "/api/customer-service/chat",
            json={
                "session_id": sid,
                "message": "test",
            },
        )
        assert res.status_code == 429


class TestSessionIsolation:
    """Two sessions should not interfere with each other."""

    def test_two_sessions_isolated(self, app_client):
        """Messages in session A should not appear in session B."""
        # Create two sessions
        ra = app_client.post("/api/customer-service/sessions", json={"customer_id": "A"})
        rb = app_client.post("/api/customer-service/sessions", json={"customer_id": "B"})
        sid_a = ra.json()["data"]["session_id"]
        sid_b = rb.json()["data"]["session_id"]

        # Chat in session A
        app_client.post(
            "/api/customer-service/chat",
            json={
                "session_id": sid_a,
                "message": "我是客户A",
            },
        )

        # Chat in session B
        app_client.post(
            "/api/customer-service/chat",
            json={
                "session_id": sid_b,
                "message": "我是客户B",
            },
        )

        # Check histories are isolated
        ha = app_client.get(f"/api/customer-service/sessions/{sid_a}/messages").json()["data"][
            "messages"
        ]
        hb = app_client.get(f"/api/customer-service/sessions/{sid_b}/messages").json()["data"][
            "messages"
        ]

        user_a = [m["content"] for m in ha if m["role"] == "user"]
        user_b = [m["content"] for m in hb if m["role"] == "user"]

        assert user_a == ["我是客户A"]
        assert user_b == ["我是客户B"]

    def test_delete_one_session_preserves_other(self, app_client):
        """Deleting session A should not affect session B."""
        ra = app_client.post("/api/customer-service/sessions", json={})
        rb = app_client.post("/api/customer-service/sessions", json={})
        sid_a = ra.json()["data"]["session_id"]
        sid_b = rb.json()["data"]["session_id"]

        app_client.post("/api/customer-service/chat", json={"session_id": sid_a, "message": "A"})
        app_client.post("/api/customer-service/chat", json={"session_id": sid_b, "message": "B"})

        # Delete A
        app_client.delete(f"/api/customer-service/sessions/{sid_a}")

        # B should still work
        res = app_client.get(f"/api/customer-service/sessions/{sid_b}/messages")
        assert res.status_code == 200
        assert len(res.json()["data"]["messages"]) == 2


class TestCreateSession:
    """Tests for session creation edge cases."""

    def test_create_session_without_body(self, app_client):
        """POST /sessions with empty body should still work."""
        res = app_client.post("/api/customer-service/sessions")
        assert res.status_code == 200
        assert res.json()["data"]["session_id"]

    def test_create_session_with_metadata(self, app_client):
        """Session with metadata should be created successfully."""
        res = app_client.post(
            "/api/customer-service/sessions",
            json={
                "customer_id": "VIP001",
                "metadata": {"channel": "wechat", "source": "ad"},
            },
        )
        assert res.status_code == 200
        assert res.json()["data"]["session_id"]
