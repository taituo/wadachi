"""Constructed rollout structures. Every content value is invented (WHY: Forge)."""

import json
from pathlib import Path

import pytest

from wadachi import dumps, session_id
from wadachi.convert import base, codex
from wadachi.digest import digests
from wadachi.validate import validate_session


@pytest.fixture
def convert_rows(tmp_path, monkeypatch):
    converter = {"name": "constructed-codex-fixture", "version": "9.8.7"}
    monkeypatch.setattr(codex, "CONVERTER", converter)
    monkeypatch.setattr(codex._Session, "CONVERTER", converter)

    def convert(rows, meta=None):
        path = tmp_path / "constructed-rollout.jsonl"
        start = {"type": "session_meta", "payload": {"id": "constructed-thread", "session_id": "constructed-process",
                 "cli_version": "9.8.7", "cwd": "/home/user/project", **(meta or {})}}
        path.write_text("".join(json.dumps(r) + "\n" for r in [start, *rows]), encoding="utf-8")
        inp = base.SessionInput([base.Source("f1", path, "record", "constructed-codex-jsonl")],
                                header={"x": {"fixture": {"constructed": True}}})
        lines = base.convert(codex, inp)
        out = base.write_session(lines, tmp_path / "store")
        assert validate_session(out).problems == []
        assert lines == base.convert(codex, inp)
        return lines

    return convert


def row(typ, payload, **extra):
    return {"type": typ, "payload": payload, **extra}


def item(typ, rid="constructed-item", **fields):
    return row("event_msg", {"type": "item_completed", "turn_id": "constructed-turn",
                            "item": {"type": typ, "id": rid, **fields}})


def response(typ, rid="constructed-response", **fields):
    return row("response_item", {"type": typ, "id": rid, **fields})


def user(rid="constructed-user", text="Invented prompt.", turn="constructed-turn"):
    record = item("UserMessage", rid, content=[{"type": "text", "text": text, "text_elements": []}])
    record["payload"]["turn_id"] = turn
    return record


def input_message(rid, turn, kind="user.text", text="Invented input."):
    return response("message", rid, role="user", content=[{"type": "input_text", "text": text}],
                    internal_chat_message_metadata_passthrough={"turn_id": turn, "content_item_kinds": [kind]})


@pytest.mark.usefixtures("convert_rows")
def test_constructed_goal_continuation_matches_expected_output(tmp_path):
    root = Path(__file__).parent / "fixtures" / "codex"
    fixture = root / "goal-continuation.constructed.jsonl"
    inp = base.SessionInput([base.Source("f1", fixture, "record", "constructed-codex-jsonl")],
                            header={"x": {"fixture": {"constructed": True}}})
    lines = base.convert(codex, inp)
    assert validate_session(base.write_session(lines, tmp_path / "store")).problems == []
    # Only the machine-dependent provenance path differs in the golden output.
    lines[0]["files"]["f1"]["path"] = "/home/user/constructed-goal-continuation.jsonl"
    assert "".join(dumps(r) + "\n" for r in lines) == (root / "goal-continuation.expected.jsonl").read_text()
    events = lines[1:]
    assert [(e["type"], e["actor"]) for e in events] == [
        ("prompt", "caller"), ("reasoning", "agent"), ("tool_call", "agent"),
        ("usage", "harness"), ("tool_result", "tool"), ("steer", "human"),
        ("assistant_text", "agent"), ("usage", "harness")]
    assert {e["turn"] for e in events} == {1}
    assert events[0]["how"] == {"type": "inferred:goal-context-input", "actor": "inferred:goal-context-input"}
    assert [e["data"]["input_tokens"] for e in events if e["type"] == "usage"] == [17, 19]
    assert list(digests(events))[0][1].endswith("^1 5m4s")


