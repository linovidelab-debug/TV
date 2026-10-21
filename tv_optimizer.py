#!/usr/bin/env python3
"""
Optimizador para Smart TV Android (probado pensando en TV Caixun / Android TV).

Se ejecuta en un computador o iPhone (app a-Shell) conectado a la MISMA red
Wi-Fi que el TV y se comunica con el TV mediante ADB (Android Debug Bridge).
Si no encuentra el programa 'adb', usa un cliente ADB incorporado escrito en
Python puro, por lo que no necesita instalar nada más.

Uso:
    python tv_optimizer.py buscar             # encuentra el TV en la red
    python tv_optimizer.py conectar IP        # conecta por ADB
    python tv_optimizer.py analizar           # diagnóstico + informe
    python tv_optimizer.py limpiar            # borra cachés y procesos
    python tv_optimizer.py optimizar          # animaciones + compilar apps
    python tv_optimizer.py desactivar         # desactiva apps (con confirmación)
    python tv_optimizer.py restaurar          # reactiva lo desactivado
    python tv_optimizer.py todo IP            # conectar + analizar + limpiar + optimizar

Nada se borra ni desactiva sin preguntar. Todo lo desactivado se anota en
desactivadas.txt y se puede revertir con "restaurar".
"""

import concurrent.futures
import datetime
import ipaddress
import json
import os
import re
import base64
import secrets
import shutil
import socket
import struct
import subprocess
import sys

ADB_PORT = 5555
HERE = os.path.dirname(os.path.abspath(__file__))
DISABLED_LOG = os.path.join(HERE, "desactivadas.txt")
TV_IP_FILE = os.path.join(HERE, "tv_ip.txt")
LITE_KEY_FILE = os.path.join(HERE, "adbkey.json")

