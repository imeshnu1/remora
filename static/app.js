const app = document.getElementById('app');
let me = null;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  let data = null; try { data = await r.json(); } catch(e) {}
  if (!r.ok) {
    let msg = (data && (data.error || (typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data)))) || r.statusText;
    const err = new Error(msg); err.status = r.status; err.data = data; throw err;
  }
  return data;
}
function renderUserbox(){
  document.getElementById('userbox').innerHTML = me && me.id
    ? `<span class="badge">${esc(me.name)} · ${esc(me.plan)}</span> <button id="signout">Sign out</button>`
    : `<button id="signin-nav">Sign in</button>`;
  const so = document.getElementById('signout'); if (so) so.onclick = async ()=>{ await fetch('/api/signout',{method:'POST'}); me=null; renderUserbox(); showAuth(); };
  const si = document.getElementById('signin-nav'); if (si) si.onclick = showAuth;
}
document.querySelectorAll('[data-nav]').forEach(b => b.onclick = ()=> route(b.dataset.nav));
function route(name){
  if (name==='discover') return showDiscover();
  if (name==='publishers') return showPublishers();
  if (name==='pricing') return showPricing();
  return me && me.id ? showMyBooks() : showAuth();
}
function showAuth(){
  app.innerHTML = `<h1>Write the book of your life.</h1>
  <p>Remora is where anybody can write their own memoir, legacy book, chronicle, or testament — free writing, chapter by chapter, in your own words.</p>
  <div class="grid">
    <div class="card"><h2>Create account</h2><div id="autherr"></div>
      <label>Your name<input id="su-name"></label><label>Email<input id="su-email" type="email"></label>
      <label>Password (6+ characters)<input id="su-pass" type="password"></label>
      <button class="primary" id="su-btn">Create my account</button></div>
    <div class="card"><h2>Sign in</h2>
      <label>Email<input id="si-email" type="email"></label><label>Password<input id="si-pass" type="password"></label>
      <button class="primary" id="si-btn">Sign in</button></div>
  </div>`;
  document.getElementById('su-btn').onclick = async ()=>{
    try { me = await api('/api/signup',{method:'POST',body:JSON.stringify({name:val('su-name'),email:val('su-email'),password:val('su-pass')})}); renderUserbox(); showMyBooks(); }
    catch(e){ errBox('autherr', e.message); }
  };
  document.getElementById('si-btn').onclick = async ()=>{
    try { me = await api('/api/signin',{method:'POST',body:JSON.stringify({email:val('si-email'),password:val('si-pass')})}); renderUserbox(); showMyBooks(); }
    catch(e){ errBox('autherr', e.message); }
  };
}
const val = id => document.getElementById(id).value;
function errBox(id,msg){ document.getElementById(id).innerHTML = `<p class="error">${esc(msg)}</p>`; }

