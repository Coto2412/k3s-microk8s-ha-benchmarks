"""T-21.4: potencia por simulación de la comparación K3s vs MicroK8s en potencia media (W).

Modelo (supuestos, no medidos): y = mu + delta*[MicroK8s] + u_segmento + e. Cada (bloque, distribución) es un
segmento con su propio nivel u ~ N(0, sigma_u) y r repeticiones con ruido e ~ N(0, sigma_w).
sigma_w sale de los pilotos (analysis/varianzas_piloto.py); sigma_u, delta y el diseño son supuestos.
Dos análisis: ingenuo (todas las repeticiones como independientes) y por segmento (media de cada segmento).
"""
import math, random, statistics as st

SIGMA_W = 0.018


def _betacf(a, b, x):
    qab, qap, qam, c, d = a + b, a + 1, a - 1, 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / d if abs(d) > 1e-30 else 1e30
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / d if abs(d) > 1e-30 else 1e30
            c = 1 + aa / c
            c = c if abs(c) > 1e-30 else 1e-30
            h *= d * c
    return h


def _ibeta(a, b, x):
    if x <= 0 or x >= 1:
        return min(max(x, 0.0), 1.0)
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def welch_p(x, y):
    vx, vy, nx, ny = st.variance(x) / len(x), st.variance(y) / len(y), len(x), len(y)
    if vx + vy == 0:
        return 0.0
    t = (st.mean(x) - st.mean(y)) / math.sqrt(vx + vy)
    df = (vx + vy) ** 2 / (vx ** 2 / (nx - 1) + vy ** 2 / (ny - 1))
    return _ibeta(df / 2, 0.5, df / (df + t * t))


def simular(b, r, sigma_u, delta, n=2000, rng=random.Random(1)):
    ing = seg = 0
    for _ in range(n):
        g = {0: [], 1: []}
        medias = {0: [], 1: []}
        for d in (0, 1):
            for _ in range(b):
                u = rng.gauss(0, sigma_u)
                ys = [delta * d + u + rng.gauss(0, SIGMA_W) for _ in range(r)]
                g[d] += ys
                medias[d].append(st.mean(ys))
        ing += welch_p(g[0], g[1]) < 0.05
        seg += welch_p(medias[0], medias[1]) < 0.05
    return ing / n, seg / n


if __name__ == "__main__":
    # p bilateral exacta: df=1 (Cauchy) y df=2 tienen forma cerrada
    assert abs(2 * _ibeta(0.5, 0.5, 0.5) / 2 - 0.5) < 1e-9
    assert abs(_ibeta(1.0, 0.5, 2 / (2 + 1)) - (1 - 1 / math.sqrt(3))) < 1e-9
    print(f"sigma_w = {SIGMA_W} W (medido); sigma_u, delta y diseño: supuestos. Fracción de rechazos con p < 0,05 (Welch, 2000 simulaciones)")
    print("bloques por distribución b, repeticiones por bloque r | sigma_u | delta | ingenuo | por segmento")
    for b, r in ((2, 5), (5, 2), (6, 2), (10, 1)):
        for su in (0.0, 0.1, 0.3, 0.6):
            for dl in (0.0, 0.1, 0.25, 0.5):
                i, s = simular(b, r, su, dl)
                print(f"  b={b:2} r={r} | su={su:.1f} | delta={dl:.2f} | {i:5.3f} | {s:5.3f}")
