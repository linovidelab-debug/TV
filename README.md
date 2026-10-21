# Optimizador para Smart TV Caixun (Android TV)

Herramienta para **encontrar el TV en tu red Wi-Fi, analizarlo y acelerarlo**
cuando dice "memoria casi llena" o está lento al encender o abrir apps.

Se ejecuta en un **computador conectado al mismo Wi-Fi que el TV**.

## 1. Preparar el TV (una sola vez)

1. **Ajustes → Preferencias del dispositivo → Información**: baja hasta
   **Compilación** y presiona OK **7 veces** hasta ver "Ahora eres desarrollador".
2. **Ajustes → Preferencias del dispositivo → Opciones de desarrollador**:
   activa **Depuración USB** y, si aparece, **Depuración de red / ADB por red**.
3. Anota la IP del TV: **Ajustes → Red e Internet → (tu red Wi-Fi)**.

## 2. Preparar el computador (una sola vez)

1. Instala **Python 3**: <https://www.python.org/downloads/>.
   En Windows, marca "Add Python to PATH".
2. Descarga **SDK Platform-Tools** (contiene `adb`):
   <https://developer.android.com/tools/releases/platform-tools>
3. Pon `tv_optimizer.py` (y `optimizar_tv.bat` en Windows) **junto a** la
   carpeta `platform-tools` descomprimida.

## 3. Uso

En Windows puedes hacer doble clic en `optimizar_tv.bat`. O desde una terminal:

```bash
python tv_optimizer.py buscar              # busca el TV en el Wi-Fi
python tv_optimizer.py todo 192.168.1.50   # conecta, analiza, limpia y optimiza
```

La primera vez, el TV mostrará **"¿Permitir depuración?"**: marca *Permitir
siempre* y acepta.

| Comando | Qué hace |
|---|---|
| `buscar` | Escanea la red local buscando dispositivos con ADB (puerto 5555). |
| `conectar IP` | Conecta con el TV. |
| `analizar` | Modelo, almacenamiento, RAM, apps más pesadas, caché, archivos grandes. Guarda un informe `.txt`. |
| `limpiar` | Vacía la caché de todas las apps, cierra apps en segundo plano y ofrece borrar archivos grandes (pregunta uno por uno). |
| `optimizar` | Acelera animaciones (0.5x) y precompila las apps para que abran más rápido. Ofrece reiniciar. |
| `desactivar` | Ofrece desactivar apps del sistema prescindibles y apps que no uses (pregunta una por una). |
| `restaurar` | Revierte animaciones y reactiva todo lo que se desactivó. |

## Seguridad

- No se borra ni desactiva nada sin tu confirmación.
- Desactivar una app no la elimina; `restaurar` la vuelve a activar.
- Al terminar puedes apagar **Depuración USB / de red** en el TV.

## Otros consejos

- Desinstala las apps que no uses (Ajustes → Apps): es lo que más espacio libera.
- Si existe **Inicio rápido / Instant Power On** en Ajustes → Energía, actívalo.
- Mantén al menos 1–2 GB libres.
- Si sigue muy lento, haz una copia de tus cuentas y considera un
  **restablecimiento de fábrica** (Ajustes → Preferencias del dispositivo → Restablecer).
