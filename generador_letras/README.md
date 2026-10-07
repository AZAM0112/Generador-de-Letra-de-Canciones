# Generador de letras en video — Ministerio de Alabanza *La Voz de Dios*

Entrega el audio de una canción y obtén un **video MP4** con la letra sincronizada:

* Al inicio, el **título grande y al centro**.
* Pantalla dividida en dos mitades:
  * **Derecha (blanco):** lo que viene — máximo **2 versos**. Si lo que viene es una sola
    palabra (el "Jesús" de un coro), se muestra **solo esa palabra**.
  * **Izquierda (amarillo):** lo que se está cantando ahora.
* Cuando llega el momento de cantar lo siguiente, el texto **se desplaza de la derecha a la
  izquierda y se vuelve amarillo**; lo ya cantado se desvanece y aparece lo que sigue a la derecha.
* El audio original de la canción va incluido en el MP4.

## Instalación

Requiere Python 3.9 o superior.

```bash
pip install -r generador_letras/requirements.txt
```

(`imageio-ffmpeg` incluye ffmpeg; si ya tienes ffmpeg instalado se usa el tuyo.)
La **primera vez** Whisper descarga su modelo de internet (cientos de MB hasta ~3 GB).

## Uso

### Como función

```python
from generador_letras import generar_video_letra

# Lo más simple: solo el audio. El título sale del nombre del archivo.
generar_video_letra("cuan_grande_es_dios.mp3")

# Recomendado: con la letra escrita (mucha más precisión).
generar_video_letra(
    "cuan_grande_es_dios.mp3",
    titulo="Cuán grande es Dios",
    letra="letra.txt",
    separar_voz=True,
)
```

Devuelve la ruta del MP4 (`<audio>_letra.mp4` junto al audio, o la que indiques en `salida=`).

### Desde la terminal

Ejecuta desde la carpeta que contiene `generador_letras/`:

```bash
python -m generador_letras cancion.mp3
python -m generador_letras cancion.mp3 -t "Cuán grande es Dios" --letra letra.txt --separar-voz
python -m generador_letras --help
```

Opciones principales: `--letra`, `--separar-voz`, `--modelo` (`tiny`, `small`, `medium`,
`large-v3`), `--idioma`, `--resolucion 1920x1080`, `--fps 30`, `--fondo "#000000"`,
`--fuente ruta.ttf`, `--solo-json`, `--desde-json`.

## Flujo recomendado para el equipo (≈ 5 minutos por canción)

1. **Pega la letra completa** en un `.txt` (un verso por línea, repitiendo los coros tal como
   se cantan). Una línea en blanco o un marcador como `[Coro]` separa estrofas.
2. Genera primero solo el JSON para revisar:
   `python -m generador_letras cancion.mp3 --letra letra.txt --separar-voz --solo-json`
3. Abre `cancion_letra.letra.json`, corrige si algún tiempo o palabra quedó mal (ver formato abajo).
4. Genera el video con lo revisado, sin volver a transcribir:
   `python -m generador_letras cancion.mp3 --desde-json cancion_letra.letra.json`

Formato del JSON (se puede editar a mano; los tiempos son segundos del audio original):

```json
{
  "titulo": "Cuán grande es Dios",
  "versos": [
    {"inicio": 12.4, "fin": 15.1, "texto": "El esplendor de un Rey"},
    {"inicio": 15.4, "fin": 18.0, "texto": "Vestido en majestad", "nueva_pagina": true}
  ]
}
```

## Cómo funciona

```
audio ──(opcional Demucs: aísla la voz)──► Whisper ──► palabras con tiempos
                                                        │
              letra.txt (opcional) ─► alineación ───────┤
                                                        ▼
                      palabras → versos (por pausas/puntuación/largo) → páginas de 1–2 versos
                                                        ▼
                      dibujo cuadro a cuadro (Pillow) ─► ffmpeg ─► MP4 con el audio original
```

* **Versos:** se cortan por pausas (≥ 0.8 s), puntuación y fin de segmento; los muy largos se
  parten en su pausa más grande (máx. 8 palabras / 40 caracteres).
* **Páginas:** hasta 2 versos. Un verso de **una sola palabra va siempre solo**. Una pausa larga
  (> 3 s) o una estrofa nueva abren página nueva.
* **Si la voz entra casi al inicio** del audio, se antepone un breve silencio para que el título
  alcance a verse (el audio se retrasa igual, así que todo sigue sincronizado).
* Parámetros de animación (duración del desplazamiento, cuánto se queda lo cantado, etc.) son
  constantes al inicio de `render.py` y `segmentacion.py`.

## Cómo hacer que el sistema automático funcione mejor

Whisper fue entrenado con voz hablada; en canciones con banda se equivoca más. En orden de impacto:

1. **Entrega la letra (`--letra`)** — es la mejora más grande. Whisper deja de "adivinar" el texto
   y solo se usa para saber *cuándo* se canta cada palabra; aunque se equivoque en varias palabras,
   la letra que se muestra es la tuya (ortografía, tildes, mayúsculas, saltos de línea).
2. **Aísla la voz (`--separar-voz`, requiere `pip install demucs`)** — quita batería, bajo y
   guitarras antes de transcribir. Mejora mucho tiempos y reconocimiento. Si Demucs falla, el
   programa avisa y continúa con el audio completo.
3. **Usa un modelo grande y GPU** — `large-v3` es el más preciso (por defecto si hay GPU NVIDIA;
   en CPU el defecto es `medium`). En CPU, `--modelo large-v3` funciona pero es lento.
4. **Mejor audio de entrada** — la grabación de estudio o un *stem*/pista de voz funciona mucho mejor
   que un audio de celular en el culto, con coros y reverberación.
5. **Revisa el JSON antes del video final** — 2 minutos de revisión evitan errores frente a la
   congregación. Si una canción sale bien, guarda su JSON y reutilízalo.
6. **Prueba `--vad`** si hay intros/instrumentales largos que generan texto inventado.
   (El programa ya descarta frases típicas inventadas como "Subtítulos por Amara.org".)

Ideas para llevarlo más lejos: alineación forzada a nivel de fonema (WhisperX / `stable-ts`)
para tiempos aún más exactos, una pequeña interfaz web para corregir tiempos arrastrando, resaltar
palabra por palabra, y una biblioteca de canciones ya corregidas para reutilizar.

## Pruebas

```bash
python -m unittest discover -s generador_letras/tests -t .
```
