"""Página de revisión: un HTML junto a la canción para escuchar y corregir tiempos con el teclado.

Se abre con doble clic (Chrome o Edge). No necesita internet ni instalar nada.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from .modelos import Verso

_PLANTILLA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisar: __TITULO__</title>
<style>
  :root { color-scheme: dark; --fondo:#111; --panel:#1c1c1c; --texto:#eee; --tenue:#999;
          --amarillo:#ffdd00; --aviso:#ff9f1a; --sel:#2a3d66; }
  body { margin:0; font:16px/1.4 system-ui, sans-serif; background:var(--fondo); color:var(--texto); }
  header { position:sticky; top:0; background:var(--panel); padding:12px 16px; border-bottom:1px solid #333; z-index:1; }
  h1 { margin:0 0 4px; font-size:20px; }
  .info { color:var(--tenue); font-size:14px; }
  audio { width:100%; margin:8px 0; }
  .barra { display:flex; flex-wrap:wrap; gap:12px; align-items:center; font-size:14px; }
  button { font:inherit; padding:6px 14px; border-radius:6px; border:1px solid #555; background:#2b2b2b; color:var(--texto); cursor:pointer; }
  button.principal { background:var(--amarillo); color:#000; border-color:var(--amarillo); font-weight:600; }
  table { width:100%; border-collapse:collapse; }
  td { padding:6px 10px; border-bottom:1px solid #262626; vertical-align:middle; }
  td.n { color:var(--tenue); width:2.5em; text-align:right; }
  td.t { width:7em; }
  input.tiempo { width:6em; font:inherit; background:#000; color:var(--texto); border:1px solid #444; border-radius:4px; padding:2px 4px; }
  input.texto { width:100%; font:inherit; background:transparent; color:inherit; border:1px solid transparent; }
  input.texto:focus { border-color:#444; background:#000; }
  tr.sel { background:var(--sel); }
  tr.suena td.txt input { color:var(--amarillo); font-weight:600; }
  tr.aviso td.av { color:var(--aviso); }
  td.av { font-size:13px; color:var(--tenue); width:30%; }
  tr.oculto { display:none; }
  kbd { background:#333; border-radius:3px; padding:0 5px; font-size:13px; }
  #estado { color:var(--amarillo); }
</style>
</head>
<body>
<header>
  <h1>__TITULO__</h1>
  <div class="info" id="resumen"></div>
  <audio id="audio" controls preload="auto" src="__AUDIO__"></audio>
  <div class="barra">
    <span><kbd>Espacio</kbd> reproducir/pausa · <kbd>M</kbd> marcar inicio del verso elegido ahora ·
      <kbd>↑</kbd><kbd>↓</kbd> elegir verso · <kbd>←</kbd><kbd>→</kbd> mover ±0,05 s (con <kbd>Shift</kbd>: medio tiempo) ·
      <kbd>P</kbd> escuchar desde el verso</span>
  </div>
  <div class="barra" style="margin-top:8px">
    <label><input type="checkbox" id="pulso" checked> Ajustar al pulso</label>
    <label><input type="checkbox" id="soloAvisos"> Solo versos con aviso</label>
    <button class="principal" id="guardar">Guardar JSON corregido</button>
    <span id="estado"></span>
  </div>
</header>
<table><tbody id="filas"></tbody></table>
<script>
const DATOS = __DATOS__;
const NOMBRE_JSON = __NOMBRE_JSON__;
const audio = document.getElementById("audio");
const filas = document.getElementById("filas");
const versos = DATOS.versos.map(v => Object.assign({ tocado: false }, v));
const medio = DATOS.tempo_bpm ? 30 / DATOS.tempo_bpm : null;
let elegido = 0;

function redondear(t) { return Math.round(t * 100) / 100; }
function alPulso(t) {
  if (!medio || !document.getElementById("pulso").checked) return redondear(t);
  const o = DATOS.pulso_inicio || 0;
  return redondear(o + Math.round((t - o) / medio) * medio);
}
function resumen() {
  const avisos = versos.filter(v => v.revisar && !v.tocado).length;
  document.getElementById("resumen").textContent =
    `${versos.length} versos` + (DATOS.tempo_bpm ? ` · ${DATOS.tempo_bpm} BPM` : "") +
    (avisos ? ` · ${avisos} con aviso (en naranja)` : " · sin avisos pendientes");
}
function pintar() {
  filas.innerHTML = "";
  versos.forEach((v, i) => {
    const tr = document.createElement("tr");
    tr.dataset.i = i;
    if (v.revisar && !v.tocado) tr.classList.add("aviso");
    tr.innerHTML = `<td class="n">${i + 1}</td>
      <td class="t"><input class="tiempo" type="number" step="0.05" min="0" value="${v.inicio.toFixed(2)}"></td>
      <td class="txt"><input class="texto" value=""></td>
      <td class="av">${v.tocado ? "corregido" : (v.revisar || "")}</td>`;
    tr.querySelector(".texto").value = v.texto;
    tr.querySelector(".tiempo").addEventListener("change", e => fijar(i, parseFloat(e.target.value), false));
    tr.querySelector(".texto").addEventListener("change", e => { v.texto = e.target.value; v.tocado = true; resumen(); });
    tr.addEventListener("click", e => { if (e.target.tagName !== "INPUT") { elegir(i); escucharDesde(i); } });
    filas.appendChild(tr);
  });
  filtrar(); elegir(elegido); resumen();
}
function filtrar() {
  const solo = document.getElementById("soloAvisos").checked;
  [...filas.children].forEach(tr => tr.classList.toggle("oculto", solo && !tr.classList.contains("aviso")));
}
function elegir(i) {
  elegido = Math.max(0, Math.min(versos.length - 1, i));
  [...filas.children].forEach(tr => tr.classList.toggle("sel", +tr.dataset.i === elegido));
  const tr = filas.children[elegido];
  if (tr) tr.scrollIntoView({ block: "nearest" });
}
function fijar(i, t, ajustar = true) {
  if (!isFinite(t)) return;
  const v = versos[i];
  const duracion = Math.max(v.fin - v.inicio, 0.3);
  v.inicio = Math.max(0, ajustar ? alPulso(t) : redondear(t));
  v.fin = redondear(v.inicio + duracion);
  v.tocado = true;
  const tr = filas.children[i];
  tr.querySelector(".tiempo").value = v.inicio.toFixed(2);
  tr.classList.remove("aviso");
  tr.querySelector(".av").textContent = "corregido";
  resumen();
}
function escucharDesde(i) { audio.currentTime = Math.max(0, versos[i].inicio - 2); audio.play(); }

audio.addEventListener("timeupdate", () => {
  const t = audio.currentTime;
  let actual = -1;
  versos.forEach((v, i) => { if (v.inicio <= t) actual = i; });
  [...filas.children].forEach(tr => tr.classList.toggle("suena", +tr.dataset.i === actual));
});
document.getElementById("soloAvisos").addEventListener("change", filtrar);
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" && e.target.type !== "checkbox") return;
  const paso = e.shiftKey && medio ? medio : 0.05;
  if (e.code === "Space") { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
  else if (e.key === "m" || e.key === "M") { fijar(elegido, audio.currentTime - 0.1); elegir(elegido + 1); }
  else if (e.key === "ArrowDown") { e.preventDefault(); elegir(elegido + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); elegir(elegido - 1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); fijar(elegido, versos[elegido].inicio + paso, false); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); fijar(elegido, versos[elegido].inicio - paso, false); }
  else if (e.key === "p" || e.key === "P") { escucharDesde(elegido); }
});

function jsonCorregido() {
  const salida = { titulo: DATOS.titulo };
  if (DATOS.tempo_bpm) salida.tempo_bpm = DATOS.tempo_bpm;
  if (DATOS.tempo_bpm && DATOS.pulso_inicio != null) salida.pulso_inicio = DATOS.pulso_inicio;
  const ordenados = [...versos].sort((a, b) => a.inicio - b.inicio);
  salida.versos = ordenados.map(v => {
    const r = { inicio: v.inicio, fin: Math.max(v.fin, redondear(v.inicio + 0.3)), texto: v.texto };
    if (v.nueva_pagina) r.nueva_pagina = true;
    if (v.revisar && !v.tocado) r.revisar = v.revisar;
    return r;
  });
  return JSON.stringify(salida, null, 2);
}
document.getElementById("guardar").addEventListener("click", async () => {
  const texto = jsonCorregido();
  const estado = document.getElementById("estado");
  try {
    if (window.showSaveFilePicker) {
      const archivo = await window.showSaveFilePicker({ suggestedName: NOMBRE_JSON,
        types: [{ description: "Letra (JSON)", accept: { "application/json": [".json"] } }] });
      const w = await archivo.createWritable(); await w.write(texto); await w.close();
      estado.textContent = "Guardado. Ahora rehaz el video de esta canción.";
      return;
    }
  } catch (err) { if (err.name === "AbortError") return; }
  const a = document.createElement("a");
  a.href = "data:application/json;charset=utf-8," + encodeURIComponent(texto);
  a.download = NOMBRE_JSON;
  document.body.appendChild(a); a.click(); a.remove();
  estado.textContent = `Descargado: copia ${NOMBRE_JSON} a la carpeta de la canción (reemplázalo) y rehaz el video.`;
});
pintar();
</script>
</body>
</html>
"""


