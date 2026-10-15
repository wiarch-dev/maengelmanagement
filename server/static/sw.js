// MAEMA – Service Worker: App-Hülle, Pläne und Fotos offline verfügbar (nur https/localhost)
// Offline-Start: '/' kommt aus dem Cache, Daten (JSON) kommen aus der App-eigenen IndexedDB.
const CACHE='maema-v3';
const SHELL=['/','/api/logo','/static/manifest.json','/static/icon-192.png','/static/icon-512.png','/static/icon-180.png'];
self.addEventListener('install',e=>{ e.waitUntil(caches.open(CACHE).then(c=>Promise.all(SHELL.map(u=>c.add(u).catch(()=>{})))).then(()=>self.skipWaiting())); });
self.addEventListener('activate',e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())); });
self.addEventListener('message',e=>{ if(e.data&&e.data.type==='precache'&&Array.isArray(e.data.urls)){ // Fotos/Pläne vorab laden (von der App angestossen)
    e.waitUntil(caches.open(CACHE).then(async c=>{ for(const u of e.data.urls){ try{ if(!(await c.match(u))){ const r=await fetch(u,{credentials:'same-origin'}); if(r.ok) await c.put(u,r); } }catch(err){} } })); } });
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url); if(e.request.method!=='GET'||u.origin!==location.origin) return;
  const isShell=u.pathname==='/'||u.pathname.startsWith('/static/')||u.pathname==='/api/logo';
  const isFile=u.pathname.startsWith('/api/plans/')||u.pathname.startsWith('/api/photos/')||u.pathname.startsWith('/api/backups/');
  if(u.pathname==='/'){
    // App-Seite: Netz zuerst (damit Updates ankommen), sonst Cache -> Offline-Start
    e.respondWith(caches.open(CACHE).then(async c=>{ try{ const r=await fetch(e.request); if(r.ok) c.put('/',r.clone()); return r; }catch(err){ return (await c.match('/'))||Response.error(); } }));
  } else if(isShell||(isFile&&!u.pathname.startsWith('/api/backups/'))){
    // Cache zuerst, im Hintergrund aktualisieren (Pläne haben ?v=, Fotos ändern sich selten)
    e.respondWith(caches.open(CACHE).then(async c=>{ const hit=await c.match(e.request); const net=fetch(e.request).then(r=>{ if(r.ok) c.put(e.request,r.clone()); return r; }).catch(()=>hit); return hit||net; }));
  } else if(u.pathname.startsWith('/api/')){
    // Daten: nur Netz (die App hält ihren eigenen Offline-Stand in IndexedDB)
    return;
  }
});
