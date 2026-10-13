import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import Ajv2020 from 'ajv/dist/2020.js';

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const ajv = new Ajv2020({strict:false, allErrors:true});
const validators = new Map();
for (const item of read('../conformance/cases.json')) {
  test(`independent schema validation: ${item.name}`, () => {
    if (!validators.has(item.schema)) validators.set(item.schema, ajv.compile(read(`../schema/${item.schema}.schema.json`)));
    const valid = validators.get(item.schema)(item.document);
    assert.equal(valid, item.valid, JSON.stringify(validators.get(item.schema).errors));
  });
}
for (const item of read('../conformance/canonical.json')) {
  test(`canonical UTF-8 digest: ${item.name}`, () => {
    assert.equal(createHash('sha256').update(item.canonical, 'utf8').digest('hex'), item.sha256);
  });
}
