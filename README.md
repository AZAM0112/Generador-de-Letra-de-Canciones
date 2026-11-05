# Generador de Letra de Canciones

Genera un video MP4 con la letra animada de una canción cristiana a partir de su audio
(título grande al inicio; a la derecha en blanco lo que viene, a la izquierda en amarillo lo que se canta).

```python
from generador_letras import generar_video_letra
generar_video_letra("cancion.mp3", titulo="Mi canción", letra="letra.txt", separar_voz=True)
```

```bash
pip install -r generador_letras/requirements.txt
python -m generador_letras cancion.mp3 --letra letra.txt
```

Documentación completa, guía para mejorar la precisión y formato del JSON: [generador_letras/README.md](generador_letras/README.md).

## Forma rápida: una carpeta y un solo comando

1. Pon en la carpeta `canciones/` el audio y su letra **con el mismo nombre**:
   `Tómalo - Hillsong.mp3` y `Tómalo - Hillsong.txt`.
2. Ejecuta (o en VS Code: **Ctrl+Shift+B**, usa el archivo `.vscode/tasks.json`):
   ```
   py -3.12 generar.py
   ```
3. Se crean junto al audio `..._letra.letra.json` (letra con tiempos) y `..._letra.mp4`.
4. Si corriges el JSON, rehaz el video con `py -3.12 generar.py --forzar`: usa el JSON, no vuelve a transcribir.
   (Para transcribir de nuevo, borra el JSON.)

Para rehacer **una sola** canción: `py -3.12 generar.py --forzar --cancion tomalo` (basta con parte del nombre, sin importar tildes ni mayúsculas).

Las canciones que ya tienen video se omiten; una canción con error no detiene a las demás.

## Con GitHub (sin instalar nada en tu PC)

1. Sube a `canciones/` el audio y la letra (desde la web: **Add file → Upload files**).
2. Ve a la pestaña **Actions → Generar videos de letras → Run workflow** (elige el modelo).
3. Al terminar, descarga el resultado en **Artifacts → videos-de-letras** (MP4 y JSON).
4. Para corregir tiempos: edita el JSON en tu PC, súbelo a `canciones/` y ejecuta el workflow con *forzar* activado.

Notas: usa un repositorio **privado** si subes audios con derechos de autor. En GitHub el
procesamiento es solo con CPU y una canción puede tardar varios minutos (el límite del trabajo es 4 h).

## Tamaño de la letra

La letra ya sale grande (se ajusta sola para que quepan los dos versos). Para cambiarlo: `py -3.12 generar.py --forzar --tamano-letra 0.8` (más chica) o `1.2` (más grande, si cabe).

## GPU NVIDIA (más rápido y preciso, automático)

El programa elige solo, con el mismo Ctrl+Shift+B en cualquier laptop:
- **Con GPU NVIDIA:** modelo `large-v3` en la GPU (el más preciso).
- **Sin GPU:** modelo `medium` en CPU.
- Si la GPU falla (faltan librerías, poca memoria), avisa y continúa con la CPU.

En la laptop con NVIDIA, instala una vez las librerías CUDA:
```
py -3.12 -m pip install -r generador_letras\requirements-gpu.txt
```
y mantén actualizado el driver de NVIDIA. En la otra laptop no hace falta.

## Ajuste al tempo de la canción (automático)

Después de sincronizar la letra, el programa detecta el **tempo (BPM)** y el pulso de la canción y
mueve el inicio de cada verso al **tiempo o medio tiempo más cercano** (muchos versos entran en el
"y" del compás). También corrige el retraso o adelanto general que suele tener el reconocimiento.

- El JSON guarda `"tempo_bpm"` y, en los versos dudosos, un campo `"revisar"` con el motivo:
  - `entre dos pulsos`: el inicio cae justo en medio; no se movió, revísalo a mano.
  - `no se reconoció en el audio: tiempo estimado`: su primera palabra no se escuchó; el tiempo se calculó.
  - `choca con el verso anterior`: dos versos irían al mismo pulso.
- Si la canción no tiene un pulso claro (sin batería), no se toca nada y lo avisa.
- Si el BPM detectado es el doble o la mitad del real, fuérzalo: `py -3.12 generar.py --cancion nombre --bpm 72`.
- Para desactivarlo: `--sin-tempo`. No se aplica al rehacer desde un JSON ya revisado.

## Revisión automática completa

Cada canción nueva pasa sola por todas estas etapas (no hay que hacer nada distinto: Ctrl+Shift+B):

1. **Reconocimiento** con Whisper y emparejamiento con tu letra (`.txt`).
2. **Segunda pasada**: Whisper vuelve a alinear la **letra real**, palabra por palabra, por tramos
   de 30 s. Corrige sobre todo los versos que en la primera pasada "no se escucharon".
   (Con `--rapido` se omite: más rápido, menos preciso.)
3. **Coros**: lo que se repite se canta igual. Con las repeticiones bien escuchadas se corrigen
   los versos que no se oyeron en otra repetición.
4. **Tempo**: ajuste de cada verso al pulso de la canción.
5. **Informe**: si todo cuadra, dice *"los N versos pasaron todas las comprobaciones"*. Si no,
   lista los dudosos (campo `"revisar"` en el JSON).

Con tempo detectado, además, la animación va **al ritmo**: el texto se desplaza durante medio
tiempo musical y llega en amarillo justo en el pulso en que empieza el verso.

### Página de revisión (opcional)

Junto a cada canción se crea `<canción>_revisar.html`. Ábrela con doble clic (Chrome o Edge):
reproduce la canción, resalta el verso que suena y muestra en naranja los dudosos.

| Tecla | Acción |
|---|---|
| Espacio | reproducir / pausa |
| ↑ ↓ | elegir verso |
| M | marcar ahora el inicio del verso elegido (se ajusta al pulso) y pasar al siguiente |
| ← → | mover el inicio ±0,05 s (con Shift: medio tiempo) |
| P | escuchar desde el verso elegido |

Pulsa **Guardar JSON corregido**, guárdalo encima del JSON de la canción y rehaz el video
(`py -3.12 generar.py --forzar --cancion nombre`).
