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
  if (name==='account') return me && me.id ? showAccount() : showAuth();
  return me && me.id ? showMyBooks() : showAuth();
}
function showAuth(){
  app.innerHTML = `<figure class="hero"><img class="hero-img" src="/static/img/hero-family.jpg" alt="Three generations of one family laughing together around the kitchen table">
  <figcaption class="hero-caption"><h1>Write the book of your life.</h1></figcaption></figure>
  <p>Viavios is where anybody can make their own memoir, legacy book, chronicle, testament, or photo story — in your own words, your own pictures, or your own voice.</p>
  <div class="grid">
    <div class="card" id="create-card"><h2>Create account</h2><div id="autherr"></div>
      <label>Your name<input id="su-name"></label><label>Email<input id="su-email" type="email"></label>
      <label>Password (6+ characters)<input id="su-pass" type="password"></label>
      <button class="primary" id="su-btn">Create my account</button></div>
    <div class="card"><h2>Sign in</h2>
      <label>Email<input id="si-email" type="email"></label><label>Password<input id="si-pass" type="password"></label>
      <button class="primary" id="si-btn">Sign in</button></div>
  </div>
  <h2 style="margin-top:30px">Stories people are writing</h2>
  <div id="landing-stories"><p class="muted">Loading stories…</p></div>
  <div class="paths"><h2>You don't have to be a writer</h2>
  <p>There are three ways to tell your story on Viavios. Pick the one that feels easy.</p>
  <div class="grid">
    <div class="card"><h3>Write it</h3><p>Chapter by chapter, in your own words — a little at a time is fine.</p></div>
    <div class="card"><h3>Photograph it</h3><p>Build a Photo Story from your pictures — your family, your childhood, the things you have collected and kept. A few words under each photo is enough.</p></div>
    <div class="card"><h3>Say it</h3><p>Record your voice telling it, in the language you speak at home. Your voice becomes your book.</p></div>
  </div>
  <p class="magazine-line">However you tell it, your story becomes your own magazine of your life — a real book your family keeps.</p>
  <div class="landing-cta"><button class="primary" id="cta-paths">Begin your story — create your free account</button></div></div>
  <div class="landing-cta"><p><strong>Your life is a story too — start writing yours.</strong></p>
  <button class="primary" id="cta-write">Start writing — create your free account</button></div>`;
  document.getElementById('su-btn').onclick = async ()=>{
    try { me = await api('/api/signup',{method:'POST',body:JSON.stringify({name:val('su-name'),email:val('su-email'),password:val('su-pass')})}); renderUserbox(); showMyBooks(); }
    catch(e){ errBox('autherr', e.message); }
  };
  document.getElementById('si-btn').onclick = async ()=>{
    try { me = await api('/api/signin',{method:'POST',body:JSON.stringify({email:val('si-email'),password:val('si-pass')})}); renderUserbox(); showMyBooks(); }
    catch(e){ errBox('autherr', e.message); }
  };
  const goCreate = ()=>{
    document.getElementById('create-card').scrollIntoView({behavior:'smooth',block:'center'});
    document.getElementById('su-name').focus({preventScroll:true});
  };
  document.getElementById('cta-write').onclick = goCreate;
  document.getElementById('cta-paths').onclick = goCreate;
  loadLandingStories();
}
// Landing-page stories: real public books from /api/discover first; clearly
// labeled sample stories only fill the row when there are fewer than 3 real ones.
const IMG = {
  coupleHome:'/static/img/story-couple-home.jpg',
  womanHome:'/static/img/story-woman-home.jpg',
  manReading:'/static/img/story-man-reading.jpg',
  couplePorch:'/static/img/story-couple-porch.jpg',
  album:'/static/img/story-grandparents-album.jpg',
  community:'/static/img/story-community-table.jpg',
  blackCouple:'/static/img/story-couple-black-home.jpg',
  familyBlackAlbum:'/static/img/story-family-black-album.jpg',
  familyLatina:'/static/img/story-family-latina-kitchen.jpg',
  asianCouple:'/static/img/story-couple-asian.jpg'
};
// Default cover per book type. Two fitting photos per type, picked by a hash
// of the book id, so Discover shows a genuinely mixed set of faces instead of
// the same photograph on every book.
const TYPE_IMGS = {
  'Memoir':[IMG.coupleHome, IMG.blackCouple],
  'Legacy Book':[IMG.album, IMG.familyBlackAlbum],
  'Chronicle':[IMG.manReading, IMG.asianCouple],
  'Testament':[IMG.community, IMG.familyLatina],
  'Photo Story':[IMG.couplePorch, IMG.familyLatina]
};
function typeImg(type, seed){
  const arr = TYPE_IMGS[type] || [IMG.coupleHome, IMG.blackCouple];
  const s = String(seed ?? type ?? '');
  let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return arr[h % arr.length];
}
const WRITTEN_FOR = {
  'Memoir':'Written to be kept — so the people who love them know the whole story, in their own words.',
  'Legacy Book':'Written for their children and grandchildren, so they know where they come from.',
  'Chronicle':'Written year by year, for everyone who was there — and for everyone who comes after.',
  'Testament':'Left for the people named inside it, to be opened when the time comes.',
  'Photo Story':'Told in pictures, for the family — every face named, every place remembered.'
};
const SAMPLE_STORIES = [
  {title:'Growing Up Above the Bakery', type:'Memoir', author:'Elena R.', img:IMG.coupleHome, inside:[IMG.womanHome, IMG.album],
   about:'Elena R. is 74. She started behind the bakery counter at nine years old, standing on a flour crate to reach the till, and she still makes her father\u2019s cardamom rolls every December.',
   writtenFor:'Written for her daughter, and for the grandchildren who think the smell of warm bread is just what Grandma\u2019s house smells like.',
   chapters:['The Flour Crate', 'The Winter We Almost Lost the Shop', 'What My Father Taught the Town'],
   opening:'Every morning of my childhood started at four o\u2019clock, and it did not start with an alarm. It started with the floor. The boards under my bed would warm up, just a little, and the smell would come through them — yeast and butter and the first trays of bread — and I knew my father was already downstairs, moving in the dark like a man in a church. I was nine the year he put the flour crate behind the counter so I could reach the till. \u201cElena,\u201d he said, \u201ca family that feeds a town can never really be poor. Remember that when it matters.\u201d It mattered sooner than either of us expected. The winter I turned twelve, the mill raised its prices, the oven cracked, and the bank sent a man in a good coat to stand in our doorway and be polite at us.',
   snap:'Every morning of my childhood started at 4 a.m. with the smell of bread coming up through the floorboards. My father said a family that feeds a town can never really be poor — this is the story of the winter we almost lost the shop, and the neighbors who would not let us.'},
  {title:'Letters to My Grandchildren', type:'Legacy Book', author:'Walter J.', img:IMG.familyBlackAlbum, inside:[IMG.blackCouple],
   about:'Walter J. is 81, a retired merchant seaman who crossed the Atlantic more than forty times and now lives in the house in Maine where he was born.',
   writtenFor:'Written for his grandchildren, so they know where they come from — and for Margaret, who kept every letter he ever sent her.',
   chapters:['The Ship and the Storm of \u201968', 'Two Years of Letters', 'The Quiet Man at the End of the Table'],
   opening:'My grandchildren know me as the quiet man at the end of the table, the one who carves the turkey and falls asleep during the football. They do not know that at nineteen I was standing a night watch in the North Atlantic, in a storm that took two men off a ship ahead of ours, holding a rail with both hands and promising God a list of things I have mostly kept. They do not know I wrote to their grandmother every Sunday for two years before she agreed to marry me, or that she kept all ninety-six letters in a biscuit tin. I am writing this book because the remembering should not be left to other people. If you are reading it, I did my part. The rest — the remembering, the retelling — is yours now.',
   snap:'I am 81, and my grandchildren know me as the quiet man at the end of the table. They do not know about the ship, the storm of \u201968, or the woman I wrote letters to for two years before I married her. I am writing it all down before the remembering is left to other people.'},
  {title:'Fifty Years on Maple Street', type:'Chronicle', author:'Ruth & Daniel M.', img:IMG.manReading, inside:[IMG.asianCouple, IMG.couplePorch],
   about:'Ruth and Daniel M. bought the little blue house on Maple Street in 1968 for $14,500. Ruth kept a notebook by the telephone for fifty years. This book is that notebook, finished.',
   writtenFor:'Written for everyone who ever lived on Maple Street — and for the kids who grew up there and moved away, so the street they remember still exists somewhere.',
   chapters:['1968: The Year We Moved In', 'The Blackout Summer', 'Every Wedding, Every Goodbye'],
   opening:'We moved onto Maple Street in the October of 1968, with a borrowed truck, a new baby, and a house payment of ninety-one dollars a month. Mrs. Abernathy from number 12 was on our porch before the truck was unloaded, holding a casserole and the whole history of the street, which she delivered in that order. Daniel says I wrote the first entry in the notebook that night. I don\u2019t remember writing it, but there it is, in my hand: \u201cAbernathys — casserole people. Good people.\u201d Fifty years of entries followed — every block party and blackout, every wedding on the church steps, every ambulance that came in the night and every baby that came home in the morning. A chronicle is not the big moments. It is proof that an ordinary street was somebody\u2019s whole world.',
   snap:'One house, one street, fifty years — every block party, blackout, wedding and goodbye, written year by year as it happened. A chronicle is not the big moments. It is proof that an ordinary street was somebody\u2019s whole world.'}
];
function makeSnap(text, max=240){
  const t = String(text ?? '').replace(/\s+/g,' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const end = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '));
  if (end > 80) return cut.slice(0, end+1);
  const sp = cut.lastIndexOf(' ');
  return (sp > 80 ? cut.slice(0, sp) : cut) + '…';
}
function bookPhoto(detail, type, seed){
  const photos = ((detail && detail.media) || []).filter(m => m.kind === 'photo' && m.url);
  return photos.length ? photos[0].url : typeImg(type, seed ?? (detail && detail.id));
}
function realStoryCard(b, snap, img){
  return `<div class="card story-card" onclick="openGlanceReal(${b.id})" title="Take a look inside">
    <img class="story-photo" src="${esc(img || typeImg(b.type, b.id))}" alt="Photograph from ${esc(b.title)}">
    <h3>${esc(b.title)}</h3>
    <span class="badge">${esc(b.type)}</span><span class="badge">by ${esc(b.author_name || 'a Viavios writer')}</span><span class="badge">♥ ${b.votes || 0} votes</span>${b.publisher_optin ? '<span class="badge">Open to publishers</span>' : ''}
    <p class="story-snap">${esc(snap)}</p>
    <p class="glance-link">Take a look inside →</p></div>`;
}
function sampleStoryCard(s, i){
  return `<div class="card story-card" onclick="openGlanceSample(${i})" title="Take a look inside">
    <img class="story-photo" src="${esc(s.img)}" alt="Photograph for ${esc(s.title)}">
    <h3>${esc(s.title)}</h3>
    <span class="badge">${esc(s.type)}</span><span class="badge">by ${esc(s.author)}</span><span class="badge sample">Sample story</span>
    <p class="story-snap">${esc(s.snap)}</p>
    <p class="glance-link">Take a look inside →</p></div>`;
}
const GLANCE_CACHE = {};
async function loadLandingStories(){
  const box = document.getElementById('landing-stories');
  if (!box) return;
  let real = [];
  try { real = (await api('/api/discover') || []).slice(0, 6); } catch(e){ real = []; }
  const cards = [];
  for (const b of real) {
    let snap = makeSnap(b.description);
    let detail = null;
    try { detail = await api(`/api/books/${b.id}`); GLANCE_CACHE[b.id] = detail; } catch(e){ /* glance will refetch */ }
    if (snap.length < 40 && detail) {
      const ch = (detail.chapters || []).find(c => c.body && c.body.trim());
      if (ch) snap = makeSnap(ch.body) || snap;
    }
    if (!snap) snap = 'A true story, written chapter by chapter on Viavios.';
    cards.push(realStoryCard(b, snap, bookPhoto(detail, b.type, b.id)));
  }
  for (let i = 0; cards.length < 3 && i < SAMPLE_STORIES.length; i++) cards.push(sampleStoryCard(SAMPLE_STORIES[i], i));
  box.innerHTML = `<div class="grid">${cards.join('')}</div>`;
}
// ---------- Glance inside the book ----------
// A peek, never the book: cover photo, who wrote it and who it is for, the
// chapter list, and the opening of chapter one. Full reading keeps the
// existing sharing rules.
function firstWords(text, n){
  const words = String(text ?? '').replace(/\s+/g,' ').trim().split(' ').filter(Boolean);
  return words.slice(0, n).join(' ') + (words.length > n ? '…' : '');
}
function closeGlance(){ const o = document.getElementById('glance-overlay'); if (o) o.remove(); }
window.closeGlance = closeGlance;
function renderGlance(g){
  closeGlance();
  const el = document.createElement('div');
  el.id = 'glance-overlay'; el.className = 'glance-overlay';
  el.innerHTML = `<div class="glance">
    <button class="ghost glance-close" onclick="closeGlance()">✕ Close</button>
    <img class="glance-cover" src="${esc(g.cover)}" alt="Cover photograph for ${esc(g.title)}">
    <h2>${esc(g.title)}</h2>
    <p class="glance-meta"><span class="badge">${esc(g.type)}</span><span class="badge">by ${esc(g.author)}</span>${g.votes != null ? `<span class="badge">♥ ${g.votes} votes</span>` : ''}${g.sample ? '<span class="badge sample">Sample story</span>' : ''}</p>
    <p class="glance-about">${esc(g.about)}</p>
    <p class="glance-for"><em>${esc(g.writtenFor)}</em></p>
    <h3>What's inside</h3>
    <ul class="glance-chapters">${g.chapters.map(t => `<li>${esc(t)}</li>`).join('') || '<li>Chapters are being written…</li>'}</ul>
    <h3>The opening</h3>
    <div class="prose glance-excerpt">${esc(g.excerpt)}</div>
    ${g.inside && g.inside.length ? `<div class="glance-inside">${g.inside.map(u => `<img src="${esc(u)}" alt="A photograph from inside the book">`).join('')}</div>` : ''}
    <p class="muted glance-note">This is a look inside — a beginning, not the whole book.</p>
    ${g.bookId ? `<button class="primary" onclick="closeGlance();openReader(${g.bookId})">Read the whole story</button>` : `<button class="primary" onclick="closeGlance();document.getElementById('create-card') && document.getElementById('create-card').scrollIntoView({behavior:'smooth',block:'center'})">Start your own story</button>`}
  </div>`;
  el.addEventListener('click', e => { if (e.target === el) closeGlance(); });
  document.body.appendChild(el);
}
window.openGlanceSample = i => {
  const s = SAMPLE_STORIES[i];
  renderGlance({cover:s.img, title:s.title, type:s.type, author:s.author, about:s.about,
    writtenFor:s.writtenFor, chapters:s.chapters, excerpt:firstWords(s.opening, 120),
    inside:s.inside, sample:true});
};
window.openGlanceReal = async id => {
  let d = GLANCE_CACHE[id];
  if (!d) { try { d = await api(`/api/books/${id}`); GLANCE_CACHE[id] = d; } catch(e){ alert('That book could not be opened.'); return; } }
  const photos = (d.media || []).filter(m => m.kind === 'photo' && m.url).map(m => m.url);
  const cover = photos[0] || typeImg(d.type, d.id);
  const inside = photos.slice(1, 3);
  if (!inside.length) inside.push(...[typeImg(d.type, d.id), IMG.familyBlackAlbum, IMG.album].filter(u => u !== cover).slice(0, 2));
  const chap = (d.chapters || []).find(c => c.body && c.body.trim());
  renderGlance({cover, title:d.title, type:d.type, author:d.author_name || 'a Viavios writer',
    about: d.description ? d.description : `${d.author_name || 'The author'} is writing this ${String(d.type).toLowerCase()} on Viavios, a little at a time, in their own words and pictures.`,
    writtenFor: WRITTEN_FOR[d.type] || WRITTEN_FOR['Memoir'],
    chapters:(d.chapters || []).map(c => c.title),
    excerpt: chap ? firstWords(chap.body, 120) : 'The first chapter is still being written.',
    inside, votes:d.votes, bookId: (me && me.id) ? id : null});
};
const val = id => document.getElementById(id).value;
function errBox(id,msg){ document.getElementById(id).innerHTML = `<p class="error">${esc(msg)}</p>`; }

