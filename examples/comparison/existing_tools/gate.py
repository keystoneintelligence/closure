"""Small integration glue: DVC freshness plus a numerical requirement gate."""
import json
import subprocess
import sys
from pathlib import Path

status = subprocess.run([sys.executable,'-m','dvc','status','--json'],capture_output=True,text=True,check=True)
if json.loads(status.stdout):
    print('STALE: run dvc repro before assessing the current power allocation.')
    raise SystemExit(2)
metrics = json.loads(Path('metrics.json').read_text(encoding='utf-8'))
print(f"PWR001: {metrics['total_w']} W / {metrics['limit_w']} W; margin {metrics['margin_w']} W")
raise SystemExit(0 if metrics['criterion_passed'] else 1)
