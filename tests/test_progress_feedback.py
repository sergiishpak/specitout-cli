from __future__ import annotations

import contextlib
import io
import threading
from unittest.mock import patch

import pytest

from specitout.progress import timed_reporter
from specitout import backend_index


def test_heartbeat_reports_waiting_on_stderr_and_stops_on_error():
    out, err = io.StringIO(), io.StringIO()
    heartbeat_seen = threading.Event()

    class Capture(io.StringIO):
        def write(self, value):
            result = super().write(value)
            if "still processing" in value:
                heartbeat_seen.set()
            return result

    err = Capture()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(RuntimeError, match="interrupted"):
            with timed_reporter("import add", heartbeat_seconds=0.01) as report:
                report("context_pack.extract_edges", 0, 0, "extracting graph edges; unit=items count=unknown")
                assert heartbeat_seen.wait(1)
                raise RuntimeError("interrupted")
        thread = report._thread
        assert thread is not None and not thread.is_alive()
        before = err.getvalue()
        report.close()
        assert err.getvalue() == before
    assert out.getvalue() == ""
    assert "elapsed=" in err.getvalue()
    assert "count=unknown" in err.getvalue()
    assert "0/0" not in err.getvalue()


def test_document_progress_counts_batches_but_committed_only_after_connection_exit():
    from specitout.progress import progress_scope
    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, args):
            events.append(("sql", sql))

    class Connection:
        def __enter__(self):
            return self

        def cursor(self):
            return Cursor()

        def __exit__(self, *args):
            events.append(("commit", "started"))
            assert not any(item[-1].startswith("committed") for item in events if item[0] == "progress")
            return False

    documents = [{"id": str(i), "export_id": "export", "document_key": str(i)} for i in range(3)]
    with patch.object(backend_index, "SEARCH_DOCUMENT_BATCH_SIZE", 2), patch.object(backend_index, "_jsonb", lambda v: v):
        with progress_scope(lambda *args: events.append(("progress", *args))):
            backend_index.replace_search_documents(connect=Connection, export_id="export", documents=documents, associations=[])
    messages = [item[-1] for item in events if item[0] == "progress"]
    assert any("2/3 documents" in message and "uncommitted" in message for message in messages)
    assert any("3/3 documents" in message and "uncommitted" in message for message in messages)
    assert "waiting" in messages[-2] and "commit" in messages[-2]
    assert "committed" in messages[-1]
    assert events.index(("commit", "started")) < len(events) - 1


def test_commit_failure_never_reports_committed():
    from specitout.progress import progress_scope
    events = []

    class Connection:
        def __enter__(self):
            return self

        def cursor(self):
            return contextlib.nullcontext(self)

        def execute(self, *args):
            pass

        def __exit__(self, *args):
            raise RuntimeError("constraint validation failed")

    with progress_scope(lambda *args: events.append(args)):
        with pytest.raises(RuntimeError, match="constraint"):
            backend_index.replace_search_documents(connect=Connection, export_id="export", documents=[], associations=[])
    assert not any(event[-1].startswith("committed") for event in events)


def test_resume_verified_ready_is_noop_and_uses_pinned_scope():
    from specitout.index_resume import resume_index
    class Backend:
        def import_status(self, **scope):
            assert scope == {"app_slug": "demo", "version_label": "v1"}
            return {"scope": scope, "data": {"export": {"version_label": "v1", "readiness_status": "ready"}, "embedding_stats": {"embedded_documents": 7, "remaining_documents": 0, "total_documents": 7}}}
        def rebuild_index(self, **kwargs):
            pytest.fail("ready resume must not rebuild or reset embeddings")
    messages = []
    result = resume_index(Backend(), app_slug="demo", version_label="v1", initial_limit=2, min_limit=1, max_passes=2, stuck_pass_threshold=2, sleep_seconds=0, emit=messages.append)
    assert result["state"] == "ready" and result["passes"] == 0
    assert result["last_result"]["stats"]["total_documents"] == 7
    assert "overall_embedded=7" in messages[-1]


def test_context_builder_reports_active_step_before_it_runs(tmp_path):
    from bubble_context_pack_internal.builder import ContextPackBuilder
    events = []
    builder = ContextPackBuilder(tmp_path / "source.json", tmp_path / "pack", tmp_path,
                                 export_loader=lambda _: {}, app_slug="demo",
                                 overlay_manager_factory=lambda _: None,
                                 progress_reporter=lambda *args: events.append(args))
    def stop_at_edges():
        assert events[-1][0] == "context_pack.extract_edges"
        assert "processing" in events[-1][-1]
        raise RuntimeError("edge failure")
    for method in ("collect_entities", "build_registries", "collect_integration_entities", "collect_application_entities", "register_virtual_nodes_from_index", "collect_synthetic_entities"):
        setattr(builder, method, lambda: None)
    builder.extract_edges = stop_at_edges
    with pytest.raises(RuntimeError, match="edge failure"):
        builder.assemble_graph()
    assert all("completed extract_edges" not in event[-1] for event in events)


def test_slow_commit_heartbeat_stays_waiting_until_commit_finishes():
    from specitout.progress import progress_scope
    observed = threading.Event()
    class Capture(io.StringIO):
        def write(self, value):
            result = super().write(value)
            if "still processing" in value and "search_document_commit" in value:
                observed.set()
            return result
    stream = Capture()
    class Connection:
        def __enter__(self):
            return self
        def cursor(self):
            return contextlib.nullcontext(self)
        def execute(self, *args):
            pass
        def __exit__(self, *args):
            assert observed.wait(1), "commit wait had no heartbeat"
            assert "committed 0 documents" not in stream.getvalue()
            return False
    with contextlib.redirect_stderr(stream), timed_reporter("index rebuild", heartbeat_seconds=0.01) as reporter:
        with progress_scope(reporter):
            backend_index.replace_search_documents(connect=Connection, export_id="export", documents=[], associations=[])
    assert "waiting for database transaction validation and commit" in stream.getvalue()
    assert "committed 0 documents" in stream.getvalue()
    assert not reporter._thread.is_alive()