async function showMyBooks(){
  const books = await api('/api/books');
  app.innerHTML = `<h1>My Books</h1><div id="bookerr"></div>
    <div class="card"><h2>Start a new book</h2>
      <label>Title<input id="nb-title"></label>
      <label>Type<select id="nb-type"><option>Memoir</option><option>Legacy Book</option><option>Chronicle</option><option>Testament</option></select></label>
      <label>About this book<textarea id="nb-desc" style="min-height:70px"></textarea></label>
      <button class="primary" id="nb-btn">Create book</button>
      <p class="muted">Free plan: 1 book. Paid plans: unlimited books, PDF export, testament setup.</p></div>
    ${books.map(b=>`<div class="card"><h3>${esc(b.title)}</h3>
      <span class="badge">${esc(b.type)}</span><span class="badge">${esc(b.visibility)}</span><span class="badge">♥ ${b.votes} votes</span>
      ${b.publisher_optin?'<span class="badge">Open to publishers</span>':''}
      <p>${esc(b.description)}</p>
      <button class="ghost" onclick="openEditor(${b.id})">Write / Edit</button>
      <button class="ghost" onclick="openReader(${b.id})">Read</button>
      <button class="ghost" onclick="downloadPdf(${b.id},this)">PDF export</button>
      <button class="ghost danger" onclick="deleteBook(${b.id})">Delete</button></div>`).join('') || '<p class="muted">No books yet.</p>'}`;
  document.getElementById('nb-btn').onclick = async ()=>{
    try { await api('/api/books',{method:'POST',body:JSON.stringify({title:val('nb-title'),type:val('nb-type'),description:val('nb-desc')})}); showMyBooks(); }
    catch(e){ errBox('bookerr', e.message + (e.status===402 ? ' — see Pricing to upgrade.' : '')); }
  };
}
window.deleteBook = async id => { if (confirm('Delete this book and all its chapters?')) { await api(`/api/books/${id}`,{method:'DELETE'}); showMyBooks(); } };
window.downloadPdf = async (id,btn) => {
  const r = await fetch(`/api/books/${id}/pdf`);
  if (!r.ok) { alert('PDF export is a paid-plan feature. Upgrade on the Pricing page.'); showPricing(); return; }
  const blob = await r.blob(); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='remora-book.pdf'; a.click();
};

