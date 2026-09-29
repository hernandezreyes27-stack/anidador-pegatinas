"""Generadores de marcas de registro. Coordenadas en mm, origen arriba-izquierda (y hacia abajo).
Cada tipo devuelve (margen_reservado_mm, lista_de_figuras). Figura: ('circulo', cx, cy, r) | ('rect', x, y, w, h)"""
import math

def _repartir(a, b, max_paso):
    n = max(1, math.ceil((b - a) / max_paso))
    return [a + (b - a) * i / n for i in range(n + 1)]

def circulos(SW, SH, d=5.0, borde=5.0, paso=250.0, holgura=4.0):
    """Puntos negros para mesas con cámara CCD (IECHO, Zünd...). Esquinas + intermedios en cada lado."""
    r = d / 2; c = borde + r
    pts = set()
    for x in _repartir(c, SW - c, paso):
        pts.add((round(x, 3), c)); pts.add((round(x, 3), SH - c))
    for y in _repartir(c, SH - c, paso):
        pts.add((c, round(y, 3))); pts.add((SW - c, round(y, 3)))
    return borde + d + holgura, [('circulo', x, y, r) for x, y in sorted(pts)]

def opos(SW, SH, lado=3.0, borde=5.0, paso=200.0, holgura=4.0):
    """Estilo Summa OPOS: cuadrados negros a lo largo de los dos lados largos + barra en el borde de entrada."""
    figs = []
    for x in _repartir(borde, SW - borde - lado, paso):
        figs.append(('rect', x, borde, lado, lado))
        figs.append(('rect', x, SH - borde - lado, lado, lado))
    figs.append(('rect', borde + lado + 5, borde + 0.5, SW - 2 * (borde + lado + 5), 2.0))  # barra
    return borde + lado + holgura, figs

def esquinas(SW, SH, brazo=10.0, grosor=0.5, borde=5.0, holgura=4.0):
    """Marcas en L en las 4 esquinas (tipo Graphtec / Mimaki)."""
    figs = []
    for (x, y, sx, sy) in [(borde, borde, 1, 1), (SW - borde, borde, -1, 1),
                           (borde, SH - borde, 1, -1), (SW - borde, SH - borde, -1, -1)]:
        figs.append(('rect', min(x, x + sx * brazo), min(y, y + sy * grosor), brazo, grosor))
        figs.append(('rect', min(x, x + sx * grosor), min(y, y + sy * brazo), grosor, brazo))
    return borde + brazo + holgura, figs

def ninguna(SW, SH):
    return 10.0, []

TIPOS = {
    'circulos': ('Círculos · IECHO / mesas con cámara', circulos),
    'opos':     ('Cuadrados · estilo Summa OPOS', opos),
    'esquinas': ('Esquinas en L · Graphtec / Mimaki', esquinas),
    'ninguna':  ('Sin marcas', ninguna),
}

def a_pdf(figs, SH_pt, PT):
    """Contenido PDF en negro 100% K."""
    k = 0.5523
    ops = ['q 0 0 0 1 k']
    for f in figs:
        if f[0] == 'circulo':
            _, cx, cy, r = f
            X, Y, R = cx / PT, SH_pt - cy / PT, r / PT
            ops.append(f'{X+R:.3f} {Y:.3f} m '
                       f'{X+R:.3f} {Y+k*R:.3f} {X+k*R:.3f} {Y+R:.3f} {X:.3f} {Y+R:.3f} c '
                       f'{X-k*R:.3f} {Y+R:.3f} {X-R:.3f} {Y+k*R:.3f} {X-R:.3f} {Y:.3f} c '
                       f'{X-R:.3f} {Y-k*R:.3f} {X-k*R:.3f} {Y-R:.3f} {X:.3f} {Y-R:.3f} c '
                       f'{X+k*R:.3f} {Y-R:.3f} {X+R:.3f} {Y-k*R:.3f} {X+R:.3f} {Y:.3f} c f')
        else:
            _, x, y, w, h = f
            ops.append(f'{x/PT:.3f} {SH_pt-(y+h)/PT:.3f} {w/PT:.3f} {h/PT:.3f} re f')
    ops.append('Q')
    return '\n'.join(ops)
