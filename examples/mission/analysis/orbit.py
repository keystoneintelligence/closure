"""Synthetic SGP4 example. TEME states, fixed Sun direction, cylindrical shadow."""
import csv
import json
import math
from pathlib import Path
import sys

from sgp4.api import Satrec, WGS72, jday

request = json.load(sys.stdin)
v = {key: value['value'] for key, value in request['inputs'].items()}
if not (10 <= v['mean_motion'] <= 17 and 0 <= v['eccentricity'] <= 0.02 and 0 <= v['inclination'] <= 180):
    raise ValueError('Example supports only low-eccentricity Earth orbits at 10–17 revolutions/day')
jd, fraction = jday(2026, 10, 11, 0, 0, 0)
satellite = Satrec()
satellite.sgp4init(WGS72, 'i', 99999, jd + fraction - 2433281.5,
                   0, 0, 0, v['eccentricity'], 0, math.radians(v['inclination']),
                   0, v['mean_motion'] * 2 * math.pi / 1440, 0)
step_s, duration_s = 30, 6 * 3600
rows, longest, consecutive = [], 0, 0
min_altitude = math.inf
for seconds in range(0, duration_s + 1, step_s):
    error, position, velocity = satellite.sgp4(jd, fraction + seconds / 86400)
    if error or not all(math.isfinite(x) for x in (*position, *velocity)):
        raise ValueError(f'SGP4 state invalid at {seconds}s: error {error}')
    x, y, z = position
    # Assumed fixed +TEME-X Sun direction, parallel rays and spherical Earth.
    shadow = x < 0 and math.hypot(y, z) < satellite.radiusearthkm
    consecutive = consecutive + 1 if shadow else 0
    longest = max(longest, consecutive)
    altitude = math.sqrt(x*x + y*y + z*z) - satellite.radiusearthkm
    min_altitude = min(min_altitude, altitude)
    rows.append([seconds, *position, *velocity, int(shadow), altitude])
# Pad both edges of the longest sampled interval by one sample period.
# This bounds that interval under the assumed geometry, not all future eclipses.
padded_eclipse = (longest + 1) * step_s if longest else 0
trajectory = Path(request['output_dir']) / 'trajectory.csv'
with trajectory.open('w', newline='', encoding='utf-8') as stream:
    writer = csv.writer(stream)
    writer.writerow(['seconds_since_2026_10_11_UTC', 'x_km', 'y_km', 'z_km',
                     'vx_km_s', 'vy_km_s', 'vz_km_s', 'shadow', 'altitude_km'])
    writer.writerows(rows)
json.dump({'protocol': request['protocol'], 'invocation_id': request['invocation_id'], 'outputs': {
    'max_eclipse': {'value': padded_eclipse, 'unit': 's'},
    'min_altitude': {'value': min_altitude, 'unit': 'km'},
    'trajectory': {'path': str(trajectory), 'media_type': 'text/csv', 'qualifiers': {'frame': 'TEME'}}
}}, sys.stdout)
