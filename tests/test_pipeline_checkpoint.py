import sqlite3

from openroad_platform_scheduler import PipelineCheckpointStore


def test_pipeline_checkpoint_create_or_get_and_optimistic_revision(tmp_path):
    path = tmp_path / "pipelines.db"
    store = PipelineCheckpointStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    first = store.create_or_get(pipeline_kind="rtl", subject_id="spec-1",
                                owner_id="owner", initial_state={"status": "new"})
    again = store.create_or_get(pipeline_kind="rtl", subject_id="spec-1",
                                owner_id="owner", initial_state={"status": "different"})
    assert again["pipeline_id"] == first["pipeline_id"]
    assert again["state"] == {"status": "new"}

    saved = store.save(first["pipeline_id"], {"status": "running"},
                       expected_revision=first["revision"])
    assert saved["revision"] == 1
    assert saved["state"]["status"] == "running"

    try:
        store.save(first["pipeline_id"], {"status": "stale"}, expected_revision=0)
    except ValueError as exc:
        assert "revision conflict" in str(exc)
    else:
        raise AssertionError("stale checkpoint write must be rejected")
