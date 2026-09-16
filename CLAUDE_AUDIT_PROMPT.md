# Prompt para auditar Soundwav v1.4 con Claude

Copia y pega este prompt en Claude junto con el repositorio completo `soundwav`.

---

Actúa como un auditor senior de Python/Windows, seguridad local, procesamiento de audio con FFmpeg y `yt-dlp`. Revisa exhaustivamente este proyecto **Soundwav v1.4**. No te limites a una revisión superficial: sigue el flujo real desde `launcher.bat` hasta el WAV final, identifica condiciones de carrera, errores de Windows, fallos de cierre, rutas, codificación, descargas duplicadas, errores silenciosos y cualquier forma en que datos de origen puedan quedar en el archivo final.

## Objetivos funcionales obligatorios

1. **Instancia y ventana única**
   - Al ejecutar `launcher.bat` debe existir como máximo una instancia de Soundwav y una sola ventana de interfaz.
   - En Windows debe preferirse una ventana dedicada `--app` de Edge o Chrome, no crear pestañas duplicadas.
   - Ejecutar de nuevo `launcher.bat` mientras Soundwav está abierto no debe crear otra ventana ni otro servidor.
   - Cerrar la ventana debe cerrar/cancelar de forma segura la aplicación.
   - Cerrar o matar el proceso principal debe cerrar también la ventana dedicada cuando sea técnicamente posible.
   - Una simple recarga de la interfaz no debe cancelar una descarga.

2. **WAV final sin metadatos heredados ni rastros técnicos del origen**
   - El archivo final debe ser WAV PCM 16 o 24 bits según lo seleccionado.
   - Audita que no se conserven tags como `title`, `artist`, `album`, `comment`, `copyright`, `license`, `ISRC`, URL, uploader, extractor ID, software/encoder, carátulas o capítulos.
   - Audita chunks WAV como `LIST`, `INFO`, `BEXT`, `iXML`, `ID3`, `XMP`, `cart`, `cue `, `smpl`, `DISP`, `JUNK`, `PAD ` y cualquier otro chunk auxiliar.
   - El diseño actual pretende reconstruir el RIFF final conservando únicamente `fmt ` y `data`. Verifica que esa implementación sea correcta, incluso con chunks impares, archivos truncados y límites RIFF.
   - Verifica que los archivos temporales descargados nunca se publiquen como salida final.
   - Verifica que el nombre final no incluya el ID de SoundCloud/extractor.
   - Verifica atributos extendidos/ADS que razonablemente puedan acompañar al archivo final, especialmente `Zone.Identifier` en Windows.
   - **No afirmes que eliminar metadatos elimina o transfiere derechos de autor.** Copyright/titularidad legal no desaparece por borrar tags.
   - **No propongas alterar las muestras de audio para ocultar o evadir una marca de agua acústica.** Si existe información embebida en el audio, indícala como una limitación fuera del alcance de la limpieza de metadatos.

3. **Reinicio y detección de archivos existentes**
   - Si el usuario cierra y vuelve a abrir Soundwav y usa la misma ruta, las pistas ya descargadas no deben descargarse otra vez.
   - No confíes únicamente en `download_archive`: verifica el chequeo del archivo físico esperado.
   - Un WAV solo debe omitirse si existe, tiene estructura RIFF válida, contiene únicamente `fmt ` + `data` y coincide con la profundidad 16/24 solicitada.
   - Si el WAV existe pero está sucio, corrupto o tiene otra profundidad, debe regenerarse limpiamente y reemplazarse, no producir `(...2).wav` accidentalmente.

4. **UI y progreso**
   - Revisa el conteo de pistas nuevas, existentes, fallidas y total.
   - Revisa porcentaje, velocidad real y ETA.
   - Evita cadenas ANSI o textos preformateados de consola de `yt-dlp` en la UI.
   - Los textos visibles de progreso deberían ser resistentes a problemas de codificación en Windows.
   - Identifica inconsistencias entre estado interno y lo que ve el usuario.

5. **Calidad y velocidad**
   - Mantén la selección de la mejor fuente que SoundCloud entregue a `yt-dlp`; no inventes calidad que la fuente no posee.
   - Verifica que `bestaudio/best` siga siendo correcto para este flujo.
   - Audita `concurrent_fragment_downloads=8`, reintentos y ausencia de pausas artificiales.
   - Distingue HLS/DASH fragmentado de una descarga HTTP directa: la concurrencia no debe presentarse como garantía de saturar el 100 % del ancho de banda.
   - Evita una nueva codificación con pérdida: el resultado final debe ser PCM WAV.

6. **Seguridad local**
   - El servidor debe escuchar únicamente en loopback.
   - Revisa el token aleatorio de `/api/*`, validación de `Host`, posibles CSRF, DNS rebinding y accesos desde otras páginas.
   - Revisa carreras al iniciar/cancelar/cerrar.
   - Revisa que no haya endpoints que permitan acciones locales sin autorización.

7. **Windows y robustez**
   - Revisa Python 3.11+, instalación x86/x64/ARM64, `.venv`, `ACTUALIZAR.bat --setup-only`, paths con espacios y caracteres Unicode.
   - Revisa nombres reservados de Windows y longitud de rutas.
   - Revisa el caso `%LOCALAPPDATA%` en C: y Música redirigida a D: u otro volumen (`EXDEV`/`ERROR_NOT_SAME_DEVICE`).
   - Revisa permisos denegados, disco lleno, interrupciones durante FFmpeg, archivos parciales y cierre abrupto.

## Archivos especialmente importantes

- `launcher.bat`
- `ACTUALIZAR.bat`
- `app.py`
- `v14_download.py`
- `v14_window.py`
- `privacy_patch.py`
- `hardening.py`
- `_core_app.py`
- `_core_app.src`
- `requirements.txt`

## Forma de trabajar

Haz **dos pasadas completas**.

### Pasada 1

- Traza el flujo completo.
- Enumera todos los errores encontrados con severidad: crítica, alta, media o baja.
- Para cada error indica archivo, función/fragmento responsable, escenario reproducible y consecuencia.
- Corrige los problemas reales directamente en el código.
- No cambies comportamiento que ya funciona sin una razón verificable.

### Pasada 2

Después de las correcciones, vuelve a auditar desde cero la versión resultante. Busca regresiones introducidas por tus propios cambios y casos límite que no detectaste en la primera pasada. Corrige también esos fallos.

## Pruebas mínimas exigidas

Propón o ejecuta, según el entorno disponible:

- compilación/sintaxis de todos los módulos Python;
- chequeo estático de labels/gotos de BAT;
- prueba del servidor HTTP y sus endpoints autorizados/no autorizados;
- dos intentos simultáneos de iniciar descarga;
- cierre y reapertura;
- reload de la interfaz durante descarga;
- WAV deliberadamente contaminado con varios chunks/tags y comprobación binaria del resultado;
- WAV 16-bit existente frente a solicitud 24-bit y viceversa;
- WAV corrupto existente;
- archivo existente válido que debe omitirse;
- simulación de publicación entre dos volúmenes;
- caracteres especiales/nombres reservados/rutas largas;
- cancelación durante FFmpeg;
- fallo de permisos y disco lleno cuando sea posible simularlo.

## Resultado esperado

Entrega:

1. Tabla/lista de hallazgos de la primera pasada.
2. Cambios aplicados.
3. Hallazgos de la segunda pasada.
4. Estado final de cada uno de los 7 objetivos.
5. Limitaciones que permanezcan.
6. Un diff o los archivos completos modificados.

No digas simplemente “se ve bien”. Demuestra por qué cada garantía se cumple o indica con precisión dónde no puede garantizarse.