# Apps del sistema que normalmente se pueden desactivar sin romper el TV.
# Se ofrecen solo si están instaladas y siempre se pregunta antes.
SAFE_SYSTEM_CANDIDATES = {
    "com.google.android.marvin.talkback": "TalkBack (lector de pantalla para accesibilidad)",
    "com.android.printspooler": "Servicio de impresión",
    "com.google.android.feedback": "Envío de comentarios a Google",
    "com.android.dreams.basic": "Salvapantallas básico",
    "com.android.dreams.phototable": "Salvapantallas de fotos",
    "com.google.android.backdrop": "Salvapantallas Ambient / Backdrop",
    "com.android.bips": "Impresión integrada",
    "com.google.android.play.games": "Google Play Juegos",
    "com.google.android.videos": "Google TV / Play Películas",
    "com.google.android.music": "Google Play Música (descontinuada)",
    "com.google.android.youtube.tvmusic": "YouTube Music",
    "com.google.android.tv.bugreportsender": "Envío de reportes de errores",
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def find_adb():
    for candidate in (
        shutil.which("adb"),
        os.path.join(HERE, "platform-tools", "adb.exe"),
        os.path.join(HERE, "platform-tools", "adb"),
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


ADB = None   # ruta al programa adb, o None para usar el cliente incorporado
LITE = None  # conexión del cliente incorporado (AdbLite)


def adb(*args, timeout=60, check=False):
    result = subprocess.run(
        [ADB, *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


# --------------------------------------------------------------------------
# Cliente ADB incorporado (Python puro, para iPhone u otros equipos sin adb)
# --------------------------------------------------------------------------

def _is_probable_prime(n, rounds=40):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(rounds):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _random_prime(bits):
    while True:
        candidate = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _is_probable_prime(candidate):
            return candidate


class AdbLite:
    """Implementación mínima del protocolo ADB por TCP (conectar, shell, reboot)."""

    VERSION = 0x01000001
    MAX_DATA = 256 * 1024
    CNXN, AUTH, OPEN, OKAY, CLSE, WRTE = (
        struct.unpack("<I", c)[0] for c in (b"CNXN", b"AUTH", b"OPEN", b"OKAY", b"CLSE", b"WRTE"))
    AUTH_TOKEN, AUTH_SIGNATURE, AUTH_RSAPUBLICKEY = 1, 2, 3
    SHA1_DIGEST_INFO = bytes.fromhex("3021300906052b0e03021a05000414")

    def __init__(self, host, port=ADB_PORT):
        self.host, self.port = host, port
        self.sock = None
        self.next_id = 1
        self.n, self.e, self.d = self._load_key()

    # --- claves RSA (el TV las recuerda tras "Permitir siempre") ---

    def _load_key(self):
        try:
            with open(LITE_KEY_FILE, encoding="utf-8") as fh:
                k = json.load(fh)
            return int(k["n"]), int(k["e"]), int(k["d"])
        except (OSError, ValueError, KeyError):
            pass
        print("Generando clave de seguridad (solo la primera vez, puede tardar ~1 minuto)...")
        e = 65537
        while True:
            p, q = _random_prime(1024), _random_prime(1024)
            n, phi = p * q, (p - 1) * (q - 1)
            if p != q and n.bit_length() == 2048 and phi % e:
                break
        d = pow(e, -1, phi)
        with open(LITE_KEY_FILE, "w", encoding="utf-8") as fh:
            json.dump({"n": str(n), "e": str(e), "d": str(d)}, fh)
        return n, e, d

    def _sign(self, token):
        payload = self.SHA1_DIGEST_INFO + token
        em = b"\x00\x01" + b"\xff" * (256 - 3 - len(payload)) + b"\x00" + payload
        return pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(256, "big")

    def _public_key(self):
        words = 64  # 2048 bits / 32
        n0inv = (-pow(self.n % 2 ** 32, -1, 2 ** 32)) % 2 ** 32
        rr = pow(2, 4096, self.n)
        blob = struct.pack("<II", words, n0inv)
        blob += self.n.to_bytes(256, "little") + rr.to_bytes(256, "little")
        blob += struct.pack("<i", self.e)
        return base64.b64encode(blob) + b" tv_optimizer@iphone\x00"

    # --- mensajes ---

    def _send(self, cmd, arg0, arg1, data=b""):
        header = struct.pack("<6I", cmd, arg0, arg1, len(data),
                             sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF)
        self.sock.sendall(header + data)

    def _recv_exact(self, size):
        buf = b""
        while len(buf) < size:
            chunk = self.sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("El TV cerró la conexión.")
            buf += chunk
        return buf

    def _recv(self):
        cmd, arg0, arg1, length, _crc, _magic = struct.unpack("<6I", self._recv_exact(24))
        return cmd, arg0, arg1, self._recv_exact(length) if length else b""

    def connect(self, auth_wait=90):
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self._send(self.CNXN, self.VERSION, self.MAX_DATA, b"host::\x00")
        sent_signature = sent_key = False
        while True:
            cmd, arg0, _arg1, data = self._recv()
            if cmd == self.CNXN:
                return data.decode(errors="replace")
            if cmd != self.AUTH or arg0 != self.AUTH_TOKEN:
                continue
            if not sent_signature:
                self._send(self.AUTH, self.AUTH_SIGNATURE, 0, self._sign(data))
                sent_signature = True
            elif not sent_key:
                self._send(self.AUTH, self.AUTH_RSAPUBLICKEY, 0, self._public_key())
                sent_key = True
                print("Mira el TV: acepta '¿Permitir depuración?' marcando 'Permitir siempre'.")
                self.sock.settimeout(auth_wait)
            else:
                raise ConnectionError("El TV rechazó la conexión.")

    def _stream(self, destination, timeout):
        local_id = self.next_id
        self.next_id += 1
        self.sock.settimeout(timeout)
        self._send(self.OPEN, local_id, 0, destination.encode() + b"\x00")
        output, remote_id = [], 0
        try:
            while True:
                cmd, arg0, arg1, data = self._recv()
                if arg1 != local_id:
                    continue
                if cmd == self.OKAY:
                    remote_id = arg0
                elif cmd == self.WRTE:
                    output.append(data)
                    self._send(self.OKAY, local_id, arg0)
                elif cmd == self.CLSE:
                    if remote_id:
                        self._send(self.CLSE, local_id, remote_id)
                    break
        except (socket.timeout, ConnectionError, OSError):
            pass  # reboot corta la conexión; en shell devolvemos lo recibido
        return b"".join(output).decode("utf-8", errors="replace").replace("\r\n", "\n").strip()

    def shell(self, command, timeout=120):
        return self._stream("shell:" + command, timeout)

    def reboot(self):
        self._stream("reboot:", 10)


def lite_connect(host):
    global LITE
    LITE = AdbLite(host)
    try:
        LITE.connect()
    except socket.timeout:
        sys.exit("No se aceptó la conexión en el TV a tiempo. Reintenta y acepta el aviso.")
    except OSError as exc:
        sys.exit(f"No pude conectar con {host}:{ADB_PORT} ({exc}). "
                 "Revisa que la depuración esté activada y que estés en el mismo Wi-Fi.")


def sh(command, timeout=120):
    if ADB is None:
        return LITE.shell(command, timeout)
    return adb("shell", command, timeout=timeout)


def reboot():
    if ADB is None:
        LITE.reboot()
    else:
        adb("reboot")


def quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def ask(question):
    try:
        return input(f"{question} [s/N]: ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except EOFError:
        return False


def human(num_bytes):
    num = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def title(text):
    print(f"\n=== {text} ===")


def require_device():
    if ADB is None:
        if LITE is None:
            try:
                with open(TV_IP_FILE, encoding="utf-8") as fh:
                    host = fh.read().strip()
            except OSError:
                sys.exit("No hay TV conectado. Ejecuta primero: python tv_optimizer.py conectar IP_DEL_TV")
            lite_connect(host)
        return
    lines = [l for l in adb("devices").splitlines()[1:] if l.strip()]
    ready = [l.split()[0] for l in lines if l.split()[-1] == "device"]
    if any(l.split()[-1] == "unauthorized" for l in lines):
        sys.exit("El TV no autorizó la conexión. Acepta el aviso "
                 "'¿Permitir depuración?' en la pantalla del TV y reintenta.")
    if not ready:
        sys.exit("No hay TV conectado. Ejecuta primero: python tv_optimizer.py conectar IP_DEL_TV")
    if len(ready) > 1:
        print(f"Aviso: hay varios dispositivos conectados, se usará {ready[0]}.")
        os.environ["ANDROID_SERIAL"] = ready[0]


# --------------------------------------------------------------------------
# Buscar
# --------------------------------------------------------------------------

def local_networks():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no envía datos, solo elige la interfaz
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    nets = {ipaddress.ip_network(f"{ip}/24", strict=False)
            for ip in ips if not ip.startswith("127.")}
    return sorted(nets, key=str)


def port_open(ip, port, timeout=0.6):
    try:
        with socket.create_connection((str(ip), port), timeout=timeout):
            return True
    except OSError:
        return False


def cmd_buscar(_args):
    nets = local_networks()
    if not nets:
        sys.exit("No pude determinar tu red local. ¿Está el computador conectado al Wi-Fi?")
    found = []
    for net in nets:
        print(f"Buscando dispositivos con ADB (puerto {ADB_PORT}) en {net} ...")
        hosts = list(net.hosts())
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            for ip, ok in zip(hosts, pool.map(lambda h: port_open(h, ADB_PORT), hosts)):
                if ok:
                    found.append(str(ip))
                    print(f"  -> Encontrado: {ip}")
    if not found:
        print(
            "\nNo encontré ningún TV con ADB activo. Revisa en el TV:\n"
            "  1. Ajustes > Preferencias del dispositivo > Información > pulsa 7 veces\n"
            "     'Compilación' para activar las Opciones de desarrollador.\n"
            "  2. Ajustes > Preferencias del dispositivo > Opciones de desarrollador >\n"
            "     activa 'Depuración USB' y, si existe, 'Depuración de red / ADB por red'.\n"
            "  3. La IP del TV aparece en Ajustes > Red e Internet > (tu Wi-Fi).\n"
            "     Puedes conectar directo con: python tv_optimizer.py conectar ESA_IP"
        )
        return
    print("\nPara conectar ejecuta:  python tv_optimizer.py conectar " + found[0])


# --------------------------------------------------------------------------
# Conectar
# --------------------------------------------------------------------------

def cmd_conectar(args):
    if not args:
        sys.exit("Indica la IP del TV, por ejemplo: python tv_optimizer.py conectar 192.168.1.50")
    if ADB is None:
        print(f"Conectando a {args[0]} con el cliente incorporado ...")
        lite_connect(args[0])
        with open(TV_IP_FILE, "w", encoding="utf-8") as fh:
            fh.write(args[0])
        print("Conectado a:", sh("getprop ro.product.manufacturer"), sh("getprop ro.product.model"))
        return
    target = args[0] if ":" in args[0] else f"{args[0]}:{ADB_PORT}"
    print(f"Conectando a {target} ... (si el TV muestra un aviso, elige 'Permitir siempre')")
    print(adb("connect", target, timeout=30))
    os.environ["ANDROID_SERIAL"] = target
    adb("wait-for-device", timeout=60)
    require_device()
    print("Conectado a:", sh("getprop ro.product.manufacturer"), sh("getprop ro.product.model"))


# --------------------------------------------------------------------------
# Analizar
# --------------------------------------------------------------------------

def storage_info():
    out = sh("df /data")
    lines = out.splitlines()
    if len(lines) < 2:
        return None
    parts = lines[-1].split()
    try:
        total, used, free = (int(p) * 1024 for p in parts[1:4])
    except ValueError:
        return None
    return total, used, free


def app_sizes():
    """Devuelve [(paquete, apk, datos, cache)] usando dumpsys diskstats."""
    out = sh("dumpsys diskstats", timeout=180)
    fields = {}
    for key in ("Package Names", "App Sizes", "App Data Sizes", "Cache Sizes"):
        m = re.search(rf"^{key}: (\[.*\])$", out, re.MULTILINE)
        if m:
            try:
                fields[key] = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    if len(fields) < 4:
        return []
    rows = zip(fields["Package Names"], fields["App Sizes"],
               fields["App Data Sizes"], fields["Cache Sizes"])
    return sorted(rows, key=lambda r: r[1] + r[2] + r[3], reverse=True)


def meminfo():
    info = {}
    for line in sh("cat /proc/meminfo").splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            info[m.group(1)] = int(m.group(2)) * 1024
    return info


def cmd_analizar(_args):
    require_device()
    report = []

    def out(line=""):
        print(line)
        report.append(line)

    out(f"Informe del TV - {datetime.datetime.now():%Y-%m-%d %H:%M}")
    out("\n=== Equipo ===")
    for label, prop in (("Marca", "ro.product.brand"), ("Fabricante", "ro.product.manufacturer"),
                        ("Modelo", "ro.product.model"), ("Android", "ro.build.version.release"),
                        ("Parche de seguridad", "ro.build.version.security_patch"),
                        ("Chip", "ro.board.platform")):
        out(f"  {label:20} {sh('getprop ' + prop)}")
    uptime = sh("cat /proc/uptime").split()
    if uptime:
        out(f"  {'Encendido hace':20} {float(uptime[0]) / 3600:.1f} horas")

    out("\n=== Almacenamiento interno ===")
    st = storage_info()
    if st:
        total, used, free = st
        pct = used * 100 / total if total else 0
        out(f"  Total {human(total)} | Usado {human(used)} ({pct:.0f}%) | Libre {human(free)}")
        if pct > 85:
            out("  ! Almacenamiento casi lleno: esto ralentiza mucho Android.")

    out("\n=== Memoria RAM ===")
    mem = meminfo()
    if "MemTotal" in mem:
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        out(f"  Total {human(mem['MemTotal'])} | Disponible {human(avail)}")
        if mem["MemTotal"] <= 1.6 * 1024 ** 3:
            out("  ! El TV tiene poca RAM: conviene tener pocas apps instaladas.")

    out("\n=== Apps que más espacio ocupan ===")
    rows = app_sizes()
    total_cache = sum(r[3] for r in rows)
    third_party = set(p.replace("package:", "") for p in sh("pm list packages -3").splitlines())
    out(f"  {'App':45} {'App':>9} {'Datos':>9} {'Caché':>9}  Tipo")
    for pkg, apk, data, cache in rows[:25]:
        kind = "instalada" if pkg in third_party else "sistema"
        out(f"  {pkg[:45]:45} {human(apk):>9} {human(data):>9} {human(cache):>9}  {kind}")
    if rows:
        out(f"\n  Caché total recuperable: {human(total_cache)}")
    else:
        out("  (Este TV no entrega tamaños por app; usa Ajustes > Apps para verlos.)")

    out(f"\n=== Apps instaladas por el usuario ({len(third_party)}) ===")
    for pkg in sorted(third_party):
        out(f"  {pkg}")

    out("\n=== Archivos grandes (>50 MB) en el almacenamiento compartido ===")
    big = sh("find /sdcard/ -type f -size +50M 2>/dev/null", timeout=180)
    out("  " + ("\n  ".join(big.splitlines()) if big else "(ninguno)"))

    out("\n=== Animaciones ===")
    for key in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        out(f"  {key:30} {sh('settings get global ' + key)}")

    path = os.path.join(HERE, f"informe_tv_{datetime.datetime.now():%Y%m%d_%H%M}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    print(f"\nInforme guardado en: {path}")


# --------------------------------------------------------------------------
# Limpiar
# --------------------------------------------------------------------------

def cmd_limpiar(_args):
    require_device()
    before = storage_info()

    title("Borrando caché de todas las apps")
    # Pide al sistema liberar hasta 1 TB de caché: en la práctica la vacía entera.
    print(sh("pm trim-caches 1000G", timeout=300) or "  Listo.")

    title("Cerrando apps en segundo plano")
    sh("am kill-all")
    print("  Listo.")

    title("Archivos grandes en el almacenamiento compartido")
    big = [l for l in sh("find /sdcard/ -type f -size +50M 2>/dev/null", timeout=180).splitlines() if l]
    if not big:
        print("  No hay archivos de más de 50 MB.")
    for path in big:
        size = sh(f"stat -c %s {quote(path)}")
        label = human(int(size)) if size.isdigit() else "?"
        if ask(f"  ¿Borrar {path} ({label})?"):
            sh(f"rm -f {quote(path)}")
            print("    Borrado.")

    after = storage_info()
    if before and after:
        print(f"\nEspacio libre: {human(before[2])} -> {human(after[2])} "
              f"(liberado {human(max(0, after[2] - before[2]))})")


# --------------------------------------------------------------------------
# Optimizar
# --------------------------------------------------------------------------

def cmd_optimizar(_args):
    require_device()

    title("Acelerando animaciones (0.5x)")
    for key in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        sh(f"settings put global {key} 0.5")
    print("  Los menús se sentirán más rápidos. (Se revierte con 'restaurar').")

    title("Compilando apps para que abran más rápido")
    print("  Esto puede tardar entre 5 y 20 minutos; no apagues el TV...")
    result = sh("cmd package bg-dexopt-job", timeout=1800)
    print("  " + (result or "Listo."))

    title("Recomendaciones")
    print(
        "  - Desactiva apps que no uses:  python tv_optimizer.py desactivar\n"
        "  - Ajustes > Preferencias del dispositivo > Energía: si existe 'Inicio rápido'\n"
        "    o 'Instant Power On', actívalo para que encienda más rápido.\n"
        "  - Reinicia el TV una vez por semana (desenchufar 30 s también sirve).\n"
        "  - Mantén al menos 1-2 GB libres de almacenamiento."
    )
    if ask("\n¿Reiniciar el TV ahora para aplicar todo?"):
        reboot()
        print("Reiniciando...")


# --------------------------------------------------------------------------
# Desactivar / restaurar apps
# --------------------------------------------------------------------------

def record_disabled(pkg):
    with open(DISABLED_LOG, "a", encoding="utf-8") as fh:
        fh.write(pkg + "\n")


def cmd_desactivar(_args):
    require_device()
    installed = set(p.replace("package:", "") for p in sh("pm list packages -e").splitlines())
    third_party = set(p.replace("package:", "") for p in sh("pm list packages -3").splitlines())
    sizes = {r[0]: r[1] + r[2] + r[3] for r in app_sizes()}

    title("Apps del sistema que se pueden desactivar sin riesgo")
    for pkg, desc in SAFE_SYSTEM_CANDIDATES.items():
        if pkg in installed and ask(f"  {desc} ({pkg})  ¿Desactivar?"):
            print("    " + sh(f"pm disable-user --user 0 {pkg}"))
            record_disabled(pkg)

    title("Apps instaladas por el usuario (de mayor a menor tamaño)")
    print("  Desactivar libera RAM y evita que se ejecuten; no borra la app.")
    for pkg in sorted(third_party, key=lambda p: sizes.get(p, 0), reverse=True):
        size = f" - {human(sizes[pkg])}" if pkg in sizes else ""
        if ask(f"  {pkg}{size}  ¿Desactivar?"):
            print("    " + sh(f"pm disable-user --user 0 {pkg}"))
            record_disabled(pkg)

    print(f"\nLas apps desactivadas quedaron anotadas en {DISABLED_LOG}.")
    print("Para desinstalar apps que no usas y liberar espacio, usa Ajustes > Apps en el TV.")


def cmd_restaurar(_args):
    require_device()
    title("Restaurando animaciones a 1x")
    for key in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        sh(f"settings put global {key} 1.0")
    print("  Listo.")

    title("Reactivando apps desactivadas")
    if not os.path.exists(DISABLED_LOG):
        print("  No hay apps desactivadas por este script.")
        return
    with open(DISABLED_LOG, encoding="utf-8") as fh:
        pkgs = sorted({l.strip() for l in fh if l.strip()})
    for pkg in pkgs:
        print(f"  {pkg}: " + sh(f"pm enable {pkg}"))
    os.remove(DISABLED_LOG)


# --------------------------------------------------------------------------

def cmd_todo(args):
    if args:
        cmd_conectar(args)
    cmd_analizar([])
    if ask("\n¿Limpiar caché y archivos ahora?"):
        cmd_limpiar([])
    if ask("\n¿Aplicar optimizaciones de velocidad?"):
        cmd_optimizar([])


COMMANDS = {
    "buscar": cmd_buscar,
    "conectar": cmd_conectar,
    "analizar": cmd_analizar,
    "limpiar": cmd_limpiar,
    "optimizar": cmd_optimizar,
    "desactivar": cmd_desactivar,
    "restaurar": cmd_restaurar,
    "todo": cmd_todo,
}


def main():
    global ADB
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    ADB = find_adb()
    if ADB is None and sys.argv[1] != "buscar":
        print("(No encontré 'adb'; uso el cliente ADB incorporado.)")
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
