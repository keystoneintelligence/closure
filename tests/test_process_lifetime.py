"""Execution limits and wrapper exit clean up real child/grandchild processes."""
import os
import signal
import time

import pytest

from closure.engine import Engine
from conftest import edit_yaml, runner


@pytest.mark.parametrize("ending", ["success", "failure", "timeout", "output_limit"])
def test_descendants_stop_before_snapshot_is_released(project_dir, ending):
    heartbeat = project_dir/"heartbeat.txt"
    child_pid = project_dir/"child.pid"
    grandchild_pid = project_dir/"grandchild.pid"
    writer = (
        "import os,time\nfrom pathlib import Path\n"
        f"Path({str(grandchild_pid)!r}).write_text(str(os.getpid()))\n"
        f"p=Path({str(heartbeat)!r})\n"
        "until=time.monotonic()+10\n"
        "while time.monotonic()<until:\n p.write_text(str(time.monotonic_ns())); time.sleep(.02)\n"
    )
    child = (
        "import os,sys,time,subprocess\nfrom pathlib import Path\n"
        f"Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
        f"subprocess.Popen([sys.executable,'-c',{writer!r}])\n"
        "time.sleep(10)\n"
    )
    body = (
        "import subprocess,time\n"
        f"subprocess.Popen([sys.executable,'-c',{child!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"while not pathlib.Path({str(heartbeat)!r}).is_file(): time.sleep(.01)\n"
    )
    if ending == "success":
        body += "print(json.dumps({'protocol':r['protocol'],'invocation_id':r['invocation_id'],'outputs':{'total':{'value':180,'unit':'W'}}}))"
    elif ending == "failure":
        body += "raise RuntimeError('intentional wrapper failure')"
    elif ending == "timeout":
        body += "time.sleep(10)"
    else:
        body += "print('x'*5000,flush=True)\ntime.sleep(10)"
    runner(project_dir, body)
    edit_yaml(project_dir/"model/power.yaml", lambda d: d["analyses"]["budget"]["run"].update(
        timeout=1 if ending == "timeout" else 5, max_output_bytes=1000))
    try:
        report = Engine(project_dir).build(trusted=True)
        assert heartbeat.is_file(), "Fixture must reach a running grandchild"
        initial = heartbeat.read_text()
        time.sleep(.15)
        assert heartbeat.read_text() == initial, "Background analysis continued after the wrapper finished"
        assert report["gate"] is (ending == "success")
        if ending != "success":
            expected = "RUN_ERROR" if ending == "failure" else "RUN_LIMIT"
            assert report["analyses"][0]["error"]["code"] == expected
            assert not (project_dir/".closure/runs").exists()
        assert not list((project_dir/".closure").glob("work-*"))
    finally:
        # If lifetime management regresses, kill this fixture's known processes.
        # The fixture also exits on its own after ten seconds.
        for path in (child_pid, grandchild_pid):
            if path.is_file():
                try:
                    os.kill(int(path.read_text()), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                except OSError as exc:
                    # Windows reports ERROR_INVALID_PARAMETER for an already
                    # terminated PID; the heartbeat/resource assertions above
                    # remain the actual process-lifetime checks.
                    if os.name != "nt" or getattr(exc, "winerror", None) != 87:
                        raise
