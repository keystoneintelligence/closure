"""Check the candidate cam's native solids along its solved contact path."""
import json
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'examples/pen/analysis'))
from cam_profile import CamProfile
from cam_solid import make_parts

report=json.loads((root/'examples/pen/.closure/report.json').read_text())
record=next(a['record'] for a in report['analyses'] if a['id']=='manufacturing.cad')
v={name:item['value'] for name,item in record['inputs'].items()}
v.update(full_stroke=6,phase_offset=5,release_gap=0.6,button_projection=6.5,lug_count=3)
started=time.monotonic()
parts,datum=make_parts(v,v['retracted_gap']+v['refill_length'],v['nose_length']+v['barrel_length'])
print('SOLIDS', {k:(s.isValid(),len(s.Solids()),s.Volume()) for k,s in parts.items()},flush=True)
motion=CamProfile(v).solve(clicks=2)
samples=motion['samples'][::20]+[motion['samples'][-1]]
checks=[]
for point in samples:
 rotor=parts['rotor'].rotate((0,0,0),(0,0,1),point['rotor_deg']).translate((0,0,-point['rotor_mm']))
 button=parts['button'].translate((0,0,-point['button_mm']))
 volumes={'rotor_sleeve':rotor.intersect(parts['cam_sleeve']).Volume(),
          'rotor_button':rotor.intersect(button).Volume(),
          'button_sleeve':button.intersect(parts['cam_sleeve']).Volume()}
 if max(volumes.values())>0.001:
  checks.append({'point':point,'overlaps_mm3':volumes})
print(json.dumps({'seconds':time.monotonic()-started,'sample_count':len(samples),'overlaps':checks},indent=2))
out=root/'.closure/cam-candidate'
out.mkdir(parents=True,exist_ok=True)
for name,shape in parts.items():
 shape.exportBrep(str(out/(name+'.brep')))
(out/'audit.json').write_text(json.dumps({'datum':datum,'sample_count':len(samples),'overlaps':checks,
    'solids':{k:{'valid':s.isValid(),'count':len(s.Solids()),'volume_mm3':s.Volume()} for k,s in parts.items()}},indent=2))
