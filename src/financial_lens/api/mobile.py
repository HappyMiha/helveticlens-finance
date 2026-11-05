"""Phone upload: a small installable web app (PWA) served by the local API.

Pair a phone once from the desktop (QR code with a one-time device token);
afterwards the phone camera uploads receipts straight into the ledger over the
local network. The phone gets only this upload page: every other API route
stays reachable from this machine only.
"""

from __future__ import annotations

import hashlib
import secrets
import socket
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..service import FinancialLens

router = APIRouter()
PUBLIC_PATHS = ("/m", "/health", "/mobile/v1/")


def lan_address() -> str:
    """This machine's address on the local network (no packet is sent)."""
    from .. import privacy

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        privacy._original_connect(s, ("192.168.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def pair_device(lens: FinancialLens, name: str, base_url: Optional[str] = None, port: int = 8765) -> dict:
    lens.authorize("configure")
    token = secrets.token_urlsafe(32)
    did = str(uuid.uuid4())
    with lens.db.transaction():
        lens.db.execute("INSERT INTO device_tokens (id, organization_id, name, token_sha256, created_by) VALUES (%s,%s,%s,%s,%s)",
                        (did, lens.org, name, hashlib.sha256(token.encode()).hexdigest(), lens.actor))
        lens._audit("pair_device", "device", did, {"name": name})
    base = base_url or f"http://{lan_address()}:{port}"
    return {"id": did, "name": name, "url": f"{base}/m#t={token}", "token": token}


def revoke_device(lens: FinancialLens, device_id: str) -> None:
    lens.authorize("configure")
    with lens.db.transaction():
        lens.db.execute("UPDATE device_tokens SET revoked_at=now() WHERE id=%s AND organization_id=%s", (device_id, lens.org))
        lens._audit("revoke_device", "device", device_id, {})


def devices(lens: FinancialLens) -> list[dict]:
    lens.authorize("read")
    return [lens._json(r) for r in lens.db.execute(
        "SELECT id, name, created_at, last_used_at, revoked_at FROM device_tokens WHERE organization_id=%s ORDER BY created_at",
        (lens.org,)).fetchall()]


def device_for(lens: FinancialLens, token: str) -> Optional[dict]:
    row = lens.db.execute("SELECT * FROM device_tokens WHERE token_sha256=%s AND revoked_at IS NULL",
                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row:
        lens.db.execute("UPDATE device_tokens SET last_used_at=now() WHERE id=%s", (row["id"],))
    return row


def is_local_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("testclient", ""):
        return True
    import ipaddress

    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


async def lan_gate(request: Request, call_next):
    """Phones on the LAN may use the upload page only."""
    path = request.url.path
    public = path in ("/m", "/health") or path.startswith(("/m/", "/mobile/v1/"))  # not "/members" etc.
    if not is_local_client(request) and not public:
        return JSONResponse({"detail": "Only the phone upload page is available from the network."}, status_code=403)
    return await call_next(request)


def make_routes(get_lens):
    @router.get("/m", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @router.get("/m/manifest.webmanifest")
    def manifest() -> Response:
        return Response(MANIFEST, media_type="application/manifest+json")

    @router.get("/m/sw.js")
    def sw() -> Response:
        return Response(SERVICE_WORKER, media_type="text/javascript")

    @router.get("/m/icon.svg")
    def icon() -> Response:
        return Response(ICON, media_type="image/svg+xml")

    @router.post("/m/upload")
    async def upload(files: list[UploadFile], authorization: str = Header(default=""),
                     fl: FinancialLens = Depends(get_lens)) -> dict:
        token = authorization.removeprefix("Bearer ").strip()
        device = device_for(fl, token) if token else None
        if device is None or str(device["organization_id"]) != fl.org:
            raise HTTPException(401, "This phone is not paired, or its access was revoked. Pair it again from the desktop.")
        out = []
        actor = fl.actor
        fl.actor = f"device:{device['name']}"
        try:
            for f in files:
                data = await f.read()
                if len(data) > 25 * 1024 * 1024:
                    out.append({"file": f.filename, "error": "larger than 25 MB"})
                    continue
                ctype = f.content_type if f.content_type not in (None, "", "application/octet-stream") else None
                res = fl.ingest(data, f.filename or "photo.jpg", ctype)
                summary = {"file": f.filename, "type": res.doc_type, "records": len(res.operation_ids),
                           "messages": res.messages}
                if res.operation_ids:
                    d = fl.operation_detail(res.operation_ids[0])
                    summary.update({"amount": d["amount"], "currency": d["currency"], "counterparty": d["counterparty"],
                                    "category": " / ".join(d["category_path"]), "status": d["verification"]})
                out.append(summary)
        finally:
            fl.actor = actor
        return {"device": device["name"], "results": out}

    return router


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Financial Lens · Upload</title>
<link rel="manifest" href="/m/manifest.webmanifest"><link rel="icon" href="/m/icon.svg"><meta name="theme-color" content="#090b0e">
<style>
:root{--bg:#090b0e;--surface:#111418;--line:#343a44;--text:#e6e3e1;--muted:#a7adb5;--ok:#a4d2b7;--warn:#e6c083;--bad:#f2b0a9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 Inter,'Helvetica Neue',Arial,sans-serif;padding:20px}
h1{font-size:22px;margin:4px 0 4px}p{color:var(--muted);margin:0 0 16px}
label.big{display:flex;align-items:center;justify-content:center;min-height:140px;border:1px dashed var(--line);border-radius:16px;
background:var(--surface);font-weight:600;font-size:18px;margin-bottom:12px;text-align:center;padding:16px}
input[type=file]{position:absolute;left:-9999px}button{width:100%;min-height:48px;border-radius:10px;border:1px solid var(--line);
background:var(--surface);color:var(--text);font:inherit;margin-bottom:10px}
.r{border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:10px;background:var(--surface)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}small{color:var(--muted)}
</style></head><body>
<h1>Financial Lens</h1><p id="state">Photograph a receipt or invoice, or choose files. They go straight into your ledger on your computer.</p>
<label class="big" for="cam">📷 Take a photo</label><input id="cam" type="file" accept="image/*" capture="environment" multiple>
<label class="big" for="files" style="min-height:64px;font-size:16px">Choose files (PDF, photos, statements)</label>
<input id="files" type="file" accept="image/*,application/pdf,.heic,.xml,.csv,.xlsx" multiple>
<div id="out" aria-live="polite"></div>
<script>
(function(){
  var h=new URLSearchParams(location.hash.slice(1));
  try{ if(h.get('t')){localStorage.setItem('fl-token',h.get('t'));history.replaceState(null,'',location.pathname);} }catch(e){}
  var token=null; try{token=localStorage.getItem('fl-token');}catch(e){}
  var state=document.getElementById('state'), out=document.getElementById('out');
  if(!token){state.textContent='This phone is not paired yet. On your computer choose “Pair phone” and scan the QR code.';state.className='warn';}
  function esc(s){return String(s==null?'':s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  function send(list){
    if(!list.length)return; var fd=new FormData(); for(var i=0;i<list.length;i++)fd.append('files',list[i],list[i].name);
    var div=document.createElement('div');div.className='r';div.textContent='Uploading '+list.length+' file(s)…';out.prepend(div);
    fetch('/m/upload',{method:'POST',headers:{'Authorization':'Bearer '+token},body:fd}).then(function(r){
      return r.json().then(function(j){ if(!r.ok)throw new Error(j.detail||r.status); return j; });
    }).then(function(j){
      div.innerHTML=j.results.map(function(x){
        if(x.error)return '<div class="bad">'+esc(x.file)+': '+esc(x.error)+'</div>';
        if(!x.records)return '<div class="warn">'+esc(x.file)+' saved · '+esc((x.messages||[]).join(' '))+'</div>';
        return '<div><span class="'+(x.status==='needs_review'?'warn':'ok')+'">●</span> '+esc(x.counterparty)+' · '+esc(x.currency)+' '+esc(x.amount)+
          '<br><small>'+esc(x.category)+' · '+esc(x.status.replace('_',' '))+'</small></div>';
      }).join('');
    }).catch(function(e){div.innerHTML='<span class="bad">'+esc(e.message)+'</span>';});
  }
  ['cam','files'].forEach(function(id){document.getElementById(id).addEventListener('change',function(e){send(e.target.files);e.target.value='';});});
  if('serviceWorker' in navigator){navigator.serviceWorker.register('/m/sw.js').catch(function(){});}
})();
</script></body></html>"""

MANIFEST = """{"name":"Financial Lens Upload","short_name":"Lens Upload","start_url":"/m","display":"standalone",
"background_color":"#090b0e","theme_color":"#090b0e","icons":[{"src":"/m/icon.svg","sizes":"any","type":"image/svg+xml"}]}"""

SERVICE_WORKER = "self.addEventListener('fetch', function(){});"

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="8" fill="#090B0E"/>'
        '<path fill="#E6E3E1" d="M9 8h5v10h12V8h5v24h-5V22H14v10H9z"/></svg>')
