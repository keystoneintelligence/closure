import test from 'node:test';
import assert from 'node:assert/strict';
import {modelArtifacts, metadataMatches, partDetails} from './project-view.js';

test('non-geometric evidence never creates a model workspace', () => {
  const data = {report: {analyses: [{id:'network.capacity', record:{outputs:{table:{type:'artifact',name:'capacity.csv',media_type:'text/csv'}}}}]}};
  assert.deepEqual(modelArtifacts(data), []);
});

test('multiple models retain producer identity and metadata binds to an explicit output', () => {
  const data = {report:{analyses:[
    {id:'flow.geometry',record:{outputs:{fluid:{type:'artifact',name:'fluid.glb'},walls:{type:'artifact',name:'walls.GLB'}}}},
    {id:'thermal.mesh',record:{outputs:{mesh:{type:'artifact',name:'mesh',media_type:'model/gltf-binary'}}}},
  ]}};
  const models=modelArtifacts(data);
  assert.deepEqual(models.map(m=>m.output),['flow.geometry.fluid','flow.geometry.walls','thermal.mesh.mesh']);
  assert(metadataMatches({model_output:'walls'},{analysis:'flow.geometry'},models[1]));
  assert(!metadataMatches({model_output:'fluid'},{analysis:'flow.geometry'},models[1]));
  assert(!metadataMatches({model_output:'mesh'},{analysis:'flow.geometry'},models[2]));
});

test('component details do not fabricate manufacturing properties', () => {
  assert.deepEqual(partDetails({id:'control-volume'}), []);
  assert.deepEqual(partDetails({id:'boundary',properties:{'Boundary condition':'moving wall','Speed':'1 m/s'}}),
    [['Boundary condition','moving wall'],['Speed','1 m/s']]);
  assert.deepEqual(partDetails({id:'failed-solid',valid:false}),[['Geometry check','ERROR']]);
});
