import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('./runtime.js',import.meta.url),'utf8');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const run=new AsyncFunction('eda','batch',source);

function fixture({failAt=Infinity,nonempty=false}={}) {
    const items=new Map();
    let count=0;
    const api={
        async getAllPrimitiveId(){return nonempty ? ['existing'] : [];},
        async get(id){return items.get(id);},
        async delete(id){return items.delete(id);},
    };
    const eda={
        dmt_SelectControl:{async getCurrentDocumentInfo(){return {uuid:'test-pcb',documentType:3};}},
        sys_Unit:{mmToMil:n=>n/0.0254},
        pcb_MathPolygon:{createPolygon:s=>({getSource:()=>s})},
    };
    function add(layer,polygon) {
        if (++count===failAt) throw Error('injected failure');
        const id=String(count);
        const item={getState_PrimitiveId:()=>id,getState_Layer:()=>layer,getState_ComplexPolygon:()=>polygon,getState_Polygon:()=>polygon};
        items.set(id,item);
        return item;
    }
    for(const name of ['Line','Arc','Fill','Pad','Via','Component','Polyline','Pour','Region','String','Image','Object']) eda['pcb_Primitive'+name]={...api};
    eda.pcb_PrimitiveFill.create=async (layer,polygon)=>add(layer,polygon);
    eda.pcb_PrimitivePolyline.create=async (net,layer,polygon)=>add(layer,polygon);
    return {eda,items};
}

const batch={documentUuid:'test-pcb',width_mm:30,height_mm:40,requireEmpty:true,outline:true,shapes:[{layer:'back_mask_open',rect_mm:[3,5,7,2]}]};
{
    const {eda,items}=fixture();
    const result=await run(eda,batch);
    assert.equal(result.ok,true);
    assert.equal(items.size,2);
    const shape=result.created[1];
    assert.equal(shape.layer,6);
    assert.ok(Math.abs(shape.source[0]*0.0254-20)<1e-8,'back x must be width-x-w');
    assert.ok(Math.abs(shape.source[1]*0.0254+5)<1e-8,'image y must be inverted');
    assert.deepEqual(shape.source.slice(-2),shape.source.slice(0,2),'fill path explicitly closes');
}
{
    const {eda,items}=fixture({failAt:2});
    const result=await run(eda,batch);
    assert.equal(result.ok,false);
    assert.equal(items.size,0,'rollback only objects created by this batch');
    assert.equal(result.cleanup[0].deleted,true);
}
{
    const {eda,items}=fixture({nonempty:true});
    const result=await run(eda,batch);
    assert.equal(result.ok,false);
    assert.equal(items.size,0,'existing designs must not be modified');
}
console.log('3 runtime checks passed: mirror/units/readback, rollback, nonempty document guard');
