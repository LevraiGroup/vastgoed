"""
Levrai Group - Pandenselectiesysteem
Bouwt het dashboard (design/index.html) data-gedreven uit panden_delft.json.

Draai na run_proef.py. Genereert een zelfstandige HTML met ingesloten payload,
zodat de pagina ook als statische snapshot (Claude Design) werkt zonder fetch.
"""
from __future__ import annotations

import json
from pathlib import Path

from gebieden import resolve, slug
from selectie import load_config

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT = BASE / "design" / "index.html"


def bouw_payload() -> dict:
    cfg = load_config()
    label, _ = resolve(cfg)
    panden = json.load(open(DATA / f"panden_{slug(label)}.json", encoding="utf-8"))
    act = [p for p in panden if not p["uitgesloten"] and p["categorieen"]]
    # Binnen gelijke score een zinnige volgorde: meer woningen, dan ouder, dan groter.
    top = sorted(act, key=lambda p: (
        -p["score100"],
        -p["aantal_per_functie"].get("woon", 0),
        p["bouwjaar"],
        -p["totale_oppervlakte"],
        p["bag_pand_id"],
    ))[:20]

    tot_vbo = sum(p["aantal_vbo"] for p in panden)
    uitgesloten = sum(1 for p in panden if p["uitgesloten"])
    # Drempel uit config.yaml (briefing sectie 4): geen magisch getal in de code.
    drempel = cfg["drempels"]["score_min_voor_werklijst"]
    werklijst = sum(1 for p in act if p["leadscore"] >= drempel)

    kpi = [
        {"v": f"{tot_vbo:,}".replace(",", "."), "l": "Verblijfsobjecten ingelezen",
         "h": f"100,0% dekking van {label}", "c": "var(--s1)"},
        {"v": f"{len(panden):,}".replace(",", "."), "l": "Unieke BAG-panden",
         "h": f"{uitgesloten:,}".replace(",", ".") + " uitgesloten", "c": "var(--s3)"},
        {"v": f"{len(act):,}".replace(",", "."), "l": "Binnen categorie A–E",
         "h": "de mastervoorraad", "c": "var(--s2)"},
        {"v": f"{werklijst:,}".replace(",", "."), "l": f"Werklijst · score ≥ {drempel}",
         "h": "ruim meerdere maanden voorraad", "c": "var(--s5)"},
    ]

    labels = {"A": "Winkel + wonen", "B": "Bedrijf/kantoor + wonen",
              "C": "Klein wooncomplex", "D": "Groot oud pand", "E": "Afwijkende combinatie"}
    slot = {"A": "var(--s1)", "B": "var(--s2)", "C": "var(--s3)", "D": "var(--s4)", "E": "var(--s5)"}
    cats = [{"k": k, "name": labels[k], "n": sum(1 for p in act if k in p["categorieen"]),
             "c": slot[k]} for k in "ABCDE"]

    scores = [p["score100"] for p in top]
    bjs = [p["bouwjaar"] for p in top]
    gem_opp = round(sum(p["totale_oppervlakte"] for p in top) / len(top))
    facts = [
        {"k": "Panden in proefselectie", "val": str(len(top))},
        {"k": "Score-index (/100)", "val": f"{min(scores)}–{max(scores)}"},
        {"k": "Bouwjaren", "val": f"{min(bjs)}–{max(bjs)}"},
        {"k": "Oudste pand", "val": str(min(bjs))},
        {"k": "Gem. oppervlakte", "val": f"{gem_opp} m²"},
        {"k": "Doelgebied", "val": label},
    ]

    # Korte tags voor de kwalificatie-signalen die de gebruiker belangrijk vindt.
    # 'kind' stuurt de kleur: leeg = opvallend (amber), rest = groen.
    qual_tag = {
        "Buiten gebruik / leegstaand": ("🏚 leegstaand", "leeg"),
        "In verbouwing": ("🔧 in verbouwing", "bouw"),
        "Slecht of ontbrekend energielabel": ("⚡ slechte staat", "ok"),
    }

    leads = []
    for p in top:
        f = {k: round(v) for k, v in p["opp_per_functie"].items() if v}
        sig = [{"t": qual_tag[it["label"]][0], "k": qual_tag[it["label"]][1], "d": it["detail"]}
               for it in p["score_opbouw"] if it["label"] in qual_tag and it["behaald"]]
        leads.append({
            "a": p["hoofdadres"].split(",")[0],
            "p": p["postcode"],
            "id": p["bag_pand_id"],
            "bj": p["bouwjaar"],
            "m2": round(p["totale_oppervlakte"]),
            "vbo": p["aantal_vbo"],
            "adr": p["aantal_adressen"],
            "won": p["aantal_per_functie"].get("woon", 0),
            "cat": p["categorieen"],
            "f": f,
            "wp": p.get("woonplaats", ""),
            "s100": p["score100"],
            "raw": p["leadscore"],
            "sig": sig,
            "opbouw": p["score_opbouw"],
        })

    budget = cfg["score"].get("schaal_max", 26)
    return {"kpi": kpi, "cats": cats, "facts": facts, "leads": leads,
            "budget": budget, "gebied": label}


