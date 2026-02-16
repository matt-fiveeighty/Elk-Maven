"""Tests for the Flask web API routes — sessions, images, optimization, status."""
from __future__ import annotations

import io
import json
import os

import pytest


class TestSessionRoutes:
    def test_create_session(self, client):
        resp = client.post("/api/sessions", json={"title": "Test Session"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["session_id"] > 0
        assert data["title"] == "Test Session"

    def test_list_sessions(self, client):
        # Create two sessions
        client.post("/api/sessions", json={"title": "Session A"})
        client.post("/api/sessions", json={"title": "Session B"})

        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["sessions"]) >= 2

    def test_get_session_messages_empty(self, client):
        create_resp = client.post("/api/sessions", json={"title": "Empty"})
        sid = create_resp.get_json()["session_id"]

        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        assert resp.get_json()["messages"] == []

    def test_delete_session(self, client):
        create_resp = client.post("/api/sessions", json={"title": "To Delete"})
        sid = create_resp.get_json()["session_id"]

        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "deleted"

    def test_rename_session(self, client):
        create_resp = client.post("/api/sessions", json={"title": "Old"})
        sid = create_resp.get_json()["session_id"]

        resp = client.patch(f"/api/sessions/{sid}", json={"title": "Renamed"})
        assert resp.status_code == 200

        # Verify by listing
        list_resp = client.get("/api/sessions")
        sessions = list_resp.get_json()["sessions"]
        session = next(s for s in sessions if s["id"] == sid)
        assert session["title"] == "Renamed"


class TestChatRoute:
    def test_chat_requires_session_and_message(self, client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    def test_chat_requires_message(self, client):
        create_resp = client.post("/api/sessions", json={"title": "Chat Test"})
        sid = create_resp.get_json()["session_id"]

        resp = client.post("/api/chat", json={"session_id": sid, "message": ""})
        assert resp.status_code == 400


class TestImageRoutes:
    def test_upload_no_file(self, client):
        resp = client.post("/api/images/upload")
        assert resp.status_code == 400

    def test_upload_invalid_extension(self, client):
        data = {"file": (io.BytesIO(b"fake data"), "test.txt")}
        resp = client.post(
            "/api/images/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_upload_valid_image(self, client, upload_dir):
        # Create a minimal valid PNG (1x1 pixel)
        import struct
        import zlib

        def create_minimal_png():
            # PNG signature
            sig = b'\x89PNG\r\n\x1a\n'
            # IHDR chunk
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            # IDAT chunk
            raw_data = zlib.compress(b'\x00\xff\x00\x00')
            idat_crc = zlib.crc32(b'IDAT' + raw_data) & 0xffffffff
            idat = struct.pack('>I', len(raw_data)) + b'IDAT' + raw_data + struct.pack('>I', idat_crc)
            # IEND chunk
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return sig + ihdr + idat + iend

        png_bytes = create_minimal_png()
        data = {"file": (io.BytesIO(png_bytes), "test.png")}
        resp = client.post(
            "/api/images/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["image_id"] > 0
        assert result["filename"] == "test.png"
        assert "/api/images/" in result["url"]

    def test_get_image_not_found(self, client):
        resp = client.get("/api/images/9999")
        assert resp.status_code == 404

    def test_markup_not_found(self, client):
        resp = client.get("/api/images/9999/markup")
        assert resp.status_code == 404

    def test_save_markup_not_found(self, client):
        resp = client.put(
            "/api/images/9999/markup",
            json={"markup_data": {"annotations": []}},
        )
        assert resp.status_code == 404

    def test_save_description_not_found(self, client):
        resp = client.put(
            "/api/images/9999/description",
            json={"description": "Test"},
        )
        assert resp.status_code == 404


class TestOptimizationRoutes:
    def test_get_queue_empty(self, client):
        resp = client.get("/api/optimize/queue")
        assert resp.status_code == 200
        assert resp.get_json()["items"] == []

    def test_approve_item(self, client, flask_app):
        # Insert a queue item directly
        from youtube_university.web.app import get_repo
        with flask_app.app_context():
            repo = get_repo(flask_app)
            qid = repo.insert_queue_item({
                "action_type": "delete_entry",
                "severity": "destructive",
                "target_type": "knowledge_entry",
                "target_id": 1,
                "description": "Test delete",
            })

        resp = client.post(f"/api/optimize/queue/{qid}/approve")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "approved"

    def test_reject_item(self, client, flask_app):
        from youtube_university.web.app import get_repo
        with flask_app.app_context():
            repo = get_repo(flask_app)
            qid = repo.insert_queue_item({
                "action_type": "delete_entry",
                "severity": "destructive",
                "target_type": "knowledge_entry",
                "target_id": 1,
                "description": "Test delete",
            })

        resp = client.post(f"/api/optimize/queue/{qid}/reject")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "rejected"

    def test_bias_summary_empty(self, client):
        resp = client.get("/api/bias/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_flags"] == 0


class TestStatusRoute:
    def test_get_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ingestion" in data
        assert "bias" in data
        assert "optimization_queue_pending" in data


class TestIndexRoute:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Hunting Guru" in resp.data or b"html" in resp.data.lower()
