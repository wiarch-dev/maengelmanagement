// MängelManagement – Service Worker: App-Hülle, Pläne und Fotos offline verfügbar (nur https/localhost)
const CACHE='mm-v1';
self.addEventListener('install',e=>{ e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/api/logo'])).then(()=>self.skipWaiting())); });
self.addEventListener('activate',e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())); });
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url); if(e.request.method!=='GET') return;
  if(u.pathname==='/'||u.pathname.startsWith('/api/plans/')||u.pathname.startsWith('/api/photos/')||u.pathname==='/api/logo'){
    // Cache zuerst, im Hintergrund aktualisieren (Pläne/Fotos ändern sich selten; Pläne haben ?v=)
    e.respondWith(caches.open(CACHE).then(async c=>{ const hit=await c.match(e.request); const net=fetch(e.request).then(r=>{ if(r.ok) c.put(e.request,r.clone()); return r; }).catch(()=>hit); return hit||net; }));
  } else if(u.pathname.startsWith('/api/')){
    // Daten: Netz zuerst, sonst letzter Stand aus dem Cache
    e.respondWith(caches.open(CACHE).then(async c=>{ try{ const r=await fetch(e.request); if(r.ok) c.put(e.request,r.clone()); return r; }catch(err){ const hit=await c.match(e.request); return hit||new Response(JSON.stringify({detail:'offline'}),{status:503,headers:{'Content-Type':'application/json'}}); } }));
  }
});
