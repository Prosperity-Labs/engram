from __future__ import annotations

from engram.hooks import loopwright_post_commit


def test_post_commit_hook_records_ab_variant(tmp_db, monkeypatch):
    wt_id = tmp_db.create_worktree("feature/hook-variant", task_description="hook test")

    monkeypatch.setenv("LOOPWRIGHT_WORKTREE_ID", str(wt_id))
    monkeypatch.setenv("LOOPWRIGHT_SESSION_ID", "sess-hook-001")
    monkeypatch.setenv("LOOPWRIGHT_AB_VARIANT", "B")

    # The hook imports SessionDB inside main(); patch the source class it imports.
    monkeypatch.setattr("engram.recall.session_db.SessionDB", lambda *a, **kw: tmp_db)
    monkeypatch.setattr(loopwright_post_commit, "get_head_sha", lambda: "deadbeef1234")
    monkeypatch.setattr(loopwright_post_commit, "get_committed_files", lambda: ["src/app.py"])
    monkeypatch.setattr(loopwright_post_commit, "get_commit_message", lambda: "test commit")

    rc = loopwright_post_commit.main()
    assert rc == 0

    latest = tmp_db.get_latest_checkpoint(wt_id)
    assert latest is not None
    assert latest["ab_variant_label"] == "B"
    assert latest["artifact_snapshot"] == ["src/app.py"]