def test_constructed_harness_task_ids_match_output_turns(convert_rows):
    rows = []
    expected = {"constructed-normal": 1, "constructed-queued": 2, "constructed-goal": 3,
                "constructed-after-abort": 4}

    def start(turn):
        rows.append(row("event_msg", {"type": "task_started", "turn_id": turn}))

    def usage(turn):
        rows.append(row("token_usage_record", {"turn_id": turn, "usage": {"input_tokens": 11}}))

    def end(turn, typ="task_complete"):
        rows.append(row("event_msg", {"type": typ, "turn_id": turn, "reason": "invented-reason"}))

    start("constructed-normal")
    rows += [input_message("constructed-normal-input", "constructed-normal"),
             input_message("constructed-normal-steer", "constructed-normal")]
    usage("constructed-normal")
    # A queued input with its own recorded id starts a new prompt, even while
    # the previous task remains active. It must not become that task's steer.
    rows.append(input_message("constructed-queued-input", "constructed-queued"))
    end("constructed-normal")
    start("constructed-queued")
    usage("constructed-queued")
    end("constructed-queued")
    start("constructed-goal")
    rows.append(input_message("constructed-goal-input", "constructed-goal", "goal.internal_context"))
    usage("constructed-goal")
    rows.append(input_message("constructed-goal-steer", "constructed-goal"))
    end("constructed-goal", "turn_aborted")
    start("constructed-after-abort")
    rows.append(input_message("constructed-after-abort-input", "constructed-after-abort"))
    usage("constructed-after-abort")
    end("constructed-after-abort")

    events = convert_rows(rows)[1:]
    assert [e["type"] for e in events if e["type"] in ("prompt", "steer")] == [
        "prompt", "steer", "prompt", "prompt", "steer", "prompt"]
    for event in events:
        payload = event["raw"]["payload"]
        turn_id = payload.get("turn_id") or payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id")
        assert turn_id in expected  # every mapped record in this fixture has an id
        assert event["turn"] == expected[turn_id]
    assert [e["actor"] for e in events if e["type"] == "prompt"] == ["human", "human", "caller", "human"]


@pytest.mark.parametrize("first_kind", ["user.text", "goal.internal_context"])
def test_goal_context_in_existing_turn_is_caller_steer(convert_rows, first_kind):
    lines = convert_rows([input_message("constructed-first", "constructed-turn", first_kind),
                          input_message("constructed-goal-update", "constructed-turn", "goal.internal_context")])
    assert [e["type"] for e in lines[1:]] == ["prompt", "steer"]
    assert [e["turn"] for e in lines[1:]] == [1, 1]
    assert lines[2]["actor"] == "caller"
    assert lines[2]["how"] == {"type": "inferred:shared-turn-user-message", "actor": "inferred:goal-context-input"}


def test_goal_context_does_not_replace_mixed_user_input_actor_or_text(convert_rows):
    message = input_message("constructed-mixed", "constructed-turn")
    message["payload"]["content"].insert(0, {"type": "input_text", "text": "Invented goal context."})
    message["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"].insert(0, "goal.internal_context")
    lines = convert_rows([message])
    assert lines[1]["type"] == "prompt" and lines[1]["actor"] == "human"
    assert lines[1]["data"] == {"text": "Invented input."}


def test_goal_input_uses_active_task_when_its_own_turn_id_is_missing(convert_rows):
    goal = input_message("constructed-goal", "constructed-turn", "goal.internal_context")
    del goal["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"]
    lines = convert_rows([row("event_msg", {"type": "task_started", "turn_id": "constructed-turn"}),
                          goal, user()])
    assert [(e["type"], e["turn"]) for e in lines[1:]] == [("prompt", 1), ("steer", 1)]


def test_task_start_and_abort_without_input_do_not_invent_a_prompt(convert_rows):
    lines = convert_rows([row("event_msg", {"type": "task_started", "turn_id": "constructed-aborted"}),
                          row("event_msg", {"type": "turn_aborted", "turn_id": "constructed-aborted"}),
                          input_message("constructed-fresh", "constructed-fresh-turn")])
    assert [(e["type"], e["turn"]) for e in lines[1:]] == [("interrupt", 0), ("prompt", 1)]