async function openEditor(id){
  const b = await api(`/api/books/${id}`);
  app.innerHTML = `<button class="ghost" onclick="showMyBooks()">← My Books</button>
  <h1>${esc(b.title)}</h1><div id="ederr"></div>
  <div class="card"><h2>Book settings & sharing</h2>
    <label>Title<input id="bs-title" value="${esc(b.title)}"></label>
    <label>Sharing<select id="bs-vis">
      ${['private','family','public','testament'].map(v=>`<option ${b.visibility===v?'selected':''}>${v}</option>`).join('')}</select></label>
    <label>Family emails (comma-separated, for Family sharing)<input id="bs-family" value="${esc(b.family_emails)}"></label>
    <label>Testament recipients (paid feature)<input id="bs-test" value="${esc(b.testament_recipients)}"></label>
    <label>Testament release note<textarea id="bs-note" style="min-height:60px">${esc(b.release_note)}</textarea></label>
    <label><input type="checkbox" id="bs-pub" style="width:auto" ${b.publisher_optin?'checked':''}> Open to publishers (public books only — readers vote, top stories can be offered to publishers)</label><br>
    <button class="primary" id="bs-save">Save settings</button></div>
  <div class="card"><h2>Chapters — free writing</h2>
    ${b.chapters.map(c=>`<div class="card"><label>Chapter title<input id="ct-${c.id}" value="${esc(c.title)}"></label>
      <label>Visibility<select id="cv-${c.id}">${['inherit','private','family','public','testament'].map(v=>`<option ${c.visibility===v?'selected':''}>${v}</option>`).join('')}</select></label>
      <textarea id="cb-${c.id}">${esc(c.body)}</textarea>
      <button class="ghost" onclick="saveChapter(${c.id})">Save chapter</button>
      <button class="ghost danger" onclick="deleteChapter(${c.id},${id})">Delete chapter</button></div>`).join('')}
    <label>New chapter title<input id="nc-title"></label><textarea id="nc-body" placeholder="Write freely…"></textarea>
    <button class="primary" id="nc-btn">Add chapter</button></div>
  <div class="card"><h2>Photos, voice & media</h2>
    ${b.media.map(m=> m.kind==='voice_transcript' ? `<p>🎙 Transcript: ${esc(m.transcript)}</p>` : m.kind==='audio' ? `<p>🎙 <audio controls src="${m.url}"></audio></p>` : `<img class="media" src="${m.url}" alt="${esc(m.original_name)}">`).join('')}
    <label>Add a photo or voice/audio file<input id="md-file" type="file"></label>
    <label>Kind<select id="md-kind"><option value="photo">photo</option><option value="audio">audio</option></select></label>
    <button class="ghost" id="md-btn">Upload file</button>
    <label>…or save a voice note as a transcript<textarea id="md-trans" style="min-height:60px"></textarea></label>
    <button class="ghost" id="md-trans-btn">Save voice transcript</button></div>
  <div class="card"><h2>Chronicle / Timeline</h2>
    ${b.timeline.map(t=>`<p><strong>${esc(t.date_text)}</strong> — ${esc(t.event_text)}</p>`).join('')}
    <label>Date / period<input id="tl-date" placeholder="e.g. Summer 1998"></label>
    <label>What happened<input id="tl-event"></label><button class="ghost" id="tl-btn">Add timeline entry</button></div>
  <div class="card"><h2>Letters</h2>
    ${b.letters.map(l=>`<p><strong>To ${esc(l.recipient_name)}:</strong> ${esc(l.body)}</p>`).join('')}
    <label>To (name)<input id="lt-to"></label><label>Letter<textarea id="lt-body"></textarea></label>
    <button class="ghost" id="lt-btn">Add letter</button></div>
  <p><button class="ghost" onclick="openReader(${id})">Read this book →</button> <a href="/api/books/${id}/pdf">Download PDF (paid plans)</a></p>`;
  document.getElementById('bs-save').onclick = async ()=>{
    try { await api(`/api/books/${id}`,{method:'PUT',body:JSON.stringify({title:val('bs-title'),visibility:val('bs-vis'),family_emails:val('bs-family'),testament_recipients:val('bs-test'),release_note:val('bs-note'),publisher_optin:document.getElementById('bs-pub').checked})}); openEditor(id); }
    catch(e){ errBox('ederr', e.message + (e.status===402 ? ' — see Pricing to upgrade.' : '')); }
  };
  document.getElementById('nc-btn').onclick = async ()=>{ await api(`/api/books/${id}/chapters`,{method:'POST',body:JSON.stringify({title:val('nc-title'),body:val('nc-body')})}); openEditor(id); };
  document.getElementById('md-btn').onclick = async ()=>{
    const f = document.getElementById('md-file').files[0]; if (!f) return alert('Choose a file first');
    const fd = new FormData(); fd.append('kind', val('md-kind')); fd.append('file', f);
    const r = await fetch(`/api/books/${id}/media`,{method:'POST',body:fd}); if (!r.ok) return alert('Upload failed'); openEditor(id);
  };
  document.getElementById('md-trans-btn').onclick = async ()=>{
    const fd = new FormData(); fd.append('kind','voice_transcript'); fd.append('transcript', val('md-trans'));
    const r = await fetch(`/api/books/${id}/media`,{method:'POST',body:fd}); if (!r.ok) return alert('Save failed'); openEditor(id);
  };
  document.getElementById('tl-btn').onclick = async ()=>{ await api(`/api/books/${id}/timeline`,{method:'POST',body:JSON.stringify({date_text:val('tl-date'),event_text:val('tl-event')})}); openEditor(id); };
  document.getElementById('lt-btn').onclick = async ()=>{ await api(`/api/books/${id}/letters`,{method:'POST',body:JSON.stringify({recipient_name:val('lt-to'),body:val('lt-body')})}); openEditor(id); };
}
window.openEditor = openEditor;
window.saveChapter = async cid => { await api(`/api/chapters/${cid}`,{method:'PUT',body:JSON.stringify({title:val('ct-'+cid),body:val('cb-'+cid),visibility:val('cv-'+cid)})}); alert('Chapter saved'); };
window.deleteChapter = async (cid,bid) => { if (confirm('Delete chapter?')) { await api(`/api/chapters/${cid}`,{method:'DELETE'}); openEditor(bid); } };

