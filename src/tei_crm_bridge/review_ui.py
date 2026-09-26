"""Client-side review controls for the static, offline-capable TEI preview."""

SCRIPT = r"""
const reviewData=JSON.parse(document.getElementById('review-data').textContent);
const mentions=new Map(reviewData.mentions.map(m=>[m.id,m]));
const decisions=new Map();
const labels={PER:'Person',LOC:'Ort',ORG:'Organisation'};
const detail=document.getElementById('detail');
const reviewer=document.getElementById('reviewer');
const message=document.getElementById('review-message');
let selected=null;
const storageKey='tcb-review:'+reviewData.source.mentionsSha256+':'+reviewData.source.graphSha256;
function tell(value,error=false){message.textContent=value;message.classList.toggle('error',error);}
function save(){
  try{localStorage.setItem(storageKey,JSON.stringify({reviewer:reviewer.value,decisions:[...decisions.values()]}));}
  catch(_error){tell('Lokaler Speicher nicht verfügbar. Bitte Review-Datei exportieren.');}
}
function validDecision(d){
  const m=mentions.get(d.id);
  return m&&['accepted','rejected'].includes(d.decision)&&
    ['block','start','end','text','kind'].every(key=>d[key]===m[key])&&
    typeof d.note==='string'&&d.note.length<=2000&&
    typeof d.decidedAt==='string'&&/(Z|[+-]\d{2}:\d{2})$/.test(d.decidedAt)&&
    !Number.isNaN(Date.parse(d.decidedAt));
}
function loadDecisions(items){
  if(!Array.isArray(items)||items.some(d=>!validDecision(d))||new Set(items.map(d=>d.id)).size!==items.length)
    throw new Error('Entscheidungen enthalten unbekannte oder veränderte Fundstellen.');
  decisions.clear();for(const d of items)decisions.set(d.id,d);
  refresh();if(selected!==null)show(selected);
}
try{
  const saved=JSON.parse(localStorage.getItem(storageKey)||'null');
  if(saved&&typeof saved.reviewer==='string')reviewer.value=saved.reviewer;
  if(saved)loadDecisions(saved.decisions);
}catch(_error){tell('Gespeicherte Entscheidungen konnten nicht geladen werden.',true);}
reviewer.addEventListener('input',save);
function status(id){return decisions.get(id)?.decision||'open';}
function refresh(){
  const counts={open:0,accepted:0,rejected:0};
  for(const id of mentions.keys())counts[status(id)]++;
  document.getElementById('review-count').textContent=
    `${counts.accepted} angenommen · ${counts.rejected} abgelehnt · ${counts.open} offen`;
  document.querySelectorAll('[data-mention-id]').forEach(el=>{
    const value=status(Number(el.dataset.mentionId));
    el.dataset.reviewStatus=value;
    if(el.classList.contains('standoff-button')){
      const badge=el.querySelector('.review-badge');
      if(badge)badge.textContent={accepted:'Angenommen',rejected:'Abgelehnt',open:'Offen'}[value];
    }
  });
}
function row(list,key,value){
  const div=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');
  dt.textContent=key;dd.textContent=String(value);div.append(dt,dd);list.append(div);
}
function show(id){
  selected=id;
  const m=mentions.get(id);
  if(!m)return;
  const heading=document.createElement('h2');heading.textContent='Fundstelle '+id;
  const list=document.createElement('dl');
  for(const [key,value] of [['Text',m.text],['Typ',labels[m.kind]||m.kind],
    ['Position',`Block ${m.block+1}, Zeichen ${m.start}–${m.end}`],['Quelle',m.source],
    ['Score',m.score===null?'–':Number(m.score).toFixed(3)],['Kandidat-URI',m.entities.join(' ')||'–'],['Status',
      {accepted:'Angenommen',rejected:'Abgelehnt',open:'Offen'}[status(id)]]])row(list,key,value);
  const noteLabel=document.createElement('label');noteLabel.textContent='Begründung (optional)';noteLabel.htmlFor='review-note';
  const note=document.createElement('textarea');note.id='review-note';note.maxLength=2000;note.rows=3;
  note.value=decisions.get(id)?.note||'';
  note.addEventListener('input',()=>{const d=decisions.get(id);if(d){d.note=note.value;d.decidedAt=new Date().toISOString();save();}});
  const actions=document.createElement('div');actions.className='review-actions';
  for(const [value,label] of [['accepted','Annehmen'],['rejected','Ablehnen'],['open','Offen lassen']]){
    const button=document.createElement('button');button.type='button';button.textContent=label;
    button.setAttribute('aria-pressed',String(status(id)===value));
    button.addEventListener('click',()=>{
      if(value==='open')decisions.delete(id);
      else decisions.set(id,{id:m.id,block:m.block,start:m.start,end:m.end,text:m.text,kind:m.kind,
        decision:value,note:note.value,decidedAt:new Date().toISOString()});
      save();refresh();show(id);tell(`Fundstelle ${id}: ${label.toLowerCase()}.`);
    });actions.append(button);
  }
  detail.replaceChildren(heading,list,noteLabel,note,actions);
  document.querySelectorAll('[data-mention-id]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.mentionId)===id));
}
const buttons=document.querySelectorAll('[data-filter]');
buttons.forEach(button=>button.addEventListener('click',()=>{
  buttons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  const f=button.dataset.filter;
  document.querySelectorAll('mark.entity').forEach(el=>el.classList.toggle('dimmed',
    f!=='ALL'&&el.dataset.kind!==f&&el.dataset.origin!==f));
}));
document.querySelectorAll('[data-mention-id]').forEach(el=>{
  el.addEventListener('click',()=>show(Number(el.dataset.mentionId)));
  el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(Number(el.dataset.mentionId));}});
});
document.querySelectorAll('mark.entity.editorial').forEach(el=>{
  const showEditorial=()=>{
    selected=null;
    const heading=document.createElement('h2');heading.textContent='Name der Edition';
    const list=document.createElement('dl');
    for(const [key,value] of [['Text',el.dataset.text],['Typ',labels[el.dataset.kind]||el.dataset.kind],
      ['Quelle',el.dataset.source],['Entität',el.dataset.entity||'–']])row(list,key,value);
    detail.replaceChildren(heading,list);
    document.querySelectorAll('[data-mention-id]').forEach(item=>item.classList.remove('selected'));
  };
  el.addEventListener('click',showEditorial);
  el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showEditorial();}});
});
document.getElementById('review-export').addEventListener('click',()=>{
  const name=reviewer.value.trim();
  if(!name||name.length>200){tell('Bitte einen Namen oder ein Kürzel (höchstens 200 Zeichen) eintragen.',true);reviewer.focus();return;}
  const payload={format:'tei-crm-bridge-review',version:1,source:reviewData.source,reviewer:name,
    exportedAt:new Date().toISOString(),decisions:[...decisions.values()].sort((a,b)=>a.id-b.id)};
  const blob=new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=reviewData.source.document+'.review.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  tell(`Review-Datei exportiert: ${payload.decisions.length} Entscheidungen. Bitte sicher aufbewahren.`);
});
document.getElementById('review-import').addEventListener('change',async event=>{
  const file=event.target.files?.[0];if(!file)return;
  try{
    const imported=JSON.parse(await file.text());
    if(imported.format!=='tei-crm-bridge-review'||imported.version!==1||!imported.source||
       Object.keys(reviewData.source).some(key=>imported.source[key]!==reviewData.source[key])||
       Object.keys(imported.source).length!==Object.keys(reviewData.source).length)
      throw new Error('Die Datei gehört nicht zu genau diesem TEI- und RDF-Lauf.');
    if(typeof imported.reviewer!=='string'||!imported.reviewer.trim()||imported.reviewer.length>200)
      throw new Error('Der Name der prüfenden Person fehlt.');
    loadDecisions(imported.decisions);reviewer.value=imported.reviewer;save();
    tell(`Review-Datei geladen: ${decisions.size} Entscheidungen.`);
  }catch(error){tell('Import fehlgeschlagen: '+error.message,true);}
  event.target.value='';
});
refresh();
"""