@pytest.mark.parametrize("end_type", ["task_complete", "turn_aborted"])
def test_closed_goal_task_is_not_reused_for_unmarked_user_input(convert_rows, end_type):
    fresh = input_message("constructed-fresh", "constructed-fresh-turn")
    del fresh["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"]
    lines = convert_rows([row("event_msg", {"type": "task_started", "turn_id": "constructed-turn"}),
                          input_message("constructed-goal", "constructed-turn", "goal.internal_context"),
                          row("event_msg", {"type": end_type, "turn_id": "constructed-turn"}), fresh])
    assert [(e["actor"], e["turn"]) for e in lines[1:] if e["type"] == "prompt"] == [("caller", 1), ("human", 2)]


def test_prompts_steers_and_queued_new_turns(convert_rows):
    lines = convert_rows([
        row("event_msg", {"type": "task_started", "turn_id": "constructed-turn"}),
        user(), user("constructed-steer", "Invented correction."),
        user("constructed-queued", "Invented next prompt.", "constructed-next-turn"),
        row("event_msg", {"type": "task_complete", "turn_id": "constructed-turn"}),
    ])
    assert [e["type"] for e in lines[1:]] == ["prompt", "steer", "prompt"]
    assert [e["turn"] for e in lines[1:]] == [1, 1, 2]
    assert lines[0]["x"]["codex"]["skipped_records"]["event_msg/task_complete"] == 1
    assert "ended_at" not in lines[0]


def test_text_missing_is_distinct_from_empty_and_image_stays_raw(convert_rows):
    lines = convert_rows([item("UserMessage", "constructed-image", content=[{"type": "local_image", "path": "/home/user/image.png"}]),
                          user("constructed-empty", "")])
    assert lines[1]["data"] == {}
    assert lines[2]["data"]["text"] == ""
    assert lines[1]["raw"]["payload"]["item"]["content"][0]["path"] == "/home/user/image.png"


def test_duplicate_response_user_and_context_are_not_extra_prompts(convert_rows):
    lines = convert_rows([
        response("message", "constructed-input", role="user", content=[{"type": "input_text", "text": "Invented prompt."}],
                 internal_chat_message_metadata_passthrough={"turn_id": "constructed-turn", "content_item_kinds": ["user.text"]}),
        response("message", "constructed-context", role="user", content=[{"type": "input_text", "text": "Invented environment."}],
                 internal_chat_message_metadata_passthrough={"content_item_kinds": ["environments.environment_context"]}),
        user(),
    ])
    assert [e["type"] for e in lines[1:]] == ["prompt", "context"]
    assert lines[2]["data"] == {"name": "environments.environment_context", "role": "user", "text": "Invented environment."}


def test_live_response_input_does_not_wait_for_a_ui_copy(convert_rows):
    lines = convert_rows([
        response("message", "constructed-first", role="user", content=[{"type": "input_text", "text": "Invented first."}],
                 internal_chat_message_metadata_passthrough={"turn_id": "constructed-turn", "content_item_kinds": ["user.text"]}),
        user(),
        response("message", "constructed-live", role="user", content=[{"type": "input_text", "text": "Invented live steer."}],
                 internal_chat_message_metadata_passthrough={"turn_id": "constructed-turn", "content_item_kinds": ["user.text"]}),
    ])
    assert [e["type"] for e in lines[1:]] == ["prompt", "steer"]
    assert lines[2]["data"]["text"] == "Invented live steer."
    assert lines[2]["how"] == {"type": "inferred:shared-turn-user-message"}


def test_user_text_is_selected_without_joining_instruction_blocks(convert_rows):
    lines = convert_rows([response("message", role="user", content=[
        {"type": "input_text", "text": "Invented environment."}, {"type": "input_text", "text": "Invented user prompt."}],
        internal_chat_message_metadata_passthrough={"turn_id": "constructed-turn",
                                                   "content_item_kinds": ["environments.environment_context", "user.text"]})])
    assert [e["type"] for e in lines[1:]] == ["context", "prompt"]
    assert lines[1]["data"]["name"] == "environments.environment_context" and lines[1]["src"].endswith("#/payload/content/0")
    assert lines[2]["data"] == {"text": "Invented user prompt."}


