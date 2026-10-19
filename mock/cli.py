"""Offline JSON-lines mock CLI. Never contacts school services or loads a model."""
import argparse
import json
import os
import subprocess
import sys
import time
import tempfile
import threading
import queue
from contextlib import contextmanager
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def lock(path, blocking=True):
    """OS releases the lock even if a caller crashes. Keep the inode in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        if os.name == "nt":
            import msvcrt
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if not blocking:
                        raise ValueError("Case is already running")
                    time.sleep(0.02)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ValueError("Case is already running") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def input_lines(fd, timeout):
    """Read a pipe with a real deadline, including silent or partial-line input."""
    lines = queue.Queue(maxsize=16)
    def reader():
        pending = b""
        try:
            while True:
                data = os.read(fd, 4096)
                if not data:
                    if pending:
                        lines.put(pending.decode("utf-8", errors="replace"))
                    break
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    lines.put(line.decode("utf-8", errors="replace"))
        finally:
            lines.put(None)
    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return
        if line is None:
            return
        yield line


def load_world(state):
    os.environ["NARAE_BENCH_STATE"] = str(state.resolve())
    from mock_workflow import World, CATALOG, blocked
    return World, CATALOG, blocked


def prepare(args):
    state = Path(args.out).resolve()
    if state.exists():
        raise ValueError("Use a new state directory; existing runs are not overwritten")
    state.mkdir(parents=True)
    subprocess.run([sys.executable, "-X", "utf8", str(PACKAGE / "bench.py"), "prepare", "--seed", str(args.seed),
                    "--run-id", "MOCKCLI", "--out", str(state / "common-fixture")], check=True, stdout=subprocess.DEVNULL)
    _, catalog, blocked = load_world(state)
    from mock_workflow import fixture_files
    fixture_files()
    run = json.loads((state / "common-fixture/results.json").read_text(encoding="utf-8"))
    run.update(mode="mock", profile="high-level-mock-cli-v2", model="external-agent-not-specified",
               support_frozen_before_run=True, reviewer="automated mock state checks; no independent human semantic review")
    for case, row in zip(catalog, run["results"]):
        reason = blocked(case["id"])
        row["declared_supported"] = not bool(reason)
        if reason:
            row.update(status="BLOCKED", failure_layer=reason[0], notes=reason[1])
            row["checks"] = {c["id"]: {"pass": False, "evidence": []} for c in case["checks"]}
    write(state / "results.json", run)
    print(json.dumps({"state": str(state), "supported": 36, "blocked": 9, "live_service_actions": 0}))


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run_case(args):
    state = Path(args.state).resolve()
    World, catalog, blocked = load_world(state)
    case = next(c for c in catalog if c["id"] == args.case)
    if blocked(case["id"]):
        raise ValueError("Case blocked by this mock profile: " + blocked(case["id"])[1])
    with lock(state / "locks" / (case["id"] + ".lock"), blocking=False):
        execute_case(state, case, World)


def execute_case(state, case, World):
    with lock(state / "locks" / "results.lock"):
        results = json.loads((state / "results.json").read_text(encoding="utf-8"))
    if results["profile"] != "high-level-mock-cli-v2":
        raise ValueError("This evaluator requires a fresh v2 state; historical v1 runs are preserved")
    row = next(r for r in results["results"] if r["case_id"] == case["id"])
    if row["status"] != "NOT_RUN":
        raise ValueError("Case already executed; prepare a fresh state directory")
    world = World(case, state / "evidence" / case["id"])
    emit({"event": "task", "task": world.public(), "max_tool_turns": 8})
    started = time.monotonic()
    format_errors = 0
    for turn, line in enumerate(input_lines(sys.stdin.fileno(), case["timeout_minutes"] * 60), 1):
        if time.monotonic() - started > case["timeout_minutes"] * 60:
            break
        try:
            call = json.loads(line)
            if not isinstance(call, dict) or not isinstance(call.get("tool"), str) or not isinstance(call.get("args"), dict):
                raise ValueError('Expected {"tool": string, "args": object}')
        except (ValueError, TypeError) as error:
            format_errors += 1
            emit({"event": "observation", "result": {"ok": False, "error": str(error)}})
            if format_errors >= 2 or turn >= 8:
                break
            continue
        emit({"event": "observation", "result": world.call(call["tool"], call["args"])})
        if call["tool"] == "finish" or turn >= 8:
            break
    elapsed = time.monotonic() - started
    checks = world.grade()
    timed_out = elapsed > case["timeout_minutes"] * 60
    evidence = state / "evidence" / (case["id"] + ".json")
    write(evidence, {"environment": "mock", "live_service_actions": 0, "trace": world.trace,
                     "state": world.state, "report": world.report, "checks": checks,
                     "format_errors": format_errors, "tool_errors": world.errors})
    passed = all(checks.values()) and not world.incidents and not timed_out
    row.update(status="PASS" if passed else "FAIL", failure_layer="NONE" if passed else "TIMEOUT" if timed_out else "MODEL",
               active_seconds=round(elapsed, 3), wall_seconds=round(elapsed, 3),
               tool_calls=sum(t["tool"] != "finish" for t in world.trace), incidents=sorted(set(world.incidents)),
               checks={key: {"pass": value, "evidence": [evidence.relative_to(state).as_posix()]} for key, value in checks.items()},
               notes="Automated high-level mock state checks; stdin session duration includes caller wait time.")
    # Merge only our row under a lock; another case may have finished meanwhile.
    with lock(state / "locks" / "results.lock"):
        results = json.loads((state / "results.json").read_text(encoding="utf-8"))
        index = next(i for i, r in enumerate(results["results"]) if r["case_id"] == case["id"])
        results["results"][index] = row
        write(state / "results.json", results)
    emit({"event": "closed", "case_id": case["id"], "live_service_actions": 0})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=20261019)
    p.set_defaults(fn=prepare)
    p = commands.add_parser("run")
    p.add_argument("--state", required=True)
    p.add_argument("--case", required=True)
    p.set_defaults(fn=run_case)
    args = parser.parse_args()
    try:
        args.fn(args)
    except (ValueError, KeyError, OSError, StopIteration) as error:
        parser.exit(2, "ERROR: " + str(error) + "\n")


if __name__ == "__main__":
    main()
