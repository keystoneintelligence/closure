import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {sampleTransition} from './assembly-motion.js';
import {producedArtifacts,modelArtifacts,metadataMatches} from './project-view.js';

export const artifacts=producedArtifacts;
export function artifactUrl(a,download=false){return `/api/artifacts/${a.sha256}?type=${encodeURIComponent(a.media_type||'application/octet-stream')}${download?'&download='+encodeURIComponent(a.name):''}`;}

export async function mountModel(container,data,onPart,selectedOutput){
  let disposed=false,frame=0,model=null,meta=null,explosion=0,xray=false,state='',pressStart=0,pressTransition=null,selected='';
  const stage=container.querySelector('.model-stage');
  const files=artifacts(data),models=modelArtifacts(data),glb=models.find(a=>a.output===selectedOutput)||models[0];
  if(!glb){container.querySelectorAll('.model-toolbar button,.model-toolbar input').forEach(control=>control.disabled=true);stage.innerHTML='<div class="empty">This project has no current 3D artifact.<br>Build an analysis that produces a GLB file to explore it here.</div>';return ()=>{};}
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0,0);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
  stage.prepend(renderer.domElement);
  const scene=new THREE.Scene();const camera=new THREE.PerspectiveCamera(33,1,.0001,100);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.07;controls.minDistance=.01;controls.maxDistance=3;
  const pmrem=new THREE.PMREMGenerator(renderer);const room=new RoomEnvironment();const environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.8;room.dispose();pmrem.dispose();
  scene.add(new THREE.HemisphereLight(0xf6ffff,0x8eafba,1));const key=new THREE.DirectionalLight(0xffffff,1.5);key.position.set(.3,.4,.5);scene.add(key);
  const world=new THREE.Group();scene.add(world);
  const nodes=new Map(), originals=new Map();
  const resize=()=>{const {width,height}=stage.getBoundingClientRect();renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();};
  const observer=new ResizeObserver(resize);observer.observe(stage);resize();
  const fit=()=>{if(!model)return;const box=new THREE.Box3().setFromObject(world);const center=box.getCenter(new THREE.Vector3());const radius=box.getSize(new THREE.Vector3()).length()/2;const vertical=THREE.MathUtils.degToRad(camera.fov)/2;const horizontal=Math.atan(Math.tan(vertical)*camera.aspect);const distance=radius/Math.sin(Math.min(vertical,horizontal))*1.18;controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(1,.4,1.6).normalize().multiplyScalar(distance));camera.near=Math.max(distance/1000,.00001);camera.far=Math.max(distance*100,1);camera.updateProjectionMatrix();controls.minDistance=radius*.15;controls.maxDistance=radius*80;controls.update();};
  const pose=()=>{
    if(!model)return;
    for(const [name,node] of nodes){const original=originals.get(name);node.position.copy(original.position);node.quaternion.copy(original.quaternion);node.scale.copy(original.scale);}
    for(const part of meta?.parts||[]){const node=nodes.get(part.id);if(!node||!part.explode)continue;node.position.add(new THREE.Vector3(...part.explode).multiplyScalar(.001*explosion));}
    let motions=(meta?.motions||[]).filter(m=>m.state===state);
    if(pressStart&&meta?.actuation){
      const t=Math.min((performance.now()-pressStart)/(pressTransition?.duration_ms||650),1);
      if(pressTransition){motions=sampleTransition(pressTransition,t);}
      else{motions=[...motions,{parts:meta.actuation.parts||[],translation_mm:(meta.actuation.translation_mm||[0,0,0]).map(x=>x*Math.sin(t*Math.PI))}];}
      if(t===1){
        pressStart=0;
        const states=meta.states||[];
        state=pressTransition?.to||states[(states.findIndex(s=>s.id===state)+1)%states.length]?.id||'';
        const label=container.querySelector('[data-model-state]');
        if(label)label.textContent=meta.states?.find(s=>s.id===state)?.label||state;
      }
    }
    for(const motion of motions){for(const name of motion.parts){
      const node=nodes.get(name);if(!node)continue;
      if(motion.translation_mm)node.position.add(new THREE.Vector3(...motion.translation_mm).multiplyScalar(.001));
      if(motion.rotation_deg)node.quaternion.multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(...motion.rotation_deg.map(x=>x*Math.PI/180))));
      if(motion.scale_axis){const axis=motion.scale_axis;node.scale[axis]*=motion.scale;const pivot=motion.pivot_mm[['x','y','z'].indexOf(axis)]*.001;node.position[axis]+=pivot*(1-motion.scale);}
    }}
    model.traverse(node=>{if(!node.isMesh)return;let partId=node.name;for(let p=node;p;p=p.parent){if(meta?.parts?.some(x=>x.id===p.name)){partId=p.name;break;}}const part=meta?.parts?.find(p=>p.id===partId);const materials=Array.isArray(node.material)?node.material:[node.material];for(const material of materials){if(part?.color&&material.color)material.color.setRGB(part.color[0]/255,part.color[1]/255,part.color[2]/255,THREE.SRGBColorSpace);material.transparent=xray&&!part?.moving;material.opacity=material.transparent?.16:1;material.depthWrite=!material.transparent;material.emissive?.set(selected===partId?0x124a3c:0x000000);}});
  };
  const tick=()=>{if(disposed)return;frame=requestAnimationFrame(tick);if(pressStart)pose();controls.update();renderer.render(scene,camera);};tick();
  container.querySelector('[data-explode]')?.addEventListener('input',event=>{explosion=Number(event.target.value);pose();});
  container.querySelector('[data-xray]')?.addEventListener('click',event=>{xray=!xray;event.currentTarget.classList.toggle('active',xray);pose();});
  container.querySelector('[data-reset-model]')?.addEventListener('click',fit);
  container.querySelector('[data-actuate]')?.addEventListener('click',()=>{if(!pressStart){pressTransition=meta?.actuation?.transitions?.find(t=>t.from===state)||null;if(meta?.actuation?.transitions&&!pressTransition)return;pressStart=performance.now();}});
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();let down;
  renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
  renderer.domElement.addEventListener('click',e=>{if(!model||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;const r=stage.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);const hits=raycaster.intersectObject(model,true);if(hits.length){let node=hits[0].object;while(node&&!meta?.parts?.some(p=>p.id===node.name))node=node.parent;if(node){selected=node.name;pose();onPart?.(meta.parts.find(p=>p.id===selected));}}});
  try{
    for(const file of files.filter(a=>a.media_type==='application/vnd.closure.assembly+json'&&a.analysis===glb.analysis)){
      const candidate=await(await fetch(artifactUrl(file))).json();
      if(metadataMatches(candidate,file,glb)){meta=candidate;break;}
    }
    // Legacy assembly/0.1 defined Z-up geometry. Plain GLB follows glTF Y-up.
    const up=meta?.model_up_axis||(meta?.schema==='closure-assembly/0.1'?'z':'y');
    if(up==='z')world.rotation.x=-Math.PI/2;
    if(up==='x')world.rotation.z=Math.PI/2;
    const gltf=await new GLTFLoader().loadAsync(artifactUrl(glb));
    if(disposed){gltf.scene.traverse(n=>{n.geometry?.dispose();});return ()=>{};}
    model=gltf.scene;world.add(model);model.traverse(n=>{if(!n.name&&n.isMesh)n.name=`component-${nodes.size}`;nodes.set(n.name,n);originals.set(n.name,{position:n.position.clone(),quaternion:n.quaternion.clone(),scale:n.scale.clone()});});
    if(!meta)meta={parts:[...nodes.values()].filter(n=>n.isMesh).map(n=>({id:n.name,name:n.name}))};
    if(meta?.states?.length)state=meta.states[0].id;
    pose();fit();stage.querySelector('.loading-overlay')?.remove();
    const list=container.querySelector('[data-parts]');if(list&&meta){for(const part of meta.parts||[]){const button=document.createElement('button');button.className='part-button';const dot=document.createElement('span');dot.className='dot';dot.style.background=`rgb(${(part.color||[140,170,190]).slice(0,3).join(',')})`;button.append(dot,document.createTextNode(part.id.replaceAll('_',' ')));button.addEventListener('click',()=>{selected=part.id;pose();onPart?.(part);});list.append(button);}}
    const actuator=container.querySelector('[data-actuate]');if(actuator){actuator.hidden=!meta?.actuation;actuator.disabled=!meta?.actuation;actuator.textContent=meta?.actuation?.label||'Actuate';}
    const explosionControl=container.querySelector('[data-explode]');if(explosionControl)explosionControl.closest('label').hidden=!meta?.parts?.some(p=>p.explode);
    const caption=container.querySelector('[data-model-state]');if(caption)caption.textContent=meta?.states?.find(s=>s.id===state)?.label||'';
    if(meta?.notes?.length){const notes=document.createElement('details');notes.className='model-notes';const title=document.createElement('summary');title.textContent='Model scope and assumptions';notes.append(title);for(const text of meta.notes){const paragraph=document.createElement('p');paragraph.textContent=text;notes.append(paragraph);}container.querySelector('.model-toolbar')?.after(notes);}
  }catch(error){const message=stage.querySelector('.loading-overlay')||stage.appendChild(document.createElement('div'));message.className='loading-overlay';message.textContent=`Model unavailable: ${error.message}`;}
  return ()=>{disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();scene.traverse(n=>{n.geometry?.dispose();if(n.material)(Array.isArray(n.material)?n.material:[n.material]).forEach(m=>m.dispose());});environment.dispose();renderer.dispose();renderer.domElement.remove();};
}
