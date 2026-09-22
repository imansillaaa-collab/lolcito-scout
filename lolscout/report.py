"""Genera el reporte diario: un HTML interactivo (se abre con doble clic) + un JSON con los datos."""
import json
from datetime import datetime

from . import config


def _lookup(result: dict, dd) -> dict:
    champ_ids, item_ids, rune_ids, spell_ids = set(), set(), set(), set()
    for champs in result["roles"].values():
        for c in champs:
            champ_ids.add(c["id"])
            champ_ids.update(int(k) for k in c["vs_all"])
            item_ids.update(i["id"] for i in c["items"] + c["boots"])
            rune_ids.update(k["id"] for k in c["keystones"])
            for pair in c["spells"]:
                spell_ids.update(pair)
    for d in result["duos"]:
        champ_ids.update((d["adc"], d["sup"]))
    for m in result.get("me") or []:
        champ_ids.add(m["id"])
    return {
        "champs": {i: [dd.champ_name(i), dd.champ_img(i)] for i in champ_ids},
        "items": {i: [dd.item_name(i), dd.item_img(i)] for i in item_ids},
        "runes": {i: [dd.rune_name(i), dd.rune_img(i)] for i in rune_ids},
        "spells": {i: [dd.spell_name(i), dd.spell_img(i)] for i in spell_ids},
    }


def write_report(result: dict, dd) -> tuple:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        **result,
        "lookup": _lookup(result, dd),
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "tiers": config.TIERS,
        "platform": config.PLATFORM.upper(),
        "roleNames": config.ROLE_NAMES,
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)

    html_path = config.REPORTS_DIR / f"reporte_{today}.html"
    html_path.write_text(html, encoding="utf-8")
    (config.REPORTS_DIR / "ultimo.html").write_text(html, encoding="utf-8")
    json_path = config.REPORTS_DIR / f"datos_{today}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return html_path, json_path


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lolcito Scout · Picks del día</title>
<style>
/* Tipografía:
   - League (instalada en tu PC): logo, "VS" y números grandes (solo textos sin tildes, porque League no las tiene).
   - Beaufort for LOL (instalada en tu PC): títulos, pestañas y botones. Tiene tildes y ñ.
   - Texto: Spiegel completa si algún día la instalás; si no, Hanken Grotesk (libre, muy parecida, incluida).
   Si en otra PC no están League/Beaufort, se usa Cinzel (incluida). */
