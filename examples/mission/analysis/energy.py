"""Standalone JSON runner: integrate a constant load over the eclipse bound."""
import json
import sys

request = json.load(sys.stdin)
v = {key: value['value'] for key, value in request['inputs'].items()}
if min(v['payload'], v['bus'], v['eclipse']) < 0 or v['usable'] <= 0:
    raise ValueError('Nonnegative load and duration and positive usable energy are required')
demand = (v['payload'] + v['bus']) * v['eclipse'] / 3600
json.dump({'protocol': request['protocol'], 'invocation_id': request['invocation_id'], 'outputs': {
    'demand': {'value': demand, 'unit': 'Wh'},
    'reserve': {'value': 100 * (1 - demand / v['usable']), 'unit': 'percent'}
}}, sys.stdout)
