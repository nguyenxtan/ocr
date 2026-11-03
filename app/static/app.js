const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindLabel={gpkd:'Giấy chứng nhận đăng ký doanh nghiệp (GPKD)',eport:'Đăng ký sử dụng EPORT'};
const statusLabel={read:'Đã đọc',manual:'Đã chỉnh sửa',missing:'Thiếu dữ liệu',uncertain:'Cần kiểm tra',ambiguous:'Nhiều giá trị'};
const resultLabel={PASS:'Khớp',REVIEW:'Cần kiểm tra',FAIL:'Không khớp'};
const checkLabel=r=>r.type==='presence'&&r.status!=='REVIEW'?(r.status==='PASS'?'Có':'Không có'):resultLabel[r.status];
let session={documents:{}}, step=1, kind='gpkd', pageNumber=1, selected=null, zoom=1, rotation=0, report=null, activeCheck=null;
let draftRegions=null, draftSource=null, drawing=false, pointStart=null, pollTimer=null, inflight=new Set(), sequence=0;
const doc=()=>session.documents[kind];
function alertMessage(text){$('#alert').textContent=text;$('#alert').hidden=!text;}
async function api(url,options={}){
 const r=await fetch(url,options); let data;
 if((r.headers.get('content-type')||'').includes('application/json'))data=await r.json();
 if(!r.ok)throw new Error(data?.detail&&typeof data.detail==='string'?data.detail:`Yêu cầu không hoàn tất (${r.status}).`);
 return data;
}
function ready(){return !inflight.size&&['gpkd','eport'].every(k=>session.documents[k]?.state==='ready'&&session.documents[k]?.detected_kind===k);}
function pageUrl(k,d,p){return `/api/pages/${k}/${d.id}/${p}`;}
function goto(n){sequence++;step=n; for(const [i,id] of ['upload','ocr','compare'].entries()){$(`#screen-${id}`).hidden=n!==i+1;} $$('#steps li').forEach((el,i)=>{el.className=i+1===n?'active':i+1<n?'done':'';el.querySelector('b').textContent=i+1<n?'✓':i+1;});alertMessage(''); if(n===2){if(!session.documents[kind])kind='gpkd';renderOCR();}window.scrollTo(0,0);}
async function refresh(){session=await api('/api/session');renderUpload();const seconds=Math.max(0,Math.ceil((session.expires_at-Date.now()/1000)/60));$('#expiry').textContent=`${seconds} phút nữa`;schedulePoll();}
function schedulePoll(){clearTimeout(pollTimer);if(Object.values(session.documents).some(d=>['queued','running'].includes(d.state))){pollTimer=setTimeout(()=>refresh().catch(e=>alertMessage(e.message)),1100);}}
function renderUpload(){
 $('#uploads').innerHTML=['gpkd','eport'].map(k=>{
 const d=session.documents[k], busy=inflight.has(k)||['queued','running'].includes(d?.state), valid=d?.state==='ready'&&d.detected_kind===k;
 let state=d?.state==='ready'?(valid?'Đúng loại':d.detected_kind==='unknown'?'Chưa xác định':'Sai loại'):d?.state==='error'?'Lỗi OCR':d?.state==='cancelled'?'Đã hủy':busy?'Đang kiểm tra':'Chưa tải';
 let badge=valid?'ready':d?.state==='ready'?(d.detected_kind==='unknown'?'unknown':'wrong'):d?.state==='error'?'wrong':'';
 const input=`<input type="file" id="file-${k}" accept="application/pdf,.pdf" aria-label="Tải PDF ${k.toUpperCase()}" ${inflight.has(k)?'disabled':''}>`;
 return `<article class="upload-card" data-kind="${k}"><div class="card-head"><span class="doc-icon">▤</span><div><h3>${kindLabel[k]}</h3><p>File PDF · tối đa 20 MB</p></div><span class="badge ${badge}" aria-live="polite">${state}</span></div><div class="card-body">${input}${d?`<div class="uploaded"><div class="paper-preview">${d.state==='ready'?`<img src="${pageUrl(k,d,1)}" alt="Trang đầu ${k.toUpperCase()}">`:`<span class="quiet">${busy?'Đang đọc nội dung tài liệu…':esc(d.error||'Tác vụ đã hủy.')}</span>`}</div><div class="metadata"><div class="detected"><small>Loại tài liệu nhận diện</small><strong>${d.state==='ready'?esc(kindLabel[d.detected_kind]||'Chưa đủ căn cứ xác định'):state}</strong></div><div class="file-name">${esc(d.name)}</div><div class="meta-row"><span>Số trang</span><strong>${d.pages?.length??'—'}</strong></div><div class="meta-row"><span>Dung lượng</span><strong>${(d.size/1024/1024).toFixed(2)} MB</strong></div><div class="card-actions">${d.state==='ready'?`<button data-preview="${k}">◉ Xem trước</button>`:''}<button data-replace="${k}" ${inflight.has(k)?'disabled':''}>Thay file</button><button data-remove="${k}" ${inflight.has(k)?'disabled':''}>Xóa</button>${['queued','running'].includes(d.state)?`<button data-cancel="${k}">Hủy tác vụ</button>`:''}</div></div></div>`:`<div class="dropzone" data-drop="${k}"><span class="upload-symbol">⇧</span><strong>Kéo PDF vào đây</strong><span class="quiet">Hoặc chọn tài liệu từ máy của bạn</span><label class="file-label" for="file-${k}" tabindex="0">Chọn PDF ${k.toUpperCase()}</label><span class="quiet">Kiểm tra định dạng, mật khẩu và loại chứng từ</span></div>`}</div></article>`;
 }).join('');
 ['gpkd','eport'].forEach(k=>{$(`#file-${k}`).onchange=e=>upload(k,e.target.files[0]);});
 $$('[data-drop]').forEach(el=>{el.ondragover=e=>{e.preventDefault();el.classList.add('dragover');};el.ondragleave=()=>el.classList.remove('dragover');el.ondrop=e=>{e.preventDefault();upload(el.dataset.drop,e.dataTransfer.files[0]);};});
 $$('[data-replace]').forEach(el=>el.onclick=()=>$(`#file-${el.dataset.replace}`).click());
 $$('[data-remove]').forEach(el=>el.onclick=()=>mutate(`/api/documents/${el.dataset.remove}`,'DELETE'));
 $$('[data-cancel]').forEach(el=>el.onclick=()=>mutate(`/api/jobs/${el.dataset.cancel}/cancel`,'POST'));
 $$('[data-preview]').forEach(el=>el.onclick=()=>preview(el.dataset.preview));
 $$('.file-label').forEach(el=>el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$(`#${el.htmlFor}`).click();}});
 $('#continue-upload').disabled=!ready();
 $('#upload-summary').className=`summary ${ready()?'valid':''}`;
 $('#upload-summary').innerHTML=ready()?'<span class="circle">✓</span><div><strong>Đã nhận diện đúng hai loại chứng từ</strong><p>Bạn có thể tiếp tục kiểm tra thông tin và vùng nguồn.</p></div>':'<span class="circle">1</span><div><strong>Chờ đủ hai PDF đúng loại</strong><p>Tên file không quyết định loại chứng từ. Nếu chưa xác định được, hãy kiểm tra hoặc thay tài liệu.</p></div>';
}
async function upload(k,file){
 if(!file||inflight.has(k))return;
 alertMessage('');inflight.add(k);report=null;selected=null;draftRegions=null;draftSource=null;sequence++;renderUpload();
 try{
  // Selecting a new file invalidates the prior document immediately, including a failed replacement.
  if(session.documents[k])await api(`/api/documents/${k}`,{method:'DELETE'});
  delete session.documents[k];renderUpload();
  if(file.size>20*1024*1024)throw new Error('PDF vượt giới hạn 20 MB.');
  session=await api(`/api/documents/${k}`,{method:'PUT',headers:{'Content-Type':'application/pdf','X-File-Name':encodeURIComponent(file.name)},body:file});
 }catch(e){alertMessage(e.message);}finally{inflight.delete(k);renderUpload();schedulePoll();}
}
async function mutate(url,method){const k=url.split('/')[3];inflight.add(k);report=null;sequence++;delete session.documents[k];renderUpload();try{session=await api(url,{method});}catch(e){alertMessage(e.message);session=await api('/api/session');}finally{inflight.delete(k);renderUpload();schedulePoll();}}
function preview(k){const d=session.documents[k];$('#preview-body').innerHTML=d.pages.map(p=>`<p class="quiet">${k.toUpperCase()} · Trang ${p.number}</p><img loading="lazy" src="${pageUrl(k,d,p.number)}" alt="Trang ${p.number}">`).join('');$('#preview').showModal();}
function strip(){return ['gpkd','eport'].map(k=>{const d=session.documents[k];return `<div class="document-pill"><span class="doc-icon">▤</span><div><strong>${esc(d.name)}</strong><small>${d.pages.length} trang · ${(d.size/1024/1024).toFixed(2)} MB</small></div><span class="tag">${k.toUpperCase()}</span></div>`;}).join('');}
function renderOCR(){
 $('#document-strip').innerHTML=strip();
 $('#thumbnails').innerHTML=['gpkd','eport'].map(k=>`<div class="thumb-doc">${k.toUpperCase()}</div>${session.documents[k].pages.map(p=>`<button class="thumb ${k===kind&&p.number===pageNumber?'active':''}" data-doc="${k}" data-page="${p.number}"><img loading="lazy" src="${pageUrl(k,session.documents[k],p.number)}" alt="">Trang ${p.number}</button>`).join('')}`).join('');
 $$('.thumb').forEach(el=>el.onclick=()=>{const same=kind===el.dataset.doc;kind=el.dataset.doc;pageNumber=+el.dataset.page;if(!same)selected=null;drawing=false;draftRegions=null;draftSource=null;rotation=0;renderOCR();});
 const d=doc();if(pageNumber>d.pages.length)pageNumber=1;
 const count=Object.values(d.fields).filter(f=>['read','manual'].includes(f.status)).length;
 $('#field-count').textContent=`${count}/${Object.keys(d.fields).length} đã đọc`;
 $('#fields').innerHTML=Object.values(d.fields).map(f=>`<button class="field ${selected===f.key?'selected':''}" data-field="${f.key}"><span class="field-label">${esc(f.label)}</span><span class="field-value">${esc(f.status==='ambiguous'?f.candidates.map(c=>c.value).join(' / '):f.value||'Chưa đọc được')}<small>${statusLabel[f.status]}${f.regions.length?' · Trang '+[...new Set(f.regions.map(r=>r.page))].join(', '):''}</small></span></button>`).join('');
 $$('.field').forEach(el=>el.onclick=()=>selectField(el.dataset.field));
 $('#timings').textContent=`${kind.toUpperCase()} · Đọc ${d.timings.read}s · Trích trường ${d.timings.fields}s · Đọc lại vùng ${d.timings.recheck??0}s · Kiểm tra dấu ${d.timings.marks}s · Chờ ${d.timings.queue}s · Nguồn: ${d.pages.map(p=>`trang ${p.number} ${p.method==='text'?'lớp chữ':'OCR'}`).join(', ')}`;
 renderPage();renderEditor();
}
function selectField(key,fromRegion=false){selected=key;drawing=false;draftRegions=null;draftSource=null;const f=doc().fields[key];if(!fromRegion&&f.regions.length)pageNumber=f.regions[0].page;renderOCR();if(f.regions.length)$('rect.source.selected')?.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});}
function transform(w,h,r){return r===90?`translate(${h},0) rotate(90)`:r===180?`translate(${w},${h}) rotate(180)`:r===270?`translate(0,${w}) rotate(270)`:'';}
function renderPage(){
 const d=doc(),p=d.pages[pageNumber-1],w=p.width,h=p.height,sw=rotation%180?h:w,sh=rotation%180?w:h;
 $('#page-title').textContent=`${kind.toUpperCase()} · Trang ${pageNumber} / ${d.pages.length}`;$('#zoom-label').textContent=Math.round(zoom*100)+'%';
 const overlays=Object.values(d.fields).flatMap(f=>f.regions.filter(r=>r.page===pageNumber).map(r=>`<rect class="source ${selected===f.key?'selected':''}" data-key="${f.key}" data-box="${r.box.join(',')}" x="${r.box[0]*w}" y="${r.box[1]*h}" width="${(r.box[2]-r.box[0])*w}" height="${(r.box[3]-r.box[1])*h}" tabindex="0" role="button" aria-label="${esc(f.label)}"><title>${esc(f.label)}</title></rect>`)).join('');
 $('#pdf-stage').style.width=(zoom*100)+'%';
 $('#pdf-stage').innerHTML=`<svg class="page" viewBox="0 0 ${sw} ${sh}" aria-label="PDF ${kind.toUpperCase()} trang ${pageNumber}"><g id="page-coordinates" transform="${transform(w,h,rotation)}"><image href="${pageUrl(kind,d,pageNumber)}" width="${w}" height="${h}"/><g id="source-overlays">${overlays}</g>${(draftRegions||[]).filter(r=>r.page===pageNumber).map(r=>`<rect class="pending" data-box="${r.box.join(',')}" x="${r.box[0]*w}" y="${r.box[1]*h}" width="${(r.box[2]-r.box[0])*w}" height="${(r.box[3]-r.box[1])*h}"><title>Vùng nguồn đang chọn, chưa lưu</title></rect>`).join('')}<rect class="draft" hidden/></g></svg>`;
 $$('rect.source').forEach(el=>{el.onclick=e=>{if(!drawing){e.stopPropagation();selectField(el.dataset.key,true);}};el.onkeydown=e=>{if(e.key==='Enter')selectField(el.dataset.key,true);};});
 const svg=$('svg.page');svg.style.cursor=drawing?'crosshair':'';
 function point(e){const pt=new DOMPoint(e.clientX,e.clientY).matrixTransform($('#page-coordinates').getScreenCTM().inverse());return [Math.max(0,Math.min(1,pt.x/w)),Math.max(0,Math.min(1,pt.y/h))];}
 svg.onpointerdown=e=>{if(!drawing||!selected)return;e.preventDefault();pointStart=point(e);svg.setPointerCapture(e.pointerId);};
 svg.onpointermove=e=>{if(!pointStart)return;const end=point(e),box=[Math.min(pointStart[0],end[0]),Math.min(pointStart[1],end[1]),Math.max(pointStart[0],end[0]),Math.max(pointStart[1],end[1])];const r=$('rect.draft');r.removeAttribute('hidden');r.setAttribute('x',box[0]*w);r.setAttribute('y',box[1]*h);r.setAttribute('width',(box[2]-box[0])*w);r.setAttribute('height',(box[3]-box[1])*h);};
 svg.onpointerup=e=>{if(!pointStart)return;const end=point(e),box=[Math.min(pointStart[0],end[0]),Math.min(pointStart[1],end[1]),Math.max(pointStart[0],end[0]),Math.max(pointStart[1],end[1])];pointStart=null;if(box[2]-box[0]<.003||box[3]-box[1]<.003)return;draftRegions=[{page:pageNumber,box:box.map(v=>+v.toFixed(6))}];draftSource=null;renderCandidates();drawing=false;$('#draw-region').classList.remove('active');$('#draw-region').textContent='Vẽ lại vùng';renderPage();updateRegionInfo();};
 svg.onpointercancel=()=>{pointStart=null;};
}
function updateRegionInfo(){const r=draftRegions||doc().fields[selected]?.regions||[];$('#region-info').textContent=r.length?`${draftRegions?(draftSource===null?'Vùng mới chưa lưu':`Nguồn ứng viên ${draftSource+1} chưa lưu`):'Vùng nguồn'}: ${r.length} khung · Trang ${[...new Set(r.map(x=>x.page))].join(', ')}`:'Chưa có vùng nguồn. Chọn trang và vẽ vùng trước khi lưu.';}
const PRESENCE=['signature','seal'];
// Selectable sources: one per suspect location for presence fields, else one per conflicting value.
function choices(f){
 if(!f)return [];
 if(PRESENCE.includes(f.key)){const all=f.candidates.flatMap(c=>c.regions.map(r=>({value:c.value,status:c.status,regions:[r]})));return all.length>1?all:[];}
 return f.candidates.length>1?f.candidates:[];
}
function renderCandidates(){
 const f=doc().fields[selected],box=$('#candidates'),list=choices(f),presence=PRESENCE.includes(f?.key);
 if(!list.length){box.hidden=true;box.innerHTML='';return;}
 box.hidden=false;
 const must=presence?f.regions.length>1:f.status==='ambiguous';
 const intro=presence?`<strong>${list.length} vùng nghi có.</strong> ${must?'Chọn đúng một vùng hoặc vẽ vùng mới trước khi xác nhận.':'Các vùng OCR gốc được giữ nguyên.'}`:`<strong>${list.length} ứng viên khác nhau.</strong> ${must?'Chọn ứng viên đúng làm nguồn hoặc vẽ vùng mới trước khi lưu.':'Giá trị gốc từ OCR được giữ nguyên.'}`;
 box.innerHTML=`<p>${intro}</p>`+list.map((c,i)=>`<button type="button" data-candidate="${i}" class="${draftSource===i?'active':''}">${i+1}. ${presence?`Vùng ${i+1}`:esc(c.value)}<small>${statusLabel[c.status]||esc(c.status)} · Trang ${[...new Set(c.regions.map(r=>r.page))].join(', ')}</small></button>`).join('');
 $$('[data-candidate]').forEach(el=>el.onclick=()=>{const i=+el.dataset.candidate,c=choices(doc().fields[selected])[i];draftSource=i;draftRegions=c.regions.map(r=>({page:r.page,box:[...r.box]}));drawing=false;pageNumber=c.regions[0].page;const value=$('#edit-value').value;renderPage();$('#edit-value').value=presence?value:c.value;$('#draw-region').classList.remove('active');renderCandidates();updateRegionInfo();});
}
function renderEditor(){
 const f=doc().fields[selected];$('#editor').hidden=!f;if(!f)return;
 $('#edit-label').textContent=f.label;$('#edit-value').value=f.status==='ambiguous'?'':f.value;$('#edit-reason').value='';$('#raw-value').textContent=`Giá trị gốc: ${f.candidates.length>1?`${f.candidates.length} ứng viên OCR (bên dưới)`:(f.raw||'Chưa trích xuất được')} · Chuẩn hóa: ${f.normalized||'—'}`;renderCandidates();updateRegionInfo();
 $('#draw-region').classList.toggle('active',drawing);$('#draw-region').textContent=drawing?'Kéo khung trên PDF…':'Vẽ lại vùng';
 $('#history').innerHTML=f.history.length?f.history.map(h=>`<article><strong>${new Date(h.at*1000).toLocaleString('vi-VN')}</strong><div>${esc(h.reason)}</div><div>${esc(h.before.value||'Trống')} → ${esc(h.after.value||'Trống')}</div><small>${h.before.regions.length} → ${h.after.regions.length} vùng</small></article>`).join(''):'Chưa có chỉnh sửa.';
}
$('#draw-region').onclick=()=>{drawing=!drawing;pointStart=null;$('#draw-region').classList.toggle('active',drawing);$('#draw-region').textContent=drawing?'Kéo khung trên PDF…':'Vẽ lại vùng';renderPage();};
$('#save-edit').onclick=async()=>{
 sequence++;$('#continue-compare').disabled=true;
 try{
  const regions=draftRegions||doc().fields[selected].regions,reason=$('#edit-reason').value.trim();
  if(!reason)throw new Error('Nhập lý do chỉnh sửa để lưu lịch sử.');
  if(!regions.length)throw new Error('Vẽ vùng nguồn trước khi lưu giá trị.');
  if(doc().fields[selected].status==='ambiguous'&&!draftRegions)throw new Error('Trường có nhiều ứng viên mâu thuẫn. Chọn một ứng viên làm nguồn hoặc vẽ vùng mới trước khi lưu.');
  if(PRESENCE.includes(selected)&&regions.length>1)throw new Error('Xác nhận hiện diện chỉ dùng một vùng. Chọn một vùng nghi có hoặc vẽ vùng mới.');
  $('#save-edit').disabled=true;
  await api(`/api/fields/${kind}/${selected}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:$('#edit-value').value,regions,revision:doc().revision,document_id:doc().id,reason})});
  session=await api('/api/session');report=null;draftRegions=null;draftSource=null;alertMessage('');renderOCR();
 }catch(e){alertMessage(e.message);}finally{$('#save-edit').disabled=false;$('#continue-compare').disabled=false;}
};
$('#zoom-in').onclick=()=>{zoom=Math.min(3,zoom+.25);renderPage();};$('#zoom-out').onclick=()=>{zoom=Math.max(.5,zoom-.25);renderPage();};$('#rotate').onclick=()=>{rotation=(rotation+90)%360;renderPage();};
function renderReport(){
 $('#compare-strip').innerHTML=strip();
 $('#verdict').className=`verdict ${report.conclusion}`;
 $('#verdict').innerHTML=`<span class="symbol">${report.conclusion==='PASS'?'✓':report.conclusion==='FAIL'?'×':'!'}</span><div><h2>Kết quả đối chiếu: ${report.label}</h2><p>${report.conclusion==='PASS'?'Các tiêu chí có đủ dữ liệu phù hợp.':'Xem từng tiêu chí và vùng nguồn trước khi sử dụng kết quả.'}</p></div><div class="counts"><div class="count"><strong>${report.rows.length}</strong>Tiêu chí</div>${['PASS','FAIL','REVIEW'].map(s=>`<div class="count"><strong>${report.counts[s]}</strong>${resultLabel[s]}</div>`).join('')}</div>`;
 $('#checks').innerHTML=report.rows.map(r=>`<tr data-check="${r.id}" tabindex="0" class="${activeCheck===r.id?'selected':''}"><td>${esc(r.label)}</td><td>${esc(r.left.value||'Chưa đọc được')}</td><td>${esc(r.right.value||'Chưa đọc được')}</td><td><span class="badge ${r.status}">${checkLabel(r)}</span></td></tr>`).join('');
 $$('[data-check]').forEach(el=>{el.onclick=()=>{activeCheck=el.dataset.check;renderReport();};el.onkeydown=e=>{if(e.key==='Enter'){activeCheck=el.dataset.check;renderReport();}};});
 const row=report.rows.find(r=>r.id===activeCheck)||report.rows[0];activeCheck=row.id;
 $('#check-detail').innerHTML=`<h3>${esc(row.label)} <span class="badge ${row.status}">${checkLabel(row)}</span></h3><p class="quiet">${esc(row.reason)}</p><div class="value-pair"><div><small>Giá trị thứ nhất</small>${esc(row.left.value||'Chưa đọc được')}</div><div><small>Giá trị thứ hai</small>${esc(row.right.value||'Chưa đọc được')}</div></div>`;
 const leftKind=row.left_kind||(['signer','seal_identity','signature','seal'].includes(row.id)?'eport':'gpkd');
 $('#evidence').innerHTML=[[leftKind,row.left],[row.right_kind||'eport',row.right]].map(([k,f])=>{
  if(!f.regions?.length)return `<article class="proof"><h4>${row.type==='presence'&&!f.key?'Yêu cầu kiểm tra':k.toUpperCase()+' · Chưa có vùng'}</h4><p>${row.type==='presence'&&!f.key?'Chỉ kiểm tra hiện diện trên từng tài liệu, không so hình mộc giữa GPKD và EPORT.':'Thiếu bằng chứng nguồn. Quay lại OCR để kiểm tra.'}</p></article>`;
  return `<article class="proof">${f.regions.map(r=>{const p=session.documents[k].pages[r.page-1],w=p.width,h=p.height;let [x0,y0,x1,y1]=r.box;const pad=.035;x0=Math.max(0,x0-pad);y0=Math.max(0,y0-pad);x1=Math.min(1,x1+pad);y1=Math.min(1,y1+pad);return `<h4>${k.toUpperCase()} · Trang ${r.page}</h4><svg viewBox="${x0*w} ${y0*h} ${(x1-x0)*w} ${(y1-y0)*h}"><image href="${pageUrl(k,session.documents[k],r.page)}" width="${w}" height="${h}"/><rect class="source" x="${r.box[0]*w}" y="${r.box[1]*h}" width="${(r.box[2]-r.box[0])*w}" height="${(r.box[3]-r.box[1])*h}"/></svg>`;}).join('')}<button data-open-source="${k}" data-field-source="${esc(f.key||'')}" data-page-source="${f.regions[0].page}">Mở trang nguồn ↗</button></article>`;
 }).join('');
 $$('[data-open-source]').forEach(el=>el.onclick=()=>{kind=el.dataset.openSource;pageNumber=+el.dataset.pageSource;selected=el.dataset.fieldSource;rotation=0;draftRegions=null;draftSource=null;goto(2);});
}
$('#continue-upload').onclick=()=>{if(ready()){kind='gpkd';pageNumber=1;selected=null;goto(2);}};
$('#continue-compare').onclick=async()=>{const seq=++sequence;try{const result=await api('/api/report');const current=await api('/api/session');if(seq!==sequence)return;if(!['gpkd','eport'].every(k=>current.documents[k]?.id===result.documents[k]?.id&&current.documents[k]?.revision===result.documents[k]?.revision))throw new Error('Hồ sơ đã thay đổi. Vui lòng đối chiếu lại.');session=current;report=result;activeCheck='tax_id';goto(3);renderReport();}catch(e){if(seq===sequence)alertMessage(e.message);}};
$('#back-upload').onclick=()=>goto(1);$('#back-ocr').onclick=()=>goto(2);
// Export exactly the report snapshot on screen, not a recomputation of current session state.
$('#download').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='doi-chieu.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('#finish').onclick=async()=>{try{await api('/api/session',{method:'DELETE'});selected=null;report=null;draftRegions=null;draftSource=null;kind='gpkd';pageNumber=1;goto(1);await refresh();alertMessage('Đã hoàn thành và xóa hồ sơ của phiên.');}catch(e){alertMessage(e.message);}};
$('#close-preview').onclick=()=>$('#preview').close();
refresh().catch(e=>alertMessage(e.message));
