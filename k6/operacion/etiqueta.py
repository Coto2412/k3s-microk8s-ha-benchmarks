"""Cambia la etiqueta `distribution` de todos los objetivos de Prometheus sin playbook ni reinicio (E1, Etapa 4).

  python3 -m k6.operacion.etiqueta --distribucion <k3s|microk8s> [--diario ruta.jsonl]
Reescribe de forma atómica los archivos de file_sd_configs y espera a que /api/v1/targets y `up` muestren la etiqueta nueva.
"""
import argparse, glob, json, os, sys, time
import urllib.request

from k6.lib.comun import OBJETIVOS_ESPERADOS, prom

DIR_OBJETIVOS = "/etc/prometheus/objetivos"


def escribir(directorio, distribucion):
    archivos = sorted(glob.glob(os.path.join(directorio, "*.json")))
    if not archivos:
        raise RuntimeError(f"no hay archivos de objetivos en {directorio} (aplicar el playbook del host)")
    for ruta in archivos:
        grupos = json.load(open(ruta))
        for g in grupos:
            g.setdefault("labels", {})["distribution"] = distribucion
        tmp = ruta + ".tmp"  # fuera del patrón *.json: Prometheus no lo lee a medias
        with open(tmp, "w") as fh:
            json.dump(grupos, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, ruta)
    return [os.path.basename(r) for r in archivos]


def objetivos(url):
    d = json.load(urllib.request.urlopen(f"{url}/api/v1/targets?state=active", timeout=10))
    return d["data"]["activeTargets"]


def esperar(url, distribucion, limite_s, t0):
    """Espera la etiqueta nueva en todos los objetivos activos y luego una muestra de `up` posterior a t0 en cada uno."""
    fin = time.time() + limite_s
    t_api = None
    while time.time() < fin:
        try:
            ts = objetivos(url)
            if t_api is None and len(ts) == OBJETIVOS_ESPERADOS and all(t["labels"].get("distribution") == distribucion for t in ts):
                t_api = time.time()
            if t_api and len(prom(url, f'timestamp(up{{distribution="{distribucion}"}}) > {t0}')) == OBJETIVOS_ESPERADOS:
                return t_api, time.time()
        except OSError:
            pass  # Prometheus puede no responder un instante; se reintenta hasta el límite
        time.sleep(1)
    return t_api, None


def cambiar(distribucion, prometheus="http://127.0.0.1:9090", directorio=DIR_OBJETIVOS, limite_s=90):
    t0 = time.time()
    archivos = escribir(directorio, distribucion)
    t_api, t_up = esperar(prometheus, distribucion, limite_s, t0)
    return {"paso": "etiqueta", "distribucion": distribucion, "t_escritura": t0, "t_api": t_api, "t_up": t_up,
            "duracion_s": round((t_up or time.time()) - t0, 3), "archivos": archivos,
            "resultado": "ok" if t_up else "tiempo_agotado"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    ap.add_argument("--directorio", default=DIR_OBJETIVOS)
    ap.add_argument("--limite", type=int, default=90, help="s máximos de espera (scrape de 10 s y relectura de archivos)")
    ap.add_argument("--diario", help="archivo .jsonl donde agregar el registro del cambio")
    a = ap.parse_args()
    r = cambiar(a.distribucion, a.prometheus, a.directorio, a.limite)
    linea = json.dumps(r, ensure_ascii=False)
    print(linea)
    if a.diario:
        with open(a.diario, "a") as fh:
            fh.write(linea + "\n")
    sys.exit(0 if r["resultado"] == "ok" else 1)


if __name__ == "__main__":
    main()