def test_progress_scope_is_reset_on_error():
    from specitout.progress import progress_scope, report_active
    events = []
    with pytest.raises(ValueError):
        with progress_scope(lambda *args: events.append(args)):
            report_active("active", 1, 1, "inside")
            raise ValueError("failed")
    report_active("inactive", 1, 1, "outside")
    assert len(events) == 1


def test_graph_write_batches_report_only_committed_rows(monkeypatch):
    from specitout import backend_writes
    from specitout.progress import progress_scope
    events = []
    class Connection:
        def __enter__(self):
            return self
        def cursor(self):
            return contextlib.nullcontext(self)
        def execute(self, *args):
            events.append("execute")
        def __exit__(self, *args):
            events.append("commit")
    monkeypatch.setattr(backend_writes, "_MAX_QUERY_PARAMETERS", 2)
    rows = [{"id": str(i)} for i in range(3)]
    with progress_scope(lambda *args: events.append(args)):
        backend_writes.upsert_rows(connect=Connection, table="edges", rows=rows)
    completed = [event for event in events if isinstance(event, tuple) and event[-1].startswith("committed")]
    assert [event[1] for event in completed] == [2, 3]
    for event in completed:
        assert events[events.index(event) - 1] == "commit"


def test_pipeline_percent_is_explicitly_stage_position():
    from specitout.rendering import _render_pipeline_line
    from bubble_ingestion.pipeline_runs import start_pipeline_run
    class Backend:
        def upsert_rows(self, table, rows):
            self.row = rows[0]
    backend = Backend()
    run = start_pipeline_run(backend, app_id="app", export_id="export", pipeline_kind="demo", stage_names=["graph", "load"])
    assert run["summary_json"]["progress_basis"] == "stages"
    rendered = _render_pipeline_line({**run, "stage_index": 1, "stage_count": 2, "progress_percent": 50})
    assert "stage_position=1/2" in rendered
    assert "stage_progress=50%" in rendered
    assert " progress=50%" not in rendered


def test_resume_inconsistent_ready_state_preserves_existing_vectors():
    from specitout.index_resume import resume_index
    from specitout.runtime import SpecItOutRuntimeError
    class Backend:
        def import_status(self, **scope):
            return {'data': {'export': {'version_label': 'v1', 'readiness_status': 'ready'},
                             'embedding_stats': {'total_documents': 7, 'embedded_documents': 6, 'remaining_documents': 1}}}
        def rebuild_index(self, **kwargs):
            pytest.fail('resume must not implicitly reset a ready index with inconsistent counters')
    with pytest.raises(SpecItOutRuntimeError, match='inconsistent'):
        resume_index(Backend(), app_slug='demo', version_label='v1', initial_limit=2, min_limit=1,
                     max_passes=1, stuck_pass_threshold=1, sleep_seconds=0)


@pytest.mark.parametrize("failure_stage", [None, "library", "model"])
def test_cold_embedding_library_load_has_heartbeat_and_cleans_up(monkeypatch, failure_stage):
    from specitout import embedding_provider
    from specitout.progress import timed_reporter as make_reporter
    heartbeat_seen = threading.Event()
    model_heartbeat_seen = threading.Event()
    reporters = []
    calls = []
    class Capture(io.StringIO):
        def write(self, value):
            result = super().write(value)
            if "loading_library" in value and "still processing" in value:
                heartbeat_seen.set()
            if "loading_model" in value and "still processing" in value:
                model_heartbeat_seen.set()
            return result
    out, err = io.StringIO(), Capture()
    class Model:
        def encode(self, texts, **kwargs):
            return [[1.0] for _ in texts]
    def factory(*args, **kwargs):
        assert "loading_model" in err.getvalue()
        assert model_heartbeat_seen.wait(1), "model weight initialization had no heartbeat"
        if failure_stage == "model":
            raise RuntimeError("model unavailable")
        calls.append("model")
        return Model()
    def load_library():
        assert "loading_library" in err.getvalue()
        assert heartbeat_seen.wait(1), "library initialization had no heartbeat"
        if failure_stage == "library":
            raise RuntimeError("library unavailable")
        return factory
    def short_reporter(label):
        reporter = make_reporter(label, heartbeat_seconds=0.01)
        reporters.append(reporter)
        return reporter
    monkeypatch.setattr(embedding_provider, "timed_reporter", short_reporter, raising=False)
    monkeypatch.setattr(embedding_provider, "_load_sentence_transformer_factory", load_library)
    provider = embedding_provider.SentenceTransformerEmbeddingProvider(dimensions=1)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if failure_stage is not None:
            with pytest.raises(RuntimeError, match=f"{failure_stage} unavailable"):
                provider.embed_query("synthetic")
            assert "embedding model ready" not in err.getvalue()
        else:
            assert provider.embed_query("synthetic") == [1.0]
            before = err.getvalue()
            assert provider.embed_query("second") == [1.0]
            assert before == err.getvalue(), "warm model should not start progress again"
            assert calls == ["model"]
    assert out.getvalue() == ""
    assert len(reporters) == 1
    assert reporters[0]._thread is not None and not reporters[0]._thread.is_alive()
