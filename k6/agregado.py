#!/usr/bin/env python3
"""Agregado por segundo del JSON de k6: solicitudes, fallidas, descartadas y percentiles de http_req_duration."""
import datetime, gzip, json, sys


def pct(ordenados, p):
    return round(ordenados[min(len(ordenados) - 1, int(p * len(ordenados)))], 3)


def por_segundo(ruta):
    seg = {}
    with gzip.open(ruta, "rt") as fh:
        for linea in fh:
            if '"http_req_duration"' in linea:
                k = "d"
            elif '"http_req_failed"' in linea:
                k = "f"
            elif '"dropped_iterations"' in linea:
                k = "x"
            else:
                continue
            p = json.loads(linea)
            if p.get("type") != "Point":
                continue
            t = int(datetime.datetime.fromisoformat(p["data"]["time"]).timestamp())
            s = seg.setdefault(t, {"d": [], "n": 0, "f": 0, "x": 0})
            v = p["data"]["value"]
            if k == "d":
                s["d"].append(v)
            elif k == "f":
                s["n"] += 1
                s["f"] += 1 if v else 0
            else:
                s["x"] += int(v)
    filas = []
    for t in sorted(seg):
        s, d = seg[t], sorted(seg[t]["d"])
        filas.append({"t": t, "solicitudes": s["n"], "fallidas": s["f"], "descartadas": s["x"],
                      "p50_ms": pct(d, 0.5) if d else None, "p95_ms": pct(d, 0.95) if d else None,
                      "p99_ms": pct(d, 0.99) if d else None, "max_ms": round(d[-1], 3) if d else None})
    return filas


def autotest():
    import os, tempfile
    ruta = os.path.join(tempfile.mkdtemp(), "x.json.gz")
    with gzip.open(ruta, "wt") as fh:
        for i, (m, v) in enumerate([("http_req_duration", 2.0), ("http_req_failed", 0), ("http_req_duration", 4.0),
                                    ("http_req_failed", 1), ("dropped_iterations", 3)]):
            fh.write(json.dumps({"metric": m, "type": "Point", "data": {"time": "2026-10-20T19:57:29.187498111-03:00", "value": v}}) + "\n")
    f = por_segundo(ruta)
    assert len(f) == 1 and f[0]["solicitudes"] == 2 and f[0]["fallidas"] == 1 and f[0]["descartadas"] == 3
    assert f[0]["p50_ms"] == 4.0 and f[0]["max_ms"] == 4.0
    print("autotest ok")


if __name__ == "__main__":
    autotest() if "--autotest" in sys.argv else json.dump(por_segundo(sys.argv[1]), sys.stdout)
