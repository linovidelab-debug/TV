# Usar el optimizador desde un iPhone

El iPhone no puede instalar el programa `adb` de Google, pero `tv_optimizer.py`
trae su propio cliente ADB escrito en Python, así que basta con una app gratuita.

## 1. Preparar el TV (una sola vez)

1. **Ajustes → Preferencias del dispositivo → Información**: presiona
   **Compilación** 7 veces hasta ver "Ahora eres desarrollador".
2. **Ajustes → Preferencias del dispositivo → Opciones de desarrollador**:
   activa **Depuración USB** y, si aparece, **Depuración de red / ADB por red**.
3. Anota la IP del TV: **Ajustes → Red e Internet → (tu red Wi-Fi)**.

## 2. Preparar el iPhone (una sola vez)

1. Instala **a-Shell** (gratis) desde el App Store.
2. Ábrela y escribe este comando para descargar el script:

   ```
   curl -LO https://raw.githubusercontent.com/linovidelab-debug/TV/claude/caixun-android-tv-optimization-ex1ilo/tv_optimizer.py
   ```

## 3. Uso

El iPhone debe estar conectado al **mismo Wi-Fi** que el TV.

```
python3 tv_optimizer.py buscar
python3 tv_optimizer.py todo 192.168.1.50
```

(reemplaza `192.168.1.50` por la IP de tu TV)

- La primera vez, iOS pregunta si a-Shell puede **acceder a la red local**:
  responde **Permitir**. Si `buscar` no encontró nada esa primera vez, ejecútalo
  de nuevo.
- La primera conexión genera una clave de seguridad (puede tardar hasta un
  minuto) y el TV muestra **"¿Permitir depuración?"**: marca *Permitir siempre*
  y acepta.
- No bloquees el iPhone ni cambies de app mientras corre `optimizar`
  (la compilación de apps puede tardar varios minutos).

Los comandos disponibles (`analizar`, `limpiar`, `optimizar`, `desactivar`,
`restaurar`) son los mismos descritos en [README.md](README.md).

Para ver el informe generado: `cat informe_tv_*.txt`, o abre la app **Archivos →
En mi iPhone → a-Shell**.
