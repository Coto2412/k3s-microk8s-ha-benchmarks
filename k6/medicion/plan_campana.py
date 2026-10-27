"""Plan de la campaña definitiva (T-24.4): 8 bloques con las dos distribuciones en orden sorteado (semilla registrada, 4/4).

Dentro de cada tramo: por repetición, idle -> media -> alta. Las tasas, las fases y las repeticiones por celda son parámetros;
las repeticiones por celda (2, o 1 si el tiempo aprieta) son una propuesta a fijar en el pre-registro. Escribe data/campana/plan_campana_v1.json.
"""
import argparse, json, os, random

from k6.lib.comun import RAIZ

BLOQUES = 8


def generar(semilla, reps, media=450, alta=900):
    k3s_primero = set(random.Random(semilla).sample(range(1, BLOQUES + 1), BLOQUES // 2))
    bloques = []
    for b in range(1, BLOQUES + 1):
        orden = ["k3s", "microk8s"] if b in k3s_primero else ["microk8s", "k3s"]
        tramos = [{"sesion": f"b{b:02d}_{d}", "distribucion": d, "corridas": [
            {"escenario": e, "repeticion": r, "tasa_rps": {"idle": None, "media": media, "alta": alta}[e]}
            for r in range(1, reps + 1) for e in ("idle", "media", "alta")]} for d in orden]
        bloques.append({"bloque": b, "orden": orden, "tramos": tramos})
    return {
        "version": "v1", "estado": "borrador sin fijar: aún no existe la etiqueta plan-campana-v1", "semilla": semilla,
        "diseno": "8 bloques; 4 empiezan por K3s y 4 por MicroK8s (sorteo con la semilla); la unidad de análisis es el promedio de cada celda "
                  "(bloque x distribución x escenario)",
        "repeticiones_por_celda": reps, "repeticiones_por_celda_provisional": True,
        "fases_s": {"rampa": 30, "estable": 180, "descenso": 30, "estabilizacion": 120},
        "validez": "una corrida entra al análisis solo si el orquestador la marca valida_para_campana; el resto de las reglas de exclusión "
                   "se fijan antes del primer bloque",
        "bloques": bloques,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", type=int, default=20261028)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--salida", default=os.path.join(RAIZ, "data", "campana", "plan_campana_v1.json"))
    a = ap.parse_args()
    p = generar(a.semilla, a.repeticiones)
    assert sum(b["orden"][0] == "k3s" for b in p["bloques"]) == BLOQUES // 2
    json.dump(p, open(a.salida, "w"), indent=1, ensure_ascii=False)
    print(" ".join(f"b{b['bloque']}:{b['orden'][0][:2]}" for b in p["bloques"]),
          f"| corridas totales {sum(len(t['corridas']) for b in p['bloques'] for t in b['tramos'])}")


if __name__ == "__main__":
    main()
