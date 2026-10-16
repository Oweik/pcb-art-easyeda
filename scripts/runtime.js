const Layer = {TOP:1, BOTTOM:2, TOP_SILKSCREEN:3, BOTTOM_SILKSCREEN:4, TOP_SOLDER_MASK:5, BOTTOM_SOLDER_MASK:6, BOARD_OUTLINE:11};
const FillMode = {SOLID:0};
const DocumentType = {PCB:3};
const layerMap = {front_copper:Layer.TOP, back_copper:Layer.BOTTOM, front_mask_open:Layer.TOP_SOLDER_MASK, back_mask_open:Layer.BOTTOM_SOLDER_MASK, front_silk:Layer.TOP_SILKSCREEN, back_silk:Layer.BOTTOM_SILKSCREEN};
const mm = value => eda.sys_Unit.mmToMil(value);
const created = [];
const assertDocument = async () => {
    const doc = await eda.dmt_SelectControl.getCurrentDocumentInfo();
    if (!doc || doc.uuid !== batch.documentUuid || doc.documentType !== DocumentType.PCB) throw new Error('PCB focus changed; stopped');
};
const equal = (a,b) => {
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v,i) => equal(v,b[i]));
    return typeof a === 'number' && typeof b === 'number' ? Math.abs(a-b) < 0.001 : a === b;
};
try {
    await assertDocument();
    if (batch.requireEmpty) {
        for (const name of ['Line','Arc','Fill','Pad','Via','Component','Polyline','Pour','Region','String','Image','Object']) {
            const api = eda['pcb_Primitive'+name];
            if (!api || typeof api.getAllPrimitiveId !== 'function') throw new Error('Cannot establish empty PCB: '+name);
            if ((await api.getAllPrimitiveId()).length) throw new Error('Use an empty test PCB; found '+name);
        }
    }
    if (batch.outline) {
        const w=mm(batch.width_mm), h=mm(batch.height_mm);
        const source=[0,0,'L',w,0,w,-h,0,-h,0,0];
        const polygon=eda.pcb_MathPolygon.createPolygon(source);
        const item=await eda.pcb_PrimitivePolyline.create('',Layer.BOARD_OUTLINE,polygon,mm(0.1),false);
        if (!item) throw new Error('Outline creation returned undefined');
        created.push({kind:'Polyline',id:item.getState_PrimitiveId(),layer:Layer.BOARD_OUTLINE,source});
    }
    for (const shape of batch.shapes) {
        await assertDocument();
        const [x,y,w,h]=shape.rect_mm;
        const x0=shape.layer.startsWith('back_') ? batch.width_mm-x-w : x;
        const points=[[x0,-y],[x0+w,-y],[x0+w,-y-h],[x0,-y-h]];
        const source=[...points[0].map(mm),'L',...points.slice(1).flatMap(p=>p.map(mm)),...points[0].map(mm)];
        const polygon=eda.pcb_MathPolygon.createPolygon(source);
        if (!polygon) throw new Error('Invalid polygon');
        const layer=layerMap[shape.layer];
        const item=await eda.pcb_PrimitiveFill.create(layer,polygon,'',FillMode.SOLID,0,false);
        if (!item) throw new Error('Fill creation returned undefined');
        created.push({kind:'Fill',id:item.getState_PrimitiveId(),layer,source});
    }
    for (const item of created) {
        await assertDocument();
        const actual=await eda['pcb_Primitive'+item.kind].get(item.id);
        if (!actual || actual.getState_Layer() !== item.layer) throw new Error('Readback layer mismatch: '+item.id);
        const geometry=item.kind === 'Fill' ? actual.getState_ComplexPolygon().getSource() : actual.getState_Polygon().getSource();
        if (!equal(geometry,item.source || item.coords)) throw new Error('Readback geometry mismatch: '+item.id);
    }
    return {ok:true,documentUuid:batch.documentUuid,created,verification:'native API geometry and layer readback; not independent CAM'};
} catch (error) {
    const cleanup=[];
    for (const item of [...created].reverse()) {
        try {
            await assertDocument();
            const deleted=await eda['pcb_Primitive'+item.kind].delete(item.id);
            cleanup.push({id:item.id,deleted});
        } catch (failure) { cleanup.push({id:item.id,error:String(failure)}); }
    }
    return {ok:false,error:String(error),created,cleanup};
}