def _escapar_html(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _json_en_script(dato) -> str:
    return json.dumps(dato, ensure_ascii=False).replace("</", "<\\/")


def generar_pagina_revision(
    audio: Path, ruta_json: Path, titulo: str, versos: List[Verso],
    tempo_bpm: Optional[float] = None, pulso_inicio: Optional[float] = None,
) -> Path:
    """Escribe `<audio>_revisar.html` junto al audio y devuelve su ruta."""
    audio, ruta_json = Path(audio), Path(ruta_json)
    datos = {
        "titulo": titulo,
        "tempo_bpm": tempo_bpm,
        "pulso_inicio": pulso_inicio,
        "versos": [
            {"inicio": round(v.inicio, 2), "fin": round(v.fin, 2), "texto": v.texto,
             "nueva_pagina": v.pagina_nueva, "revisar": v.revisar}
            for v in versos
        ],
    }
    html = (
        _PLANTILLA.replace("__TITULO__", _escapar_html(titulo))
        .replace("__AUDIO__", _escapar_html(quote(audio.name)))
        .replace("__NOMBRE_JSON__", _json_en_script(ruta_json.name))
        .replace("__DATOS__", _json_en_script(datos))
    )
    ruta = audio.with_name(audio.stem + "_revisar.html")
    ruta.write_text(html, encoding="utf-8")
    return ruta