TEMPLATE = r"""<!-- @dsCard group="Levrai VASTGOED" name="Pandenselectie dashboard" subtitle="__LABEL__ · 20-pand proefresultaat met score-opbouw" -->
<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Levrai · Pandenselectie Dashboard — __LABEL__</title>
<style>
  :root{
    color-scheme: light;
    --plane:#f9f9f7; --surface:#fcfcfb; --surface-2:#ffffff;
    --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --ring:rgba(11,11,11,.10);
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
    --good:#0ca30c; --crit:#d03b3b;
    --shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -12px rgba(11,11,11,.12);
    --brand:#12233b;
  }
  @media (prefers-color-scheme: dark){
    :root:where(:not([data-theme="light"])){
      color-scheme: dark;
      --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#201f1e;
      --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,.10);
      --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
      --good:#0ca30c; --crit:#e06666;
      --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px -14px rgba(0,0,0,.6);
      --brand:#0a1524;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#201f1e;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
    --good:#0ca30c; --crit:#e06666;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px -14px rgba(0,0,0,.6);
    --brand:#0a1524;
  }

  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.45}
  a{color:inherit}
  .wrap{max-width:1160px;margin:0 auto;padding:22px 22px 64px}

  .top{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
    background:var(--brand);color:#fff;border-radius:16px;padding:20px 24px;box-shadow:var(--shadow)}
  .mark{font-weight:800;letter-spacing:.16em;font-size:15px}
  .mark small{display:block;letter-spacing:.28em;font-weight:600;font-size:10px;color:#9fb3cc;margin-top:3px}
  .top .sub{font-size:13px;color:#c6d3e4}
  .spacer{flex:1}
  .pill{font-size:12px;color:#c6d3e4;border:1px solid rgba(255,255,255,.18);padding:5px 11px;border-radius:999px;white-space:nowrap}
  .toggle{cursor:pointer;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);
    color:#fff;font:inherit;font-size:12px;padding:6px 12px;border-radius:999px}
  .toggle:hover{background:rgba(255,255,255,.18)}

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}
  .kpi{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow)}
  .kpi .v{font-size:30px;font-weight:750;letter-spacing:-.02em;line-height:1}
  .kpi .l{font-size:12.5px;color:var(--ink-2);margin-top:8px}
  .kpi .h{font-size:11px;color:var(--muted);margin-top:3px}
  .kpi .accent{width:26px;height:3px;border-radius:2px;margin-bottom:12px;background:var(--s1)}

  .cols{display:grid;grid-template-columns:1.35fr 1fr;gap:14px;margin-top:14px}
  .panel{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}
  .panel h2{margin:0 0 4px;font-size:14px;font-weight:700}
  .panel .cap{margin:0 0 16px;font-size:12px;color:var(--muted)}

  .bar{display:grid;grid-template-columns:150px 1fr;align-items:center;gap:12px;margin:11px 0}
  .bar .name{font-size:12.5px;color:var(--ink-2)}
  .bar .name b{color:var(--ink);font-weight:650}
  .track{position:relative;height:22px;background:var(--grid);border-radius:6px;overflow:hidden}
  .fill{height:100%;border-radius:6px;display:flex;align-items:center;justify-content:flex-end;
    padding-right:8px;color:#fff;font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums;
    min-width:34px;transition:width .6s cubic-bezier(.2,.7,.2,1)}

  .facts{display:grid;gap:12px}
  .fact{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px dashed var(--grid);padding-bottom:9px}
  .fact:last-child{border-bottom:0;padding-bottom:0}
  .fact .k{font-size:12.5px;color:var(--ink-2)}
  .fact .val{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
  .note{margin-top:14px;font-size:11.5px;color:var(--muted);line-height:1.5}

  .sec-h{display:flex;align-items:baseline;gap:10px;margin:26px 2px 12px}
  .sec-h h2{margin:0;font-size:15px}
  .sec-h span{font-size:12px;color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
  .card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 17px;
    box-shadow:var(--shadow);display:flex;flex-direction:column;gap:11px}
  .card .rowtop{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
  .card .addr{font-size:14.5px;font-weight:700;letter-spacing:-.01em}
  .card .lid{font-size:11px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}
  .score{flex:none;display:flex;flex-direction:column;align-items:center;justify-content:center;
    width:56px;height:56px;border-radius:14px;background:var(--brand);color:#fff}
  .score b{font-size:22px;font-weight:800;line-height:1}
  .score small{font-size:8px;letter-spacing:.08em;color:#9fb3cc;margin-top:2px}
  .meter{height:6px;border-radius:4px;background:var(--grid);overflow:hidden}
  .meter i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,var(--s1),var(--s3));
    transition:width .6s cubic-bezier(.2,.7,.2,1)}
  .chips{display:flex;flex-wrap:wrap;gap:5px}
  .chip{font-size:10.5px;font-weight:700;color:#fff;padding:2px 8px;border-radius:999px}
  .cA{background:var(--s1)} .cB{background:var(--s2)} .cC{background:var(--s3)}
  .cD{background:var(--s4);color:#3a2a00} .cE{background:var(--s5);color:#3a1220}
  .sigtags{display:flex;flex-wrap:wrap;gap:5px}
  .sigtag{font-size:10.5px;font-weight:650;padding:3px 9px;border-radius:999px;
    background:color-mix(in srgb,var(--good) 13%,transparent);color:var(--good);
    border:1px solid color-mix(in srgb,var(--good) 35%,transparent)}
  .sigtag.leeg{background:color-mix(in srgb,var(--s4) 18%,transparent);
    color:var(--s2);border-color:color-mix(in srgb,var(--s2) 40%,transparent)}
  .meta{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
  .meta div{background:var(--surface-2);border:1px solid var(--ring);border-radius:9px;padding:7px 8px;text-align:center}
  .meta .mv{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}
  .meta .ml{font-size:9.5px;color:var(--muted);letter-spacing:.03em;margin-top:1px}
  .fnbar{display:flex;height:9px;border-radius:5px;overflow:hidden;gap:2px;background:transparent}
  .fnbar i{display:block}
  .fnleg{display:flex;flex-wrap:wrap;gap:10px;font-size:10.5px;color:var(--ink-2)}
  .fnleg span{display:flex;align-items:center;gap:5px}
  .dot{width:8px;height:8px;border-radius:2px;flex:none}

  /* ---- score-opbouw ---- */
  details.brk{border-top:1px solid var(--grid);padding-top:9px}
  details.brk summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;
    font-size:12px;font-weight:650;color:var(--ink)}
  details.brk summary::-webkit-details-marker{display:none}
  details.brk summary .caret{margin-left:auto;color:var(--muted);transition:transform .2s}
  details.brk[open] summary .caret{transform:rotate(180deg)}
  details.brk summary em{font-style:normal;color:var(--muted);font-weight:500}
  .brk ul{list-style:none;margin:11px 0 0;padding:0;display:grid;gap:2px}
  .brk li{display:flex;align-items:center;gap:9px;padding:5px 7px;border-radius:8px;font-size:11.5px}
  .brk li.ok{background:color-mix(in srgb,var(--good) 9%,transparent)}
  .brk li .ci{flex:none;width:15px;height:15px;border-radius:50%;display:flex;align-items:center;
    justify-content:center;font-size:9px;font-weight:800;color:#fff}
  .brk li.ok .ci{background:var(--good)}
  .brk li.miss .ci{background:var(--grid);color:var(--muted)}
  .brk li.neg .ci{background:var(--crit)}
  .brk li.off .ci{background:transparent;border:1.5px dashed var(--baseline);color:var(--muted)}
  .brk li .cl{flex:1;color:var(--ink)}
  .brk li.miss .cl,.brk li.off .cl{color:var(--ink-2)}
  .brk li .cl em{display:block;font-style:normal;font-size:10px;color:var(--muted);margin-top:1px}
  .brk li .cp{flex:none;font-weight:800;font-variant-numeric:tabular-nums;font-size:11.5px}
  .brk li.ok .cp{color:var(--good)} .brk li.neg .cp{color:var(--crit)}
  .brk li.miss .cp{color:var(--muted)} .brk li.off .cp{color:var(--muted);font-weight:600;font-size:9.5px}
  .brkfoot{margin-top:9px;font-size:10.5px;color:var(--muted);line-height:1.5}
  .brkfoot b{color:var(--ink)}

  .card .foot{display:flex;justify-content:space-between;align-items:center;margin-top:2px;padding-top:2px}
  .baglink{font-size:11.5px;font-weight:650;color:var(--s1);text-decoration:none}
  .baglink:hover{text-decoration:underline}
  .status{font-size:10.5px;color:var(--good);display:flex;align-items:center;gap:5px}
  .status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--good)}
  .foothint{margin-top:26px;font-size:11.5px;color:var(--muted);text-align:center;line-height:1.6}

  #tt{position:fixed;pointer-events:none;opacity:0;transform:translate(-50%,-8px);
    background:var(--brand);color:#fff;font-size:11.5px;padding:6px 9px;border-radius:8px;
    box-shadow:var(--shadow);white-space:nowrap;transition:opacity .12s;z-index:50}

  @media(max-width:900px){
    .kpis{grid-template-columns:repeat(2,1fr)}
    .cols{grid-template-columns:1fr}
    .grid{grid-template-columns:1fr}
    .bar{grid-template-columns:120px 1fr}
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="mark">LEVRAI GROUP<small>VASTGOED</small></div>
    <div class="sub">Pandenselectie&nbsp;·&nbsp;__LABEL__</div>
    <div class="spacer"></div>
    <div class="pill">Bron: PDOK BAG WFS v2_0</div>
    <div class="pill">Peildatum 4 aug 2026</div>
    <button class="toggle" id="themeBtn" type="button">◐ Thema</button>
  </header>

  <section class="kpis" id="kpis"></section>

  <div class="cols">
    <div class="panel">
      <h2>Technische voorraad naar categorie</h2>
      <p class="cap">__LABEL__ · panden binnen categorie A–E · een pand kan in meerdere vallen</p>
      <div id="cats"></div>
    </div>
    <div class="panel">
      <h2>Proefselectie in cijfers</h2>
      <p class="cap">De 20 hoogst scorende panden — de controlevraag uit de briefing</p>
      <div class="facts" id="facts"></div>
      <p class="note">Score is een <b>index van 1–100</b> tegen het volledige modelbudget.
        Open een pand voor de volledige score-opbouw per criterium.</p>
    </div>
  </div>

  <div class="sec-h">
    <h2>Proefresultaat — 20 panden</h2>
    <span id="secmeta"></span>
  </div>
  <div class="grid" id="leads"></div>

  <p class="foothint">
    Klik op <b>Score-opbouw</b> in een pand om te zien waar elk punt vandaan komt ·
    grijze criteria wachten op een extra databron (energielabel, verkoophistorie, leegstand).
  </p>
</div>
<div id="tt"></div>

<script>
const PAYLOAD = __PAYLOAD__;
const {kpi:KPI, cats:CATS, facts:FACTS, leads:LEADS, budget:BUDGET} = PAYLOAD;
const FN = {woon:"var(--s1)", winkel:"var(--s2)", kantoor:"var(--s3)", overig:"var(--s4)", bedrijf:"var(--s5)"};
const FNL = {woon:"Wonen", winkel:"Winkel", kantoor:"Kantoor", overig:"Overig", bedrijf:"Bedrijf"};
const BAG="https://bagviewer.kadaster.nl/lvbag/bag-viewer/index.html#?searchQuery=";
const nl = n => n.toLocaleString("nl-NL");
const el = (t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};

const kb=document.getElementById("kpis");
KPI.forEach(k=>{
  const c=el("div","kpi");
  c.innerHTML=`<div class="accent" style="background:${k.c}"></div>
    <div class="v">${k.v}</div><div class="l">${k.l}</div><div class="h">${k.h}</div>`;
  kb.appendChild(c);
});

const max=Math.max(...CATS.map(c=>c.n));
const cb=document.getElementById("cats");
CATS.forEach(c=>{
  const row=el("div","bar");
  row.innerHTML=`<div class="name"><b>${c.k}</b> · ${c.name}</div>
    <div class="track"><div class="fill" data-tip="${c.name}: ${nl(c.n)} panden"
      style="width:0;background:${c.c}">${nl(c.n)}</div></div>`;
  cb.appendChild(row);
  requestAnimationFrame(()=>{row.querySelector(".fill").style.width=(c.n/max*100)+"%";});
});

const fb=document.getElementById("facts");
FACTS.forEach(f=>fb.appendChild(el("div","fact",`<span class="k">${f.k}</span><span class="val">${f.val}</span>`)));

function opbouwHTML(d){
  const cls={behaald:"ok",niet:"miss",aftrek:"neg",inactief:"off"};
  const ic={behaald:"✓",niet:"✕",aftrek:"▼",inactief:"○"};
  const rows=d.opbouw.map(it=>{
    let pts;
    if(it.status==="behaald") pts=`+${it.punten}`;
    else if(it.status==="aftrek") pts=`${it.punten}`;
    else if(it.status==="inactief") pts=`wacht · +${it.punten}`;
    else pts="0";
    return `<li class="${cls[it.status]}">
      <span class="ci">${ic[it.status]}</span>
      <span class="cl">${it.label}<em>${it.detail}</em></span>
      <span class="cp">${pts}</span></li>`;
  }).join("");
  return `<details class="brk"><summary>Score-opbouw
      <em>${d.raw} van ${BUDGET} punten benut</em>
      <span class="caret">▾</span></summary>
    <ul>${rows}</ul>
    <div class="brkfoot"><b>${d.raw}</b> van ${BUDGET} modelpunten → index <b>${d.s100}/100</b>.
      Grijze criteria (○) leveren nog niets tot hun databron is gekoppeld.</div>
  </details>`;
}

document.getElementById("secmeta").textContent=`${LEADS.length} panden · ${PAYLOAD.gebied} · gesorteerd op score-index`;
const lb=document.getElementById("leads");
LEADS.forEach(d=>{
  const order=["woon","winkel","kantoor","bedrijf","overig"];
  const segs=order.filter(k=>d.f[k]).map(k=>
    `<i data-tip="${FNL[k]}: ${d.f[k]} m²" style="flex:${d.f[k]};background:${FN[k]}"></i>`).join("");
  const leg=order.filter(k=>d.f[k]).map(k=>
    `<span><i class="dot" style="background:${FN[k]}"></i>${FNL[k]} ${d.f[k]} m²</span>`).join("");
  const chips=d.cat.map(c=>`<span class="chip c${c}">${c}</span>`).join("");
  const sigtags=d.sig.map(s=>`<span class="sigtag ${s.k}" data-tip="${s.d}">${s.t}</span>`).join("");
  const card=el("div","card");
  card.innerHTML=`
    <div class="rowtop">
      <div><div class="addr">${d.a}</div>
        <div class="lid">${d.p} ${d.wp} · BAG ${d.id}</div></div>
      <div class="score"><b>${d.s100}</b><small>/100</small></div>
    </div>
    <div class="meter"><i style="width:0" data-w="${d.s100}"></i></div>
    <div class="chips">${chips}</div>
    ${sigtags?`<div class="sigtags">${sigtags}</div>`:""}
    <div class="meta">
      <div><div class="mv">${d.bj}</div><div class="ml">BOUWJAAR</div></div>
      <div><div class="mv">${nl(d.m2)}</div><div class="ml">M²</div></div>
      <div><div class="mv">${d.vbo}</div><div class="ml">VBO</div></div>
      <div><div class="mv">${d.adr}</div><div class="ml">ADRESSEN</div></div>
    </div>
    <div class="fnbar">${segs}</div>
    <div class="fnleg">${leg}</div>
    ${opbouwHTML(d)}
    <div class="foot">
      <a class="baglink" href="${BAG}${d.id}" target="_blank" rel="noopener">Open in BAG-viewer ↗</a>
      <span class="status">te controleren</span>
    </div>`;
  lb.appendChild(card);
  const m=card.querySelector(".meter i");
  requestAnimationFrame(()=>{m.style.width=m.dataset.w+"%";});
});

const tt=document.getElementById("tt");
document.addEventListener("pointerover",e=>{const t=e.target.closest("[data-tip]");
  if(!t)return;tt.textContent=t.getAttribute("data-tip");tt.style.opacity="1";});
document.addEventListener("pointermove",e=>{if(tt.style.opacity==="1"){
  tt.style.left=e.clientX+"px";tt.style.top=(e.clientY-6)+"px";}});
document.addEventListener("pointerout",e=>{if(e.target.closest("[data-tip]"))tt.style.opacity="0";});

const root=document.documentElement;
document.getElementById("themeBtn").addEventListener("click",()=>{
  const cur=root.getAttribute("data-theme");
  const dark=cur?cur==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme",dark?"light":"dark");
});
</script>
</body>
</html>
"""


def main() -> int:
    payload = bouw_payload()
    html = (TEMPLATE
            .replace("__LABEL__", payload["gebied"])
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)))
    OUT.write_text(html, encoding="utf-8")
    print(f"dashboard geschreven -> {OUT.relative_to(BASE)} ({OUT.stat().st_size/1024:.1f} KB)")
    print(f"leads: {len(payload['leads'])}, score-index "
          f"{min(l['s100'] for l in payload['leads'])}–{max(l['s100'] for l in payload['leads'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
