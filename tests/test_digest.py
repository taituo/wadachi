from wadachi.digest import digests


def ev(i, turn, type_, actor="agent", data=None, t=None, of=None):
    e = {"id": f"e_{i:016x}", "seq": i, "turn": turn, "type": type_, "actor": actor, "src": f"f1:{i}", "data": data or {}}
    if t:
        e["t"] = t
    if of is not None:
        e["of"] = f"e_{of:016x}"
    return e


def call(i, turn, kind, paths=None, t=None):
    data = {"kind": kind}
    if paths is not None:
        data["paths"] = paths
    return ev(i, turn, "tool_call", data=data, t=t)


def only_line(events):
    [(_, line)] = digests(events)
    return line


def test_counts_in_fixed_order_and_failures():
    events = [
        ev(0, 1, "prompt", "human", {"text": "héllo"}),
        call(1, 1, "shell"),
        ev(2, 1, "tool_result", "tool", {"exit_code": 0}, of=1),
        call(3, 1, "shell"),
        ev(4, 1, "tool_result", "tool", {"exit_code": 2, "status_as_recorded": "success"}, of=3),
        call(5, 1, "read"),
        call(6, 1, "mcp"),
        ev(7, 1, "error", "tool", {"code": "timeout"}, of=6),
        call(8, 1, "shell"),  # no outcome recorded: not counted as failed
    ]
    assert only_line(events) == "t1 h5 r1 s3!1 m1!1"


def test_hook_observation_counts_as_failure():
    events = [
        ev(0, 1, "prompt", "human", {"text": "x"}),
        call(1, 1, "shell"),
        ev(2, 1, "tool_result", "tool", {}, of=1),
        ev(3, 1, "observation", "hook", {"exit_code": 1}, of=1),
    ]
    assert only_line(events) == "t1 h1 s1!1"


def test_caller_prompt_and_missing_text():
    assert only_line([ev(0, 1, "prompt", "caller", {"text": "go"})]) == "t1 p2"
    assert only_line([ev(0, 1, "prompt", "human", {"text_truncated": True})]) == "t1 h?"


def test_markers_duration_and_paths():
    paths = ["a b.rs", "100%.rs", "a b.rs", "", "c.rs", "d.rs", "e.rs", "f.rs", "g.rs"]
    events = [
        ev(0, 1, "prompt", "human", {"text": "do"}, t="2026-01-01T08:00:00Z"),
        call(1, 1, "edit", paths[:4]),
        call(2, 1, "write", paths[4:]),
        call(3, 1, "read", ["ignored.rs"]),
        ev(4, 1, "steer", "human", {"text": "no"}),
        ev(5, 1, "steer", "caller", {"text": "really"}),
        ev(6, 1, "interrupt", "human"),
        ev(7, 1, "compaction", "harness", t="2026-01-01T08:04:12.9Z"),
        ev(8, 1, "usage", "harness"),
    ]
    assert only_line(events) == "t1 h2 r1 w1 e1 ^2 x c 4m12s @a%20b.rs @100%25.rs @c.rs @d.rs @e.rs +2"


def test_path_tokens_escape_every_whitespace_and_control_character():
    events = [ev(0, 1, "prompt", "human", {"text": ""}), call(1, 1, "write", ["a\rb", "x", "45s", "c d", "e\x7ff"])]
    assert only_line(events) == "t1 h0 w1 @a%0Db @x @45s @c%C2%A0d @e%7Ff"


def test_duration_forms():
    def line(end):
        return only_line([ev(0, 1, "prompt", "human", {"text": ""}, t="2026-01-01T00:00:00Z"), ev(1, 1, "usage", "harness", t=end)])

    assert line("2026-01-01T00:00:45Z") == "t1 h0 45s"
    assert line("2026-01-01T01:00:05Z") == "t1 h0 1h0m5s"
    assert line("2026-01-01T00:00:00.9Z") == "t1 h0"  # under a second
    assert line("2025-12-31T23:59:00Z") == "t1 h0"  # clock went backwards


def test_duration_is_exact_below_microseconds():
    events = [
        ev(0, 1, "prompt", "human", {"text": ""}, t="2026-01-01T00:00:00.0000005Z"),
        ev(1, 1, "usage", "harness", t="2026-01-01T00:00:01.0000001Z"),
    ]
    assert only_line(events) == "t1 h0"  # 0.9999996 s rounds down to nothing


def test_turn_zero_has_no_digest_and_turns_are_separate():
    events = [
        ev(0, 0, "manifest", "hook"),
        ev(1, 1, "prompt", "human", {"text": "a"}),
        call(2, 1, "read"),
        ev(3, 2, "prompt", "human", {"text": "bb"}),
        call(4, 2, "search"),
    ]
    assert [line for _, line in digests(events)] == ["t1 h1 r1", "t2 h2 q1"]
    assert digests(events)[1][0] == "e_0000000000000003"
