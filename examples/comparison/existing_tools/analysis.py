"""Same RFC arithmetic, producing metrics for an existing DVC pipeline."""
import json
from pathlib import Path
import yaml

inputs = json.loads(Path('params.json').read_text(encoding='utf-8'))
requirement = yaml.safe_load(Path('requirements/PWR001.yml').read_text(encoding='utf-8'))
total = inputs['payload_w'] + inputs['base_w']
limit = requirement['limit_w']
metrics = {'total_w':total,'limit_w':limit,'margin_w':limit-total,'criterion_passed':total<=limit}
Path('metrics.json').write_text(json.dumps(metrics,indent=2)+'\n',encoding='utf-8')