def test_developer_instructions_are_context(convert_rows):
    lines = convert_rows([response("message", "constructed-dev", role="developer", content=[
        {"type": "input_text", "text": "Invented instructions."}, {"type": "input_text", "text": "Invented skills."}])])
    assert [(e["type"], e["actor"], e["data"]) for e in lines[1:]] == [
        ("context", "harness", {"role": "developer", "text": "Invented instructions."}),
        ("context", "harness", {"role": "developer", "text": "Invented skills."})]
    assert "skipped_records" not in lines[0].get("x", {}).get("codex", {})


def test_old_response_prompt_and_headless_actor(convert_rows):
    lines = convert_rows([response("message", role="user", content=[{"type": "input_text", "text": "Invented headless prompt."}])],
                         {"source": "exec", "timestamp": "2031-02-03T12:00:00+02:00"})
    assert lines[0]["mode"] == "headless"
    assert lines[0]["started_at"] == "2031-02-03T10:00:00Z"
    assert lines[1]["actor"] == "caller" and "t" not in lines[1]


def test_each_block_has_its_pointer_and_duplicate_ui_message_is_skipped(convert_rows):
    lines = convert_rows([
        response("message", "constructed-message", role="assistant", content=[{"type": "output_text", "text": "Invented first."},
                                                                                 {"type": "output_text", "text": "Invented second."}]),
        item("AgentMessage", "constructed-message", content=[{"type": "Text", "text": "Invented first."}]),
        item("AgentMessage", "constructed-async", content=[{"type": "Text", "text": "Invented async."}], delivery="async"),
    ])
    assert [e["data"]["text"] for e in lines[1:]] == ["Invented first.", "Invented second.", "Invented async."]
    assert len({e["src"] for e in lines[1:]}) == 3
    assert lines[1]["src"].endswith("#/payload/content/0")
    assert lines[2]["src"].endswith("#/payload/content/1")


def test_arguments_stay_strings_results_link_and_time_never_carries(convert_rows):
    args = '{"paths": ["/home/user/a", "/home/user/b"], "value": 2}'
    lines = convert_rows([
        response("function_call", "constructed-call-record", call_id="constructed-call", name="invented_tool", arguments=args),
        response("function_call_output", "constructed-result-record", call_id="constructed-call", output=[{"type": "input_text", "text": "Invented result."}]),
        response("custom_tool_call", "constructed-custom-record", call_id="constructed-custom", name="exec", input="invented_code()"),
        response("custom_tool_call_output", "constructed-custom-result", call_id="constructed-custom", output=""),
    ])
    assert lines[1]["data"] == {"tool": "invented_tool", "kind": "other", "args": args, "call_id": "constructed-call"}
    assert "paths" not in lines[1]["data"]
    assert lines[2]["of"] == lines[1]["id"] and lines[2]["data"]["text"] == "Invented result."
    assert lines[3]["data"]["kind"] == "other" and lines[3]["data"]["args"] == "invented_code()"
    assert lines[4]["of"] == lines[3]["id"] and lines[4]["data"]["text"] == ""
    assert all("t" not in e for e in lines[1:])


def test_mcp_prefix_and_missing_tool_fields(convert_rows):
    lines = convert_rows([response("function_call", "constructed-mcp", name="mcp__invented__read", arguments="{}"),
                          response("function_call", "constructed-missing")])
    assert lines[1]["data"]["kind"] == "mcp"
    assert lines[2]["data"] == {"kind": "other"}


def test_shell_failure_and_duration_come_from_their_own_source(convert_rows):
    lines = convert_rows([
        item("CommandExecution", command=["sh", "-c", "invented command"], cwd="/home/user/project", status="success",
             exit_code=7, duration={"secs": 2, "nanos": 3000000}, aggregated_output="Invented failure.", stdout="", stderr="Invented stderr."),
    ])
    event = lines[1]
    assert event["data"] == {"kind": "shell", "status_as_recorded": "success", "exit_code": 7, "text": "Invented failure."}
    assert event["raw"]["payload"]["item"]["duration"] == {"secs": 2, "nanos": 3000000}
    assert "of" not in event and "tool" not in event["data"] and "paths" not in event["data"]