window.openReader = async id => {
  try {
    const b = await api(`/api/books/${id}`);
    app.innerHTML = `<button class="ghost" onclick="showDiscover()">← Discover</button>
    <h1>${esc(b.title)}</h1><p class="muted">by ${esc(b.author_name||'you')} · ${esc(b.type)} · ♥ ${b.votes} votes ${b.publisher_optin?'· Open to publishers':''}</p>
    <p>${esc(b.description)}</p>
    <button class="primary" id="vote-btn" ${b.my_vote?'disabled':''}>${b.my_vote?'You voted ♥':'Vote for this story'}</button>
    ${b.chapters.map(c=>`<div class="card"><h2>${esc(c.title)}</h2><div class="prose">${esc(c.body)}</div></div>`).join('')}
    ${b.timeline.length?`<div class="card"><h2>Chronicle</h2>${b.timeline.map(t=>`<p><strong>${esc(t.date_text)}</strong> — ${esc(t.event_text)}</p>`).join('')}</div>`:''}
    ${b.media.filter(m=>m.kind==='photo').map(m=>`<img class="media" src="${m.url}">`).join('')}`;
    document.getElementById('vote-btn').onclick = async ()=>{ try { await api(`/api/books/${id}/vote`,{method:'POST'}); openReader(id); } catch(e){ alert(e.message); } };
  } catch(e){ app.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
};

async function showDiscover(){
  const books = await api('/api/discover');
  app.innerHTML = `<h1>Discover — public stories</h1><p class="muted">Sorted by votes. Vote for the real stories you want to see published.</p>
  ${books.map(b=>`<div class="card"><h3>${esc(b.title)}</h3><span class="badge">${esc(b.type)}</span><span class="badge">by ${esc(b.author_name)}</span><span class="badge">♥ ${b.votes}</span>${b.publisher_optin?'<span class="badge">Open to publishers</span>':''}<p>${esc(b.description)}</p><button class="ghost" onclick="openReader(${b.id})">Read</button></div>`).join('') || '<p class="muted">No public books yet.</p>'}`;
}
async function showPublishers(){
  const books = await api('/api/publishers');
  app.innerHTML = `<h1>For Publishers</h1><p class="muted">Public stories whose authors opted in, ranked by reader votes. A sale requires the author's explicit per-book deal — Remora takes a platform commission, the author keeps the majority.</p>
  ${books.map(b=>`<div class="card"><h3>${esc(b.title)}</h3><span class="badge">♥ ${b.votes} votes</span><span class="badge">by ${esc(b.author_name)}</span><p>${esc(b.description)}</p><button class="ghost" onclick="openReader(${b.id})">Read</button></div>`).join('') || '<p class="muted">No opted-in stories yet.</p>'}`;
}
async function showPricing(){
  const plans = await api('/api/plans');
  app.innerHTML = `<h1>Pricing</h1><div id="prerr"></div><p class="muted">Checkout here is simulated for the prototype — no real payment is taken. Stripe powers real payments at launch.</p>
  <div class="grid">${plans.map(p=>`<div class="card"><h3>${esc(p.name)}</h3><p class="price">${esc(p.price)}</p>
    <ul>${p.features.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
    ${me && me.id ? `<button class="primary" onclick="buyPlan('${p.id}')">${me.plan===p.id?'Current plan':'Choose '+esc(p.name)}</button>` : '<p class="muted">Sign in to choose a plan.</p>'}</div>`).join('')}</div>`;
}
window.buyPlan = async plan => { try { const r = await api('/api/checkout',{method:'POST',body:JSON.stringify({plan})}); me.plan = r.user.plan; renderUserbox(); showPricing(); alert('Simulated checkout complete — plan is now: '+me.plan); } catch(e){ alert(e.message); } };
window.showMyBooks = showMyBooks; window.showDiscover = showDiscover; window.showPricing = showPricing;

(async ()=>{ try { const m = await api('/api/me'); me = (m && m.id) ? m : null; } catch(e){ me=null; } renderUserbox(); route('mybooks'); })();