@font-face{font-family:"LS Display";src:local("League"),local("LeagueRegular"),url(/static/fonts/privadas/League.otf) format("opentype");unicode-range:U+0020-007E}
@font-face{font-family:"LS Title";font-weight:400;src:local("Beaufort for LOL"),local("BeaufortforLOL-Regular"),url(/static/fonts/privadas/BeaufortforLOL-Regular.ttf) format("truetype"),url(/static/fonts/Cinzel.ttf) format("truetype")}
@font-face{font-family:"LS Title";font-weight:500;src:local("Beaufort for LOL Medium"),local("BeaufortforLOL-Medium"),url(/static/fonts/privadas/BeaufortforLOL-Regular.ttf) format("truetype"),url(/static/fonts/Cinzel.ttf) format("truetype")}
@font-face{font-family:"LS Title";font-weight:600 700;src:local("Beaufort for LOL Bold"),local("BeaufortforLOL-Bold"),url(/static/fonts/privadas/BeaufortforLOL-Bold.ttf) format("truetype"),url(/static/fonts/Cinzel.ttf) format("truetype")}
@font-face{font-family:"LS Title";font-weight:800 900;src:local("Beaufort for LOL Heavy"),local("BeaufortforLOL-Heavy"),url(/static/fonts/privadas/BeaufortforLOL-Bold.ttf) format("truetype"),url(/static/fonts/Cinzel.ttf) format("truetype")}
@font-face{font-family:"LS Body";font-weight:400;src:local("Spiegel Regular"),local("Spiegel-Regular"),local("SpiegelSans-Regular"),url(/static/fonts/HankenGrotesk.ttf) format("truetype")}
@font-face{font-family:"LS Body";font-weight:500 600;src:local("Spiegel SemiBold"),local("Spiegel-SemiBold"),local("SpiegelSans-SemiBold"),url(/static/fonts/HankenGrotesk.ttf) format("truetype")}
@font-face{font-family:"LS Body";font-weight:700 900;src:local("Spiegel Bold"),local("Spiegel-Bold"),local("SpiegelSans-Bold"),url(/static/fonts/HankenGrotesk.ttf) format("truetype")}
:root{
  --bg:#010a13;--panel:#0b1520;--panel2:#111c28;--line:#1e2d3d;--text:#f0e6d2;--muted:#a09b8c;
  --accent:#c8aa6e;--good:#0acbe6;--bad:#e0484b;
  --S:#e8b84a;--A:#6fc27a;--B:#5a9bd8;--C:#9a8fc9;--D:#6b7480;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "LS Body","Segoe UI",system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 60px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:24px}
h1{font:700 26px "LS Title",Georgia,serif;margin:0;letter-spacing:1.5px;color:var(--text)}
h1 span{color:var(--accent)}
h2{font:700 16px "LS Title",Georgia,serif;letter-spacing:1.5px;text-transform:uppercase;margin:32px 0 12px;color:var(--accent)}
.meta{color:var(--muted);font-size:13px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:4px 10px;font-size:12px;color:var(--muted)}
.chip b{color:var(--text);font-weight:600}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.panel{background:linear-gradient(180deg,#111c28,#091420);border:1px solid #785a28;padding:16px}
.panel h3{margin:0 0 12px;font:700 13px "LS Title",Georgia,serif;color:var(--accent);text-transform:uppercase;letter-spacing:.6px}
.top{display:flex;flex-direction:column;gap:8px}
.toprow{display:flex;align-items:center;gap:10px}
.rank{width:18px;color:var(--muted);font-variant-numeric:tabular-nums}
img.ch{width:36px;height:36px;border-radius:8px;border:1px solid var(--line)}
img.sm{width:26px;height:26px;border-radius:6px;border:1px solid var(--line);vertical-align:middle}
.name{flex:1;font-weight:600}
.num{font-variant-numeric:tabular-nums}
.wr{font-weight:600}
.pos{color:var(--good)}.neg{color:var(--bad)}
.tier{display:inline-block;min-width:22px;text-align:center;border-radius:5px;padding:1px 5px;font-weight:700;font-size:12px;color:#111}
.tS{background:var(--S)}.tA{background:var(--A)}.tB{background:var(--B)}.tC{background:var(--C)}.tD{background:var(--D)}.t\?{background:var(--line);color:var(--text)}
.tabs{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.tab{background:var(--panel2);border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 14px;cursor:pointer;font:inherit}
.tab.on{color:var(--text);border-color:var(--accent)}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 6px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:12px;cursor:pointer;user-select:none;white-space:nowrap}
td.r,th.r{text-align:right}
tr.row{cursor:pointer}
tr.row:hover td{background:var(--panel2)}
tr.detail td{background:var(--panel2);padding:14px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.dgrid h4{margin:0 0 8px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.li{display:flex;align-items:center;gap:8px;margin:5px 0}
.li .n{flex:1}
.small{font-size:12px;color:var(--muted)}
.helper{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:14px}
label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
select{width:100%;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px}
.recs{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.rec{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px;display:flex;gap:10px;align-items:center}
.rec .why{font-size:12px;color:var(--muted)}
.scroll{overflow-x:auto}
.empty{color:var(--muted);padding:12px 0}
footer{margin-top:40px;color:var(--muted);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Lolcito <span>Scout</span> · picks del día</h1>
      <div class="meta" id="sub"></div>
    </div>
    <div class="chips" id="chips"></div>
  </header>

  <div class="grid2" id="tops"></div>

  <h2>¿Qué pickeo? (asistente de draft)</h2>
  <div class="panel">
    <div class="helper">
      <div><label>Mi rol</label><select id="hRole"></select></div>
      <div><label>Rival de línea (si ya lo sabés)</label><select id="hEnemy"></select></div>
      <div><label>Mi compañero de bot (si ya pickeó)</label><select id="hAlly"></select></div>
    </div>
    <div class="recs" id="recs"></div>
    <div class="small" style="margin-top:10px">Puntaje = winrate del meta, ajustado por el enfrentamiento y la sinergia cuando hay suficientes partidas.</div>
  </div>

  <h2>Tier list completa</h2>
  <div class="panel">
    <div class="tabs" id="tabs"></div>
    <div class="scroll"><table id="tbl"></table></div>
    <div class="small" style="margin-top:8px">Tocá un campeón para ver build, runas y enfrentamientos.</div>
  </div>

  <h2>Mejores dúos ADC + Support</h2>
  <div class="panel scroll"><table id="duos"></table></div>

  <div id="meBox"></div>

  <footer>Winrate ajustado: suma 30 partidas “fantasma” al 50% para que los campeones con pocas partidas no aparezcan inflados. Datos: API de Riot Games. Lolcito Scout no está respaldado por Riot Games.</footer>
</div>

<script>
const D = __DATA__;
const L = D.lookup;
const $ = s => document.querySelector(s);
const pct = x => (x*100).toFixed(1)+'%';
const cname = id => (L.champs[id]||['#'+id])[0];
const cimg = (id,cls='ch') => `<img class="${cls}" loading="lazy" src="${(L.champs[id]||[,''])[1]}" alt="">`;
const iimg = (map,id) => `<img class="sm" loading="lazy" title="${(map[id]||['#'+id])[0]}" src="${(map[id]||[,''])[1]}" alt="">`;
const tier = t => `<span class="tier t${t}">${t}</span>`;
const wrc = x => `<span class="wr ${x>=0.52?'pos':x<0.48?'neg':''}">${pct(x)}</span>`;
const roles = Object.keys(D.roles);
const RN = r => D.roleNames[r] || r;

$('#sub').textContent = `Parche ${D.patches.join(' + ')} · ${D.platform} ${D.tiers.map(t=>t[0]+t.slice(1).toLowerCase()).join('–')} · actualizado ${D.generated}`;
$('#chips').innerHTML = `<span class="chip"><b>${D.matches.toLocaleString('es-AR')}</b> partidas analizadas</span>` +
  roles.map(r=>`<span class="chip"><b>${D.roles[r].length}</b> ${RN(r)}</span>`).join('');

// Top 5 por rol
$('#tops').innerHTML = roles.map(r => `
  <div class="panel"><h3>Top ${RN(r)} del día</h3><div class="top">
  ${D.roles[r].slice(0,5).map((c,i)=>`
    <div class="toprow"><span class="rank">${i+1}</span>${cimg(c.id)}
      <span class="name">${c.name}</span>${tier(c.tier)}
      <span class="num small">${c.games} p.</span>${wrc(c.wr)}</div>`).join('') || '<div class="empty">Sin datos suficientes todavía.</div>'}
  </div></div>`).join('');

// Asistente de draft
const hRole=$('#hRole'), hEnemy=$('#hEnemy'), hAlly=$('#hAlly');
hRole.innerHTML = roles.map(r=>`<option value="${r}">${RN(r)}</option>`).join('');
function fillSelects(){
  const r = hRole.value;
  const enemies = [...new Set(D.roles[r].flatMap(c=>Object.keys(c.vs_all)))].sort((a,b)=>cname(a).localeCompare(cname(b)));
  hEnemy.innerHTML = '<option value="">— cualquiera —</option>' + enemies.map(id=>`<option value="${id}">${cname(id)}</option>`).join('');
  const other = r==='BOTTOM'?'UTILITY':r==='UTILITY'?'BOTTOM':null;
  hAlly.disabled = !other;
  const allies = other && D.roles[other] ? D.roles[other].map(c=>c.id).sort((a,b)=>cname(a).localeCompare(cname(b))) : [];
  hAlly.innerHTML = '<option value="">— cualquiera —</option>' + allies.map(id=>`<option value="${id}">${cname(id)}</option>`).join('');
}
function recommend(){
  const r=hRole.value, e=hEnemy.value, a=hAlly.value;
  const duo = {};
  D.duos.forEach(d=>{ duo[d.adc+'-'+d.sup]=d; });
  const list = D.roles[r].map(c=>{
    let score = c.adj, why=[`meta ${pct(c.wr)}`];
    if(e && c.vs_all[e]){ const [g,w]=c.vs_all[e]; const adj=(w*g+0.5*10)/(g+10); score += (adj-0.5)*1.2; why.push(`vs ${cname(e)} ${pct(w)} (${g})`); }
    if(a){ const k = r==='BOTTOM'? c.id+'-'+a : a+'-'+c.id; const d=duo[k]; if(d){ score += (d.adj-0.5)*0.8; why.push(`con ${cname(a)} ${pct(d.wr)} (${d.games})`);} }
    return {c,score,why};
  }).sort((x,y)=>y.score-x.score).slice(0,8);
  $('#recs').innerHTML = list.map(({c,score,why})=>`
    <div class="rec">${cimg(c.id)}<div><div><b>${c.name}</b> ${tier(c.tier)}</div>
    <div class="why">${why.join(' · ')}</div></div></div>`).join('') || '<div class="empty">Sin datos.</div>';
}
hRole.onchange=()=>{fillSelects();recommend();}; hEnemy.onchange=recommend; hAlly.onchange=recommend;
fillSelects(); recommend();

// Tier list con detalle
let curRole = roles[0], sortKey='adj', sortDir=-1, openId=null;
$('#tabs').innerHTML = roles.map(r=>`<button class="tab" data-r="${r}">${RN(r)}</button>`).join('');
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{curRole=b.dataset.r;openId=null;renderTable();});
const cols=[['#',''],['Campeón','name'],['Tier','adj'],['Winrate','wr'],['Pick','pick'],['Ban','ban'],['KDA','kda'],['Partidas','games']];
function detail(c){
  const li=(img,n,sub)=>`<div class="li">${img}<span class="n">${n}</span><span class="small num">${sub}</span></div>`;
  const vs=(arr)=>arr.map(m=>li(cimg(m.id,'sm'),cname(m.id),`${pct(m.wr)} · ${m.games}p`)).join('')||'<div class="small">Pocas partidas todavía.</div>';
  return `<div class="dgrid">
    <div><h4>Ítems más armados</h4>${c.items.slice(0,6).map(i=>li(iimg(L.items,i.id),L.items[i.id][0],`${pct(i.share)} · WR ${pct(i.wr)}`)).join('')}
      ${c.boots.slice(0,2).map(i=>li(iimg(L.items,i.id),L.items[i.id][0],`${pct(i.share)} · WR ${pct(i.wr)}`)).join('')}</div>
    <div><h4>Runa principal</h4>${c.keystones.map(k=>li(iimg(L.runes,k.id),L.runes[k.id][0],`${pct(k.share)} · WR ${pct(k.wr)}`)).join('')}
      <h4 style="margin-top:14px">Hechizos</h4>${c.spells.map(p=>`<div class="li">${p.map(s=>iimg(L.spells,s)).join('')}<span class="n">${p.map(s=>L.spells[s][0]).join(' + ')}</span></div>`).join('')}</div>
    <div><h4>Le gana a</h4>${vs(c.good_vs)}</div>
    <div><h4>Le cuesta contra</h4>${vs(c.bad_vs)}</div>
  </div>`;
}
function renderTable(){
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.r===curRole));
  const rows=[...D.roles[curRole]].sort((a,b)=>{const x=a[sortKey],y=b[sortKey];return (typeof x==='string'?x.localeCompare(y):x-y)*sortDir;});
  let h='<tr>'+cols.map(([t,k],i)=>`<th class="${i>2?'r':''}" data-k="${k}">${t}${k===sortKey?(sortDir<0?' ▾':' ▴'):''}</th>`).join('')+'</tr>';
  rows.forEach((c,i)=>{
    h+=`<tr class="row" data-id="${c.id}"><td class="small">${i+1}</td><td>${cimg(c.id,'sm')} <b>${c.name}</b></td><td>${tier(c.tier)}</td>
      <td class="r">${wrc(c.wr)}</td><td class="r num">${pct(c.pick)}</td><td class="r num">${pct(c.ban)}</td><td class="r num">${c.kda.toFixed(2)}</td><td class="r num">${c.games}</td></tr>`;
    if(openId===c.id) h+=`<tr class="detail"><td colspan="8">${detail(c)}</td></tr>`;
  });
  if(!rows.length) h+='<tr><td colspan="8" class="empty">Sin datos suficientes todavía: dejá correr el escaneo unos días.</td></tr>';
  $('#tbl').innerHTML=h;
  $('#tbl').querySelectorAll('th[data-k]').forEach(th=>{ if(!th.dataset.k) return; th.onclick=()=>{const k=th.dataset.k; sortDir = k===sortKey? -sortDir : (k==='name'?1:-1); sortKey=k; renderTable();}; });
  $('#tbl').querySelectorAll('tr.row').forEach(tr=>tr.onclick=()=>{const id=+tr.dataset.id; openId = openId===id?null:id; renderTable();});
}
renderTable();

// Dúos
$('#duos').innerHTML = '<tr><th>ADC</th><th>Support</th><th class="r">Winrate</th><th class="r">Partidas</th></tr>' +
  (D.duos.slice(0,15).map(d=>`<tr><td>${cimg(d.adc,'sm')} ${cname(d.adc)}</td><td>${cimg(d.sup,'sm')} ${cname(d.sup)}</td>
   <td class="r">${wrc(d.wr)}</td><td class="r num">${d.games}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">Todavía no hay dúos con 8+ partidas.</td></tr>');

// Mi pool
if(D.me && D.me.length){
  $('#meBox').innerHTML = `<h2>Tu pool de campeones</h2><div class="panel scroll"><table>
   <tr><th>Campeón</th><th>Rol</th><th>Tier en el meta</th><th class="r">Tu winrate</th><th class="r">Tus partidas</th></tr>
   ${D.me.map(m=>`<tr><td>${cimg(m.id,'sm')} ${cname(m.id)}</td><td>${RN(m.role)}</td><td>${tier(m.tier)}</td><td class="r">${wrc(m.wr)}</td><td class="r num">${m.games}</td></tr>`).join('')}
  </table><div class="small" style="margin-top:8px">Ideal: priorizá los que están en S/A y en los que ya tenés buen winrate.</div></div>`;
}
</script>
</body>
</html>
"""