def test_noninteger_exit_and_status_are_not_coerced(convert_rows):
    lines = convert_rows([item("CommandExecution", status=True, exit_code=1.5, aggregated_output="Invented output.")])
    assert "exit_code" not in lines[1]["data"]
    assert lines[1]["data"]["status_as_recorded"] == "true"
    assert lines[1]["raw"]["payload"]["item"]["exit_code"] == 1.5


def test_all_changed_paths_stay_in_order(convert_rows):
    changes = {"/home/user/z.py": {"type": "update", "unified_diff": "Invented diff."},
               "/home/user/a.py": {"type": "add", "content": "Invented code."}}
    lines = convert_rows([item("FileChange", changes=changes, status="completed"),
                          item("ImageView", "constructed-image", path="/home/user/image.png")])
    assert lines[1]["data"]["paths"] == list(changes)
    assert lines[1]["data"]["kind"] == "edit"
    assert lines[2]["data"]["paths"] == ["/home/user/image.png"]


def test_mcp_and_extension_results(convert_rows):
    lines = convert_rows([
        item("McpToolCall", "constructed-mcp", tool="invented_read", server="invented_server", status="failed",
             arguments={"paths": ["/home/user/a", "/home/user/b"]}, result={"content": [{"type": "text", "text": "Invented response."}]}),
        response("function_call", "constructed-sleep-call", call_id="constructed-clock", name="sleep", namespace="clock", arguments='{"duration_ms":4}'),
        item("Extension", "constructed-clock", kind="clock.sleep", action={}, results=[]),
        item("Extension", "constructed-web", kind="web.search", action={"type": "search", "query": "Invented query."}, results=[]),
    ])
    assert lines[1]["data"]["kind"] == "mcp"
    assert lines[3]["of"] == lines[2]["id"]
    assert lines[3]["how"] == {"of": "inferred:item-id-matches-call"}
    assert lines[4]["data"]["kind"] == "fetch"


def test_compaction_does_not_replay_replacement_history(convert_rows):
    replacement = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Invented earlier prompt."}]}]
    lines = convert_rows([row("compacted", {"message": "Invented model summary.", "replacement_history": replacement}),
                          item("ContextCompaction"), row("event_msg", {"type": "context_compacted", "message": "Invented old summary."})])
    assert [e["type"] for e in lines[1:]] == ["compaction"] * 3
    assert [e["turn"] for e in lines[1:]] == [0, 0, 0]
    assert lines[1]["data"]["text"] == "Invented model summary."
    assert lines[1]["raw"]["payload"]["replacement_history"] == replacement


def test_reasoning_opaque_summary_and_duplicate_ui_view(convert_rows):
    lines = convert_rows([
        response("reasoning", "constructed-opaque", encrypted_content="invented-opaque", summary=[]),
        item("Reasoning", "constructed-opaque", summary_text=[], raw_content=[]),
        response("reasoning", "constructed-summary", summary=[{"type": "summary_text", "text": "Invented summary."}]),
    ])
    assert len(lines) == 3
    assert lines[1]["data"]["redacted"] is True
    assert lines[2]["data"]["text"] == "Invented summary."


def test_usage_preserves_totals_and_ignores_noninteger_counts(convert_rows):
    usage = {"input_tokens": 13, "output_tokens": 5, "cached_input_tokens": 3, "cache_write_input_tokens": 2,
             "reasoning_output_tokens": 1, "total_tokens": 18}
    lines = convert_rows([
        row("token_usage_record", {"usage": usage, "thread_token_usage": {"input_tokens": 99}}),
        row("event_msg", {"type": "token_count", "info": {"last_token_usage": usage, "total_token_usage": {"input_tokens": 101}}}),
        row("event_msg", {"type": "token_count", "info": None}),
        row("token_usage_record", {"usage": {"input_tokens": 2.5, "output_tokens": 10**19}}),
    ])
    assert lines[1]["data"] == lines[2]["data"] == {"input_tokens": 13, "output_tokens": 5, "cache_read_tokens": 3, "cache_write_tokens": 2}
    assert lines[3]["data"] == lines[4]["data"] == {}
    assert lines[4]["raw"]["payload"]["usage"]["output_tokens"] == str(10**19)


