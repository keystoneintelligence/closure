// A standard-library-only Closure runner. It never imports the Python backend.
import {readFileSync} from 'node:fs';

const request = JSON.parse(readFileSync(0, 'utf8'));
if (request.protocol !== 'closure-run/0.1' || !/^[a-f0-9]{32}$/.test(request.invocation_id)) {
  throw Error('Unsupported runner protocol or invocation identity');
}
function watts(name) {
  const input = request.inputs[name];
  if (input?.type !== 'quantity' || input.unit !== 'W' || typeof input.value !== 'number' || !Number.isFinite(input.value)) {
    throw Error(`${name} must be supplied as a finite quantity in W`);
  }
  return input.value;
}
const total = watts('load') + watts('base');
process.stdout.write(JSON.stringify({
  protocol: request.protocol,
  invocation_id: request.invocation_id,
  outputs: {total: {value: total, unit: 'W'}},
}));
