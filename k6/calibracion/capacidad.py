"""Capacidad máxima (T-24.5): 3 pasadas por distribución de la calibración, solo en los escalones cercanos al límite
(800 a 1300 rps, de 100 en 100), con los criterios de escalón sostenido de la Etapa 3 (`calibrar.veredicto`).
Las 3 pasadas usan el mismo clúster ya construido; se declara así. Se ejecuta desde la consola de texto, con el modo medición.

  python3 -m k6.calibracion.capacidad --distribucion k3s
  python3 -m k6.calibracion.capacidad --resumir data/calibracion/<sesión>/calib_k3s_*.json   # sin medir
"""
import argparse, json, os, subprocess, sys, time

from k6.lib.comun import RAIZ

TASAS = list(range(800, 1301, 100))
PASADAS = 3


def capacidad(pasos):
    """Último escalón sostenido antes del primer fallo (None si falla el primero) y el mayor sostenido en toda la pasada."""
    antes = None
    for p in sorted(pasos, key=lambda p: p["tasa_pedida"]):
        if p["motivos_falla"]:
            break
        antes = p["tasa_pedida"]
    sost = [p["tasa_pedida"] for p in pasos if not p["motivos_falla"]]
    return antes, max(sost) if sost else None


def resumir(rutas):
    pasadas = []
    for r in rutas:
        m = json.load(open(r))
        antes, mayor = capacidad(m["pasos"])
        motivos = sorted({x.split(":")[0] for p in m["pasos"] for x in p["motivos_falla"]})
        pasadas.append({"archivo": os.path.relpath(r, RAIZ), "capacidad_rps": antes, "mayor_sostenido_rps": mayor,
                        "motivos_de_falla": motivos, "limite_por_generador": m.get("limite_por_generador")})
    cs = sorted(p["capacidad_rps"] for p in pasadas if p["capacidad_rps"] is not None)
    return {"pasadas": pasadas, "capacidad_mediana_rps": cs[len(cs) // 2] if cs else None,
            "rango_rps": [cs[0], cs[-1]] if cs else None, "mismo_cluster": True}


def autotest():
    ok, mal = [], ["contenedor estrangulado"]
    pasos = [{"tasa_pedida": 800, "motivos_falla": ok}, {"tasa_pedida": 900, "motivos_falla": ok}, {"tasa_pedida": 1000, "motivos_falla": mal},
             {"tasa_pedida": 1100, "motivos_falla": ok}]
    assert capacidad(pasos) == (900, 1100)
    assert capacidad([{"tasa_pedida": 800, "motivos_falla": mal}]) == (None, None)
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distribucion", choices=["k3s", "microk8s"])
    ap.add_argument("--pasadas", type=int, default=PASADAS)
    ap.add_argument("--resumir", nargs="+", help="JSON de calibración ya medidos")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    if a.resumir:
        return print(json.dumps(resumir(a.resumir), indent=2, ensure_ascii=False))
    if not a.distribucion:
        ap.error("--distribucion o --resumir")
    rutas = []
    for i in range(1, a.pasadas + 1):
        print(f"pasada {i}/{a.pasadas}", flush=True)
        p = subprocess.run([sys.executable, "-m", "k6.calibracion.calibrar", "--distribucion", a.distribucion,
                            "--tasas", ",".join(map(str, TASAS)), "--seguir",
                            "--nota", f"capacidad máxima T-24.5, pasada {i}/{a.pasadas}, mismo clúster"],
                           cwd=RAIZ, stdout=subprocess.PIPE, text=True)
        sys.stdout.write(p.stdout)
        if p.returncode:
            sys.exit(f"la pasada {i} terminó con código {p.returncode}")
        rutas.append(os.path.join(RAIZ, json.loads(p.stdout.strip().splitlines()[-1])["archivo"]))
    r = resumir(rutas) | {"distribucion": a.distribucion, "tasas": TASAS}
    salida = os.path.join(os.path.dirname(rutas[-1]), f"capacidad_{a.distribucion}_{time.strftime('%Y%m%dT%H%M%S')}.json")
    json.dump(r, open(salida, "w"), indent=2, ensure_ascii=False)
    print(json.dumps({"archivo": os.path.relpath(salida, RAIZ), "capacidad_mediana_rps": r["capacidad_mediana_rps"], "rango_rps": r["rango_rps"]}))


if __name__ == "__main__":
    sys.exit(main() or 0)