@pytest.mark.parametrize("record", [
    row("turn_context", {"model": "invented-model", "cwd": "/home/user/project", "effort": "invented-effort"}),
    row("world_state", {"full": True, "state": {"model": "invented-model"}}),
    row("event_msg", {"type": "thread_settings_applied", "thread_settings": {"model": "invented-model", "reasoning_effort": "invented-effort"}}),
    response("configuration_update", reasoning={"effort": "invented-effort"}),
    response("additional_tools", role="system", tools=[{"name": "invented_tool"}]),
])
def test_setting_sources_keep_unmapped_values(convert_rows, record):
    lines = convert_rows([record])
    assert lines[1]["type"] == "setting" and lines[1]["raw"]["payload"] == record["payload"]


def test_interrupt_not_session_end_and_unknown_types_counted(convert_rows):
    lines = convert_rows([row("event_msg", {"type": "turn_aborted", "reason": "invented-reason"}),
                          row("ghost_snapshot", {"id": "constructed-tree"}),
                          row("event_msg", {"type": "thread_goal_updated", "goal": {"objective": "Invented goal."}}),
                          row("constructed_future_record", {"value": "Invented value."})])
    assert len(lines) == 2 and lines[1]["type"] == "interrupt"
    skipped = lines[0]["x"]["codex"]["skipped_records"]
    assert skipped == {"ghost_snapshot": 1, "event_msg/thread_goal_updated": 1, "constructed_future_record": 1}


def test_times_are_per_record_and_invalid_unicode_is_cleaned(convert_rows):
    lines = convert_rows([
        row("turn_context", {"model": "invented-model"}, timestamp="2031-02-03T12:00:00.100+02:00"),
        row("turn_context", {}, timestamp="2031-02-03 12:00:00"),
        response("message", role="assistant", content=[{"type": "output_text", "text": "Invented cut \ud800"}]),
    ])
    assert lines[1]["t"] == "2031-02-03T10:00:00.1Z"
    assert "t" not in lines[2] and lines[2]["raw"]["timestamp"] == "2031-02-03 12:00:00"
    assert "t" not in lines[3] and lines[3]["data"]["text"].endswith("\ufffd")


@pytest.mark.parametrize("metadata,relation", [
    ({"forked_from_id": "constructed-parent"}, "fork"),
    ({"source": {"subagent": {"thread_spawn": {"parent_thread_id": "constructed-parent", "depth": 1}}}}, "subagent"),
])
def test_unmeasured_parent_shapes_only_use_recorded_links(convert_rows, metadata, relation):
    lines = convert_rows([], metadata)
    assert lines[0]["parent"] == {"session": session_id("codex", native_id="constructed-parent"), "relation": relation}
    assert lines[0]["native_id"] == "constructed-thread"


def test_no_parent_or_mode_is_guessed_from_vscode(convert_rows):
    lines = convert_rows([], {"source": "vscode"})
    assert "mode" not in lines[0] and "parent" not in lines[0]


def test_subagent_prompt_comes_from_a_caller(convert_rows):
    lines = convert_rows([user()], {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "constructed-parent"}}}})
    assert lines[1]["actor"] == "caller"


def test_discovery_honors_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    directory = tmp_path / "sessions" / "constructed"
    directory.mkdir(parents=True)
    path = directory / "constructed.jsonl"
    path.write_text(json.dumps(row("session_meta", {"id": "constructed-id"})) + "\n" + '{"partial":')
    found = list(codex.discover())
    assert [(s.native_id, s.path, s.size) for s in found] == [("constructed-id", path, path.stat().st_size)]
    assert next(codex.sessions([])).sources[0].path == path


def test_self_id_environment_precedence(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "constructed-thread")
    monkeypatch.setenv("CODEX_SESSION_ID", "constructed-process")
    assert codex.self_id() == "constructed-thread"
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert codex.self_id() == "constructed-process"