async function showMyBooks(){
  const books = await api('/api/books');
  app.innerHTML = `<h1>My Books</h1><div id="bookerr"></div>
    <div class="card"><h2>Start a new book</h2>
      <label>Title<input id="nb-title"></label>
      <label>Type<select id="nb-type"><option>Memoir</option><option>Legacy Book</option><option>Chronicle</option><option>Testament</option><option>Photo Story</option></select></label>
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
  const cards = [];
  for (const b of books) {
    let detail = null;
    try { detail = await api(`/api/books/${b.id}`); GLANCE_CACHE[b.id] = detail; } catch(e){ /* default photo */ }
    cards.push(`<div class="card story-card" onclick="openGlanceReal(${b.id})" title="Take a look inside"><img class="story-photo" src="${esc(bookPhoto(detail, b.type, b.id))}" alt="Photograph from ${esc(b.title)}"><h3>${esc(b.title)}</h3><span class="badge">${esc(b.type)}</span><span class="badge">by ${esc(b.author_name)}</span><span class="badge">♥ ${b.votes}</span>${b.publisher_optin?'<span class="badge">Open to publishers</span>':''}<p>${esc(b.description)}</p><p class="glance-link">Take a look inside →</p><button class="ghost" onclick="event.stopPropagation();openReader(${b.id})">Read</button></div>`);
  }
  app.innerHTML = `<h1>Discover — public stories</h1><p class="muted">Sorted by votes. Vote for the real stories you want to see published. Tap a story for a look inside the book.</p>
  ${cards.join('') || '<p class="muted">No public books yet.</p>'}`;
}
async function showPublishers(){
  const books = await api('/api/publishers');
  app.innerHTML = `<h1>For Publishers</h1><p class="muted">Public stories whose authors opted in, ranked by reader votes. A sale requires the author's explicit per-book deal — Viavios takes a platform commission, the author keeps the majority.</p>
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
const EMAIL_KINDS = {welcome:'Welcome', next_steps:'Getting started', payment_receipt:'Payment receipt', account_updated:'Account update', account_cancelled:'Account closed', app_update:'Viavios news'};
async function showAccount(){
  app.innerHTML = `<h1>Your account</h1><div id="accerr"></div>
  <div class="grid">
    <div class="card"><h3>Profile</h3>
      <label>Your name<input id="ac-name" value="${esc(me.name)}"></label>
      <label>Email<input value="${esc(me.email)}" disabled></label>
      <p class="muted">Plan: ${esc(me.plan)}</p>
      <button class="primary" id="ac-save">Save changes</button></div>
    <div class="card"><h3>Change password</h3>
      <label>Current password<input id="ac-cur" type="password"></label>
      <label>New password (6+ characters)<input id="ac-new" type="password"></label>
      <button class="primary" id="ac-pass">Change password</button></div>
  </div>
  <div class="card" style="margin-top:18px"><h3>Emails we've sent you</h3><div id="ac-emails"><p class="muted">Loading…</p></div>
    <p class="muted">“Stored” means the email was created and kept safely in your account history; once a sending service is connected, these arrive in your inbox as well.</p></div>
  <div class="card" style="margin-top:18px"><h3>Close account</h3>
    <p>Closing your account deletes your books, chapters, photos, and letters. This cannot be undone. We will email you a confirmation.</p>
    <label>Confirm your password<input id="ac-del-pass" type="password"></label>
    <button id="ac-del">Close my account</button></div>`;
  document.getElementById('ac-save').onclick = async ()=>{
    try { me = await api('/api/me',{method:'PATCH',body:JSON.stringify({name:val('ac-name')})}); renderUserbox(); showAccount(); alert('Saved. A confirmation email is in your account history.'); }
    catch(e){ errBox('accerr', e.message); }
  };
  document.getElementById('ac-pass').onclick = async ()=>{
    try { await api('/api/me',{method:'PATCH',body:JSON.stringify({current_password:val('ac-cur'),new_password:val('ac-new')})}); showAccount(); alert('Password changed. A confirmation email is in your account history.'); }
    catch(e){ errBox('accerr', e.message); }
  };
  document.getElementById('ac-del').onclick = async ()=>{
    if (!confirm('Close your account and delete all your books? This cannot be undone.')) return;
    try { await api('/api/me',{method:'DELETE',body:JSON.stringify({password:val('ac-del-pass')})}); me=null; renderUserbox(); showAuth(); alert('Your account is closed. A confirmation email was sent.'); }
    catch(e){ errBox('accerr', e.message); }
  };
  try {
    const rows = await api('/api/me/emails');
    document.getElementById('ac-emails').innerHTML = rows.length
      ? `<ul>${rows.map(r=>`<li><strong>${esc(EMAIL_KINDS[r.kind]||r.kind)}</strong> — ${esc(r.subject)} <span class="muted">(${esc(r.status)}, ${esc((r.created_at||'').slice(0,10))})</span></li>`).join('')}</ul>`
      : '<p class="muted">No emails yet.</p>';
  } catch(e){ document.getElementById('ac-emails').innerHTML = '<p class="muted">Could not load email history.</p>'; }
}
window.showAccount = showAccount;
window.showMyBooks = showMyBooks; window.showDiscover = showDiscover; window.showPricing = showPricing;

(async ()=>{ try { const m = await api('/api/me'); me = (m && m.id) ? m : null; } catch(e){ me=null; } renderUserbox(); route('mybooks'); })();
