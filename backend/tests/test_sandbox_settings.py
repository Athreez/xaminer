"""The sandbox container profile (SECURITY_AND_ACCESS.md § 7.2), checked without Docker.
The live check of the same settings on real containers is tests/sandbox (make sandbox-check)."""

import io
import tarfile

from docker.types import Mount

from workers.exec_worker.sandbox import Limits, container_settings, pack


def test_every_container_gets_the_full_profile() -> None:
    s = container_settings("img:1", ["./main"], Limits(time_ms=1000, memory_mb=128), [], None)
    assert s["network_mode"] == "none" and s["network_disabled"] is True
    assert s["read_only"] is True
    assert s["tmpfs"]["/tmp"].startswith("rw,noexec,nosuid,nodev,size=16m")
    assert s["user"] == "10001:10001" and s["privileged"] is False
    assert s["cap_drop"] == ["ALL"] and s["security_opt"] == ["no-new-privileges"]
    assert s["mem_limit"] == s["memswap_limit"] == "128m"  # no swap
    assert s["nano_cpus"] == 1_000_000_000 and s["pids_limit"] == 64
    assert {u.name: u.hard for u in s["ulimits"]} == {"fsize": 64 * 1024 * 1024, "core": 0}
    assert "runtime" not in s
    gvisor = container_settings("img:1", ["x"], Limits(1000, 128), [Mount("/work", "v")], "runsc")
    assert gvisor["runtime"] == "runsc"


def test_kill_at_twice_the_time_limit() -> None:
    assert Limits(time_ms=1500, memory_mb=64).kill_after_s == 3.0


def test_files_belong_to_the_runner_user() -> None:
    with tarfile.open(fileobj=io.BytesIO(pack({"main.py": b"print(1)"}))) as tar:
        (member,) = tar.getmembers()
    assert (member.name, member.uid, member.gid, member.mode) == ("main.py", 10001, 10001, 0o644)
