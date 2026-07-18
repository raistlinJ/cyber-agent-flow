from durable_event_store import DurableEventStore


def test_event_store_orders_and_replays_events(tmp_path):
    store = DurableEventStore(str(tmp_path / "caf-events.sqlite3"))
    store.create_run("run-1", "running", {"model": "test"})
    store.create_prompt("a" * 32, "run-1", "Inspect target", status="running")

    first = store.append_event("run-1", "a" * 32, "status", {"message": "Calling model"})
    second = store.append_event("run-1", "a" * 32, "tool_result", {"tool": "nmap", "exit_code": 0})

    assert (first["sequence"], second["sequence"]) == (1, 2)
    assert second["prompt_id"] == "a" * 32
    assert store.events_after("run-1", after=1) == [second]


def test_event_store_tracks_prompt_terminal_state(tmp_path):
    store = DurableEventStore(str(tmp_path / "caf-events.sqlite3"))
    store.create_run("run-1", "running")
    prompt_id = "b" * 32
    store.create_prompt(prompt_id, "run-1", "Inspect target")
    store.update_prompt_status(prompt_id, "completed")

    prompt = store.get_prompt(prompt_id)
    assert prompt["status"] == "completed"
    assert prompt["completed_at"]


def test_event_store_marks_crashed_work_as_failed_on_recovery(tmp_path):
    store = DurableEventStore(str(tmp_path / "caf-events.sqlite3"))
    prompt_id = "d" * 32
    store.create_run("run-1", "running")
    store.create_prompt(prompt_id, "run-1", "Inspect target", status="running")

    store.recover_interrupted_work()

    prompt = store.get_prompt(prompt_id)
    assert prompt["status"] == "failed"
    assert "restarted" in prompt["error"]


def test_caf_replay_and_prompt_status_endpoints(monkeypatch, tmp_path):
    import app

    store = DurableEventStore(str(tmp_path / "caf-events.sqlite3"))
    store.create_run("run-1", "running")
    prompt_id = "c" * 32
    store.create_prompt(prompt_id, "run-1", "Inspect target", status="running")
    store.append_event("run-1", prompt_id, "status", {"message": "Calling model"})
    store.append_event("run-1", prompt_id, "chat_done", {"message": "Ready"})
    store.update_prompt_status(prompt_id, "completed")
    monkeypatch.setattr(app, "_event_store", store)

    client = app.app.test_client()
    replay = client.get("/api/sessions/run-1/events?after=1")
    prompt = client.get(f"/api/prompts/{prompt_id}")

    assert replay.status_code == 200
    assert replay.get_json()["events"][0]["type"] == "chat_done"
    assert replay.get_json()["next_sequence"] == 2
    assert prompt.get_json()["status"] == "completed"


def test_caf_replay_long_poll_returns_events_that_arrive_while_waiting(monkeypatch, tmp_path):
    import app
    import threading
    import time

    store = DurableEventStore(str(tmp_path / "caf-events.sqlite3"))
    store.create_run("run-1", "running")
    monkeypatch.setattr(app, "_event_store", store)

    def append_later():
        time.sleep(0.05)
        store.append_event("run-1", None, "status", {"message": "Ready"})

    worker = threading.Thread(target=append_later)
    worker.start()
    response = app.app.test_client().get("/api/sessions/run-1/events?after=0&wait=1")
    worker.join()

    assert response.status_code == 200
    assert response.get_json()["events"][0]["message"] == "Ready"


def test_caf_capabilities_advertise_durable_replay():
    import app

    response = app.app.test_client().get("/api/capabilities")

    assert response.status_code == 200
    assert response.get_json()["durable_event_replay"] is True
    assert response.get_json()["durable_event_long_poll"] is True
