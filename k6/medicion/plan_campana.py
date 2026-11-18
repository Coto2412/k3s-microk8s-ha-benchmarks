"""Plan de la campaña definitiva (T-24.4): 8 bloques con las dos distribuciones en orden sorteado (semilla registrada, 4/4).

Dentro de cada tramo: por repetición, idle -> media -> alta, y al final una corrida con fallo. Escribe data/campana/plan_campana_v1.json.
  python3 -m k6.medicion.plan_campana                                  # borrador (estado sin fijar)
  python3 -m k6.medicion.plan_campana --fijar --commit <sha>           # estado fijado, con la fecha y el commit del código y el pipeline
El pre-registro es docs/preregistro/plan-campana-v1.md; después de la etiqueta plan-campana-v1 este archivo no se modifica.
"""
import argparse, datetime, json, os, random

from k6.lib.comun import RAIZ

BLOQUES = 8


def generar(semilla, reps, media=450, alta=900, commit=None):
    k3s_primero = set(random.Random(semilla).sample(range(1, BLOQUES + 1), BLOQUES // 2))
    bloques = []
    for b in range(1, BLOQUES + 1):
        orden = ["k3s", "microk8s"] if b in k3s_primero else ["microk8s", "k3s"]
        tramos = [{"sesion": f"b{b:02d}_{d}", "distribucion": d, "corridas": [
            {"escenario": e, "repeticion": r, "tasa_rps": {"idle": None, "media": media, "alta": alta}[e]}
            for r in range(1, reps + 1) for e in ("idle", "media", "alta")]} for d in orden]
        bloques.append({"bloque": b, "orden": orden, "tramos": tramos})
    p = {
        "version": "v1", "estado": "borrador sin fijar: aún no existe la etiqueta plan-campana-v1", "semilla": semilla,
        "diseno": "8 bloques; 4 empiezan por K3s y 4 por MicroK8s (sorteo con la semilla); la unidad de análisis es el promedio de cada celda "
                  "(bloque x distribución x escenario)",
        "repeticiones_por_celda": reps, "repeticiones_por_celda_provisional": False,
        "fases_s": {"rampa": 30, "estable": 180, "descenso": 30, "estabilizacion": 120},
        "ventana_referencia_s": {"espera": 120, "medicion": 180, "momento": "al inicio de cada tramo, antes de construir, sin VMs ni k6"},
        "construccion": "el clúster se construye desde cero en cada tramo y se destruye al final; ciclo del registro = 100 + bloque",
        "corrida_fallo": {"escenario": "media", "tasa_rps": media, "fallo_en_s": 30, "retener_s": 120,
                          "momento": "al final de cada tramo, después del almacenamiento y antes de destruir"},
        "jornadas": {"1": [1, 2, 3], "2": [4, 5, 6], "3": [7, 8], "reserva": "bloques abortados (sesiones bNNr_<dist>) y luego T-24.5"},
        "validez": "una corrida entra al análisis solo si el orquestador la marca valida_para_campana y no fue abortada por memoria",
        "reglas_exclusion": [
            "no válida solo por falla del procedimiento: precondición no cumplida, lectura de RAPL fallida, aborto por reloj, fase estable "
            "incompleta o valida_para_campana falso; se repite una vez al final del tramo, antes de la corrida con fallo; si sigue no válida, "
            "la celda queda con una corrida",
            "la latencia, las solicitudes fallidas, las iteraciones descartadas y MemAvailable bajo 1024 MB son resultados y no excluyen",
            "construcción fallida: un reintento (destruir y construir); si vuelve a fallar, el bloque completo pasa a la reserva con el mismo orden",
            "MemAvailable bajo 512 MB: aborta el tramo, se destruye el clúster y se registra como resultado de la distribución; no se repite",
        ],
        "bloques": bloques,
    }
    if commit:
        p["estado"] = "fijado"
        p["fijacion"] = {"fecha": datetime.date.today().isoformat(), "commit": commit, "etiqueta": "plan-campana-v1",
                         "preregistro": "docs/preregistro/plan-campana-v1.md"}
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", type=int, default=20261028)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--salida", default=os.path.join(RAIZ, "data", "campana", "plan_campana_v1.json"))
    ap.add_argument("--fijar", action="store_true", help="estado fijado; exige --commit")
    ap.add_argument("--commit", help="commit del código de medición y del pipeline que cita el pre-registro")
    a = ap.parse_args()
    if a.fijar and not a.commit:
        ap.error("--fijar exige --commit")
    p = generar(a.semilla, a.repeticiones, commit=a.commit if a.fijar else None)
    assert sum(b["orden"][0] == "k3s" for b in p["bloques"]) == BLOQUES // 2
    if os.path.exists(a.salida):  # nunca se vuelve a sortear: el orden debe ser el del borrador
        previo = json.load(open(a.salida))
        assert previo["semilla"] == p["semilla"] and previo["bloques"] == p["bloques"], "el orden o las corridas cambiaron respecto del archivo existente"
    json.dump(p, open(a.salida, "w"), indent=1, ensure_ascii=False)
    print(" ".join(f"b{b['bloque']}:{b['orden'][0][:2]}" for b in p["bloques"]),
          f"| corridas totales {sum(len(t['corridas']) for b in p['bloques'] for t in b['tramos'])}")


if __name__ == "__main__":
    main()
