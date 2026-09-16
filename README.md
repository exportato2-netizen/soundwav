# Soundwav

**Descargador local para Windows que convierte pistas o playlists públicas de SoundCloud a WAV PCM limpio.**

## ⬇ Descargar Soundwav

### [⬇ DESCARGAR SOUNDWAV PARA WINDOWS (ZIP)](https://github.com/exportato2-netizen/soundwav/archive/refs/heads/main.zip)

Después de descargar el ZIP: descomprímelo por completo y ejecuta **`launcher.bat`**.

---

## Versión 1.4

La v1.4 refuerza el comportamiento de la aplicación en siete áreas: una sola ventana, cierre coordinado, detección de archivos ya existentes, visualización de progreso, mejor uso de ancho de banda, limpieza estricta del WAV y una descarga visible desde GitHub.

### Una sola ventana

En Windows, Soundwav intenta abrirse como una **ventana de aplicación dedicada de Microsoft Edge o Google Chrome**, no como una pestaña normal.

- Si ejecutas `launcher.bat` mientras Soundwav ya está abierto, la segunda instancia termina y **no crea otra ventana**.
- Si cierras la ventana de Soundwav, el servidor local también se apaga.
- Si el proceso principal termina normalmente, la ventana dedicada también se cierra.

### No volver a descargar lo que ya existe

Soundwav mantiene un historial interno en:

```text
%LOCALAPPDATA%\soundwav
```

Además del historial de `yt-dlp`, antes de una descarga comprueba el destino esperado. Si ya existe un WAV válido y verificado con solo los chunks RIFF `fmt ` y `data`, se omite esa pista salvo que actives **volver a descargar**.

Esto permite cerrar y volver a abrir la aplicación sin volver a bajar las mismas pistas cuando la ruta de salida sigue siendo la misma.

### Limpieza estricta del WAV

Cada pista se procesa así:

1. El archivo fuente se descarga a una carpeta temporal privada bajo `%LOCALAPPDATA%\soundwav\temp`.
2. FFmpeg convierte el primer stream de audio a PCM 16 o 24 bits sin copiar metadatos ni capítulos.
3. Soundwav reconstruye el contenedor RIFF y conserva exclusivamente los chunks `fmt ` y `data`.
4. Se eliminan atributos extendidos del archivo cuando el sistema lo permite y, en Windows, se intenta eliminar también `Zone.Identifier`.
5. Se vuelve a verificar la estructura final antes de publicar el WAV.
6. Los temporales y el archivo fuente se eliminan.

Por diseño, el WAV final no conserva `LIST/INFO`, `BEXT`, `iXML`, carátulas, capítulos, URL, comentarios, tags de artista/álbum heredados, licencia, copyright textual, IDs del extractor ni identificadores del software de conversión.

El nombre final tampoco incluye el ID de SoundCloud. Ejemplo:

```text
001 - Nombre de la pista.wav
```

**Importante:** esto elimina metadatos y rastros técnicos del archivo. No cambia quién posee los derechos de una obra y no puede eliminar de forma garantizada una marca o identificación que esté incorporada en las propias muestras de audio sin modificar ese audio.

### Progreso y velocidad

La interfaz muestra valores formateados por Soundwav, sin reutilizar las cadenas de consola de `yt-dlp`:

- porcentaje real calculado desde bytes descargados;
- pistas completadas / total;
- pistas ya existentes omitidas;
- velocidad en KB/s, MB/s o GB/s;
- tiempo restante en segundos/minutos/horas;
- fuente de audio elegida por `yt-dlp` en el registro.

### Mejor uso de la conexión

Soundwav sigue pidiendo a `yt-dlp` la **mejor fuente de audio disponible** con `bestaudio/best`. El extractor de SoundCloud da prioridad al formato Original cuando SoundCloud lo ofrece y la sesión tiene acceso.

Para streams HLS/DASH, la v1.4 usa hasta **8 fragmentos simultáneos** y no añade una pausa artificial entre solicitudes. Esto puede aumentar mucho la velocidad frente al valor por defecto de un solo fragmento. En una descarga HTTP directa, la velocidad máxima sigue dependiendo del servidor/CDN y de la conexión disponible.

## Uso

1. Descarga el ZIP desde el botón superior.
2. Descomprime todos los archivos.
3. Ejecuta `launcher.bat` en Windows 10 u 11.
4. Si no hay Python 3.11 o superior, el lanzador intentará instalar Python automáticamente.
5. Pega una URL pública de SoundCloud.
6. Elige WAV PCM 24 o 16 bits y pulsa **Descargar**.

Los WAV quedan por defecto en:

```text
%USERPROFILE%\Music\WAV_Descargas
```

Si la carpeta Música está redirigida a otro disco, Soundwav publica el WAV mediante una copia temporal verificada en el volumen de destino y después realiza el reemplazo final dentro de ese mismo volumen.

## Seguridad de la interfaz local

El servidor escucha solo en `127.0.0.1`. Cada ejecución genera un token aleatorio obligatorio para las llamadas `/api/` y se rechazan encabezados `Host` distintos de `127.0.0.1` o `localhost`.

## Actualizar componentes

Ejecuta `ACTUALIZAR.bat`. El script llama primero a `launcher.bat --setup-only`, de modo que puede reparar un `.venv` dañado o ligado a un Python incompatible antes de actualizar las dependencias.

## Requisitos

- Windows 10 u 11.
- Conexión a Internet.
- Python 3.11 o superior; el lanzador intenta instalar Python 3.14 si hace falta.
- El instalador de respaldo contempla Windows x86, x64 y ARM64.

## Archivos principales

- `app.py`: entrada segura v1.4.
- `v14_download.py`: progreso, chequeo de existentes, limpieza adicional y concurrencia de descarga.
- `v14_window.py`: instancia única, ventana dedicada y cierre coordinado.
- `privacy_patch.py`: conversión, aislamiento temporal y verificación RIFF.
- `hardening.py`: token local y validación de `Host`.
- `_core_app.py` / `_core_app.src`: núcleo interno protegido.
- `launcher.bat`: preparación automática y arranque.
- `ACTUALIZAR.bat`: reparación y actualización de dependencias.

## Uso responsable

Utiliza esta herramienta únicamente con contenido propio, con autorización del titular o cuando la legislación aplicable permita la descarga. No está diseñada para evadir DRM, cuentas privadas ni controles de acceso.
