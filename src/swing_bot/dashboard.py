from __future__ import annotations

import argparse
import base64
import json
import os
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from swing_bot.dashboard_bridge import dashboard_payload, enqueue_command

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Control</title><style>
:root{--ink:#17201d;--muted:#63706b;--line:#d7ded9;--paper:#f4f6f2;--panel:#fff;--green:#087f5b;--red:#c43d31;--amber:#b66a05}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background-color:var(--paper);background-image:linear-gradient(#dfe5df55 1px,transparent 1px),linear-gradient(90deg,#dfe5df55 1px,transparent 1px);background-size:24px 24px;font:14px/1.45 Georgia,serif;letter-spacing:0}
header{height:64px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);background:#fcfdfb}h1{font-size:21px;margin:0;letter-spacing:0}.status{display:flex;gap:9px;align-items:center;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;background:var(--red)}.dot.live{background:var(--green)}
main{max-width:1380px;margin:auto;padding:22px 28px 48px}.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:12px}.stamp{color:var(--muted);font-family:ui-monospace,monospace}.actions{display:flex;gap:8px}button{min-height:38px;border:1px solid var(--line);border-radius:5px;background:#fff;color:var(--ink);padding:0 14px;font:600 13px Georgia,serif;cursor:pointer}button:hover{border-color:#89958f}button.danger{background:var(--red);border-color:var(--red);color:#fff}button.pause.active{background:#fff3dd;border-color:#d79a3b;color:#754300}button:disabled{opacity:.5;cursor:not-allowed}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));border:1px solid var(--line);background:var(--panel);margin-bottom:18px}.metric{padding:16px 18px;border-right:1px solid var(--line)}.metric:last-child{border:0}.label{font:11px ui-monospace,monospace;text-transform:uppercase;color:var(--muted);margin-bottom:5px}.value{font-size:25px;font-variant-numeric:tabular-nums}.positive{color:var(--green)}.negative{color:var(--red)}
.layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(310px,.75fr);gap:18px}.section{background:var(--panel);border:1px solid var(--line);margin-bottom:18px}.section h2{font-size:15px;margin:0;padding:13px 16px;border-bottom:1px solid var(--line)}.chart{height:290px;padding:12px}.chart svg{width:100%;height:100%;overflow:visible}.gridline{stroke:#e3e8e4;stroke-width:1}.curve{fill:none;stroke:var(--green);stroke-width:2;vector-effect:non-scaling-stroke}.area{fill:#087f5b18}.empty{height:150px;display:grid;place-items:center;color:var(--muted)}
.table-wrap{overflow:auto;max-height:430px}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:10px 14px;border-bottom:1px solid #e7ebe8;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{position:sticky;top:0;background:#fafbf9;color:var(--muted);font:11px ui-monospace,monospace;text-transform:uppercase}.side{font:700 11px ui-monospace,monospace}.side.LONG{color:var(--green)}.side.SHORT{color:var(--red)}
.notice{padding:13px 16px;color:var(--muted);border-top:1px solid var(--line);font-size:12px}.command{padding:16px}.command strong{display:block;margin-bottom:6px}.command p{margin:0;color:var(--muted)}
@media(max-width:850px){header{padding:0 16px}main{padding:16px}.toolbar{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr 1fr}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid var(--line)}.layout{grid-template-columns:1fr}.actions{width:100%}.actions button{flex:1}.value{font-size:21px}}
</style></head><body><header><h1>Swing Control</h1><div class="status"><span id="statusDot" class="dot"></span><span id="statusText">Connecting</span></div></header>
<main><div class="toolbar"><div id="updated" class="stamp">Awaiting strategy state</div><div class="actions"><button id="pause" class="pause">|| Pause entries</button><button id="flatten" class="danger">Flatten positions</button></div></div>
<div class="metrics"><div class="metric"><div class="label">Net liquidation</div><div id="equity" class="value">--</div></div><div class="metric"><div class="label">Curve change</div><div id="change" class="value">--</div></div><div class="metric"><div class="label">Open positions</div><div id="openCount" class="value">0</div></div><div class="metric"><div class="label">Closed trades</div><div id="tradeCount" class="value">0</div></div></div>
<div class="layout"><div><section class="section"><h2>Equity curve</h2><div id="chart" class="chart"></div></section><section class="section"><h2>Historical trades</h2><div class="table-wrap"><table><thead><tr><th>Date / instrument</th><th>Side</th><th>Quantity</th><th>Entry</th><th>Exit</th><th>P&amp;L</th></tr></thead><tbody id="trades"></tbody></table></div></section></div>
<aside><section class="section"><h2>Open positions</h2><div class="table-wrap"><table><thead><tr><th>Instrument</th><th>Side</th><th>Qty</th><th>Entry</th><th>Mark</th><th>Unrealized</th></tr></thead><tbody id="positions"></tbody></table></div><div class="notice">Flatten uses reduce-only GTC limit orders with a 5% execution collar and pauses new entries.</div></section><section class="section"><h2>Last control action</h2><div id="lastCommand" class="command"><p>No command processed.</p></div></section></aside></div></main>
<script>
const money=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}),num=new Intl.NumberFormat('en-US',{maximumFractionDigits:2});let state={};
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function cls(v){return v>0?'positive':v<0?'negative':''}
function draw(points){const el=document.getElementById('chart');if(points.length<2){el.innerHTML='<div class="empty">Equity history will appear after the bot publishes samples.</div>';return}const values=points.map(p=>Number(p.equity)),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1,w=900,h=250,pad=12;const coords=values.map((v,i)=>[pad+i*(w-2*pad)/(values.length-1),pad+(hi-v)*(h-2*pad)/span]);const line=coords.map(p=>p.join(',')).join(' '),area=`${pad},${h-pad} ${line} ${w-pad},${h-pad}`;el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line class="gridline" x1="${pad}" y1="${h/2}" x2="${w-pad}" y2="${h/2}"/><polygon class="area" points="${area}"/><polyline class="curve" points="${line}"/></svg>`}
function render(s){state=s;const online=s.status==='running';document.getElementById('statusDot').className='dot '+(online?'live':'');document.getElementById('statusText').textContent=s.paused?'Paused':online?'Running':'Offline';document.getElementById('updated').textContent=s.updated_at?'Updated '+new Date(s.updated_at).toLocaleString():'Awaiting strategy state';document.getElementById('equity').textContent=s.equity==null?'--':money.format(s.equity);const curve=s.equity_curve||[],change=curve.length>1?curve.at(-1).equity-curve[0].equity:null,changeEl=document.getElementById('change');changeEl.textContent=change==null?'--':money.format(change);changeEl.className='value '+cls(change);document.getElementById('openCount').textContent=(s.positions||[]).length;document.getElementById('tradeCount').textContent=(s.trades||[]).length;const pause=document.getElementById('pause');pause.textContent=s.paused?'> Resume entries':'|| Pause entries';pause.classList.toggle('active',!!s.paused);pause.disabled=!online;document.getElementById('flatten').disabled=!online||!(s.positions||[]).length;draw(curve);
document.getElementById('positions').innerHTML=(s.positions||[]).map(p=>`<tr><td>${esc(p.instrument_id)}</td><td class="side ${esc(p.side)}">${esc(p.side)}</td><td>${esc(p.quantity)}</td><td>${num.format(p.avg_px_open)}</td><td>${num.format(p.mark_price)}</td><td class="${cls(p.unrealized_pnl)}">${money.format(p.unrealized_pnl)}</td></tr>`).join('')||'<tr><td colspan="6">No open positions</td></tr>';
document.getElementById('trades').innerHTML=(s.trades||[]).map(t=>`<tr><td>${new Date(t.closed_at).toLocaleDateString()} &middot; ${esc(t.instrument_id)}</td><td class="side ${esc(t.side)}">${esc(t.side)}</td><td>${esc(t.quantity)}</td><td>${num.format(t.avg_px_open)}</td><td>${num.format(t.avg_px_close)}</td><td class="${cls(t.realized_pnl)}">${money.format(t.realized_pnl)}</td></tr>`).join('')||'<tr><td colspan="6">No closed trades recorded</td></tr>';const c=s.last_command;document.getElementById('lastCommand').innerHTML=c?`<strong>${esc(c.action)}</strong><p>${esc(c.result)} &middot; ${new Date(c.processed_at).toLocaleString()}</p>`:'<p>No command processed.</p>'}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error();render(await r.json())}catch{render({status:'offline',paused:true,positions:[],trades:[],equity_curve:[]})}}async function command(path,body={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)alert((await r.json()).error||'Command failed');await refresh()}
document.getElementById('pause').onclick=()=>command('/api/pause',{paused:!state.paused});document.getElementById('flatten').onclick=()=>{if(confirm('Pause entries and submit reduce-only limit exits for every open position?'))command('/api/flatten')};refresh();setInterval(refresh,5000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    runtime_dir = Path("runtime")
    username = "admin"
    password = ""

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json({"status": "ok"})
            return
        if not self._authorized():
            return
        if self.path == "/":
            self._send(INDEX_HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(dashboard_payload(self.runtime_dir))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._authorized() or not self._same_origin():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/pause" and isinstance(payload.get("paused"), bool):
            command_id = enqueue_command(
                self.runtime_dir, "set_paused", {"paused": payload["paused"]}
            )
        elif self.path == "/api/flatten":
            command_id = enqueue_command(self.runtime_dir, "flatten", {})
        else:
            self._json({"error": "Unknown command"}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"accepted": True, "command_id": command_id}, HTTPStatus.ACCEPTED)

    def _authorized(self) -> bool:
        if not self.password:
            return True
        expected = "Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        if self.headers.get("Authorization") == expected:
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Swing Control"')
        self.end_headers()
        return False

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or urlparse(origin).netloc == self.headers.get("Host"):
            return True
        self._json({"error": "Cross-origin commands are forbidden"}, HTTPStatus.FORBIDDEN)
        return False

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(
            json.dumps(value, separators=(",", ":")).encode(),
            "application/json",
            status,
        )

    def _send(
        self,
        content: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swing-bot dashboard")
    parser.add_argument("--runtime-dir", default=os.getenv("DASHBOARD_RUNTIME_PATH", "runtime"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    DashboardHandler.runtime_dir = Path(args.runtime_dir)
    DashboardHandler.username = os.getenv("DASHBOARD_USERNAME", "admin")
    DashboardHandler.password = os.getenv("DASHBOARD_PASSWORD", "")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0