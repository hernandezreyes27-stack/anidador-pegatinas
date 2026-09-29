"""Pedido completo: varios modelos con su cantidad -> hojas llenas por modelo + hojas mixtas con los sobrantes."""
import io
import math
import numpy as np
import pikepdf
import pymupdf
from shapely import affinity
from shapely.geometry import box, Point
from shapely.ops import unary_union
from shapely.prepared import prep

import marcas
from nesting import anidar, rot
from pegatina import PT, DisenoError

BORDE_MIN = 6.0


def zona_util(SW, SH, figs):
    zona = box(BORDE_MIN, BORDE_MIN, SW - BORDE_MIN, SH - BORDE_MIN)
    obst = [Point(f[1], f[2]).buffer(f[3] + 4) if f[0] == 'circulo'
            else box(f[1], f[2], f[1] + f[3], f[2] + f[4]).buffer(4) for f in figs]
    return zona.difference(unary_union(obst)) if obst else zona


def calcular(pegatinas, cantidades, SW=1000, SH=700, gap=3.0, tipo_marca='circulos', diametro=5.0):
    fn = marcas.TIPOS[tipo_marca][1]
    _, figs = fn(SW, SH, d=diametro) if tipo_marca == 'circulos' else fn(SW, SH)
    zona = zona_util(SW, SH, figs)
    zprep = prep(zona)

    hojas, restos, info = [], [], []
    for i, (peg, q) in enumerate(zip(pegatinas, cantidades)):
        lay = anidar(peg.P, SW, SH, gap, zona)
        if not lay:
            raise DisenoError(f'«{peg.nombre}» ({peg.ancho:.0f} × {peg.alto:.0f} mm) no cabe en la hoja.')
        n = len(lay)
        llenas, r = divmod(q, n)
        info.append(dict(nombre=peg.nombre, cantidad=q, por_hoja=n, hojas_llenas=llenas, sobrantes=r,
                         ancho=round(peg.ancho, 1), alto=round(peg.alto, 1)))
        if llenas:
            hojas.append(dict(items=[(i,) + p for p in lay], copias=llenas))
        if r:
            sel = sorted(lay, key=lambda t: (round(t[2], 1), t[1]))[:r]
            polys = [affinity.translate(rot(peg.P, a), x, y) for a, x, y in sel]
            top = min(p.bounds[1] for p in polys); bot = max(p.bounds[3] for p in polys)
            restos.append(dict(i=i, sel=sel, polys=polys, top=top, bot=bot))

    # Sobrantes: cada modelo aporta una franja (sus filas sobrantes). Las franjas se colocan en hojas
    # mixtas buscando el primer hueco libre (de arriba abajo, pegadas a izquierda o derecha).
    zx0, zy0, zx1, zy1 = zona.bounds
    mixtas = []

    def colocar(hj, band):
        U = unary_union(band['polys'])
        bx0, by0, bx1, by1 = U.bounds
        ocupado = prep(unary_union(hj['polys']).buffer(gap - 0.01)) if hj['polys'] else None
        for dy in np.arange(zy0 - by0, zy1 - by1 + 0.01, 2.0):
            for dx in (0.0, zx1 - bx1, zx0 - bx0):
                V = affinity.translate(U, dx, dy)
                if zprep.contains(V) and (ocupado is None or not ocupado.intersects(V)):
                    hj['items'] += [(band['i'], a, x + dx, y + dy) for a, x, y in band['sel']]
                    hj['polys'].append(V)
                    return True
        return False

    for band in sorted(restos, key=lambda b: unary_union(b['polys']).area, reverse=True):
        if not any(colocar(hj, band) for hj in mixtas):
            hj = dict(items=[], polys=[])
            if not colocar(hj, band):  # no debería pasar: la franja viene de una hoja válida
                hj['items'] = [(band['i'],) + p for p in band['sel']]; hj['polys'] = band['polys']
            mixtas.append(hj)
    hojas += [dict(items=h['items'], copias=1) for h in mixtas]

    total_hojas = sum(h['copias'] for h in hojas)
    area = sum(p.P.area * q for p, q in zip(pegatinas, cantidades))
    resumen = dict(hojas=total_hojas, pegatinas=sum(cantidades),
                   aprovechamiento=round(area / (total_hojas * SW * SH) * 100, 1) if total_hojas else 0)
    return dict(hojas=hojas, modelos=info, resumen=resumen, figs=figs, SW=SW, SH=SH)


def _matriz(peg, a, px, py, SH_pt):
    T = lambda tx, ty: np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1.]])
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    rb = affinity.rotate(peg.P, a, origin=(0, 0)).bounds[:2]
    M = np.array([[1, 0, 0], [0, -1, peg.H], [0, 0, 1.]])     # PDF fuente -> y hacia abajo
    M = np.diag([PT, PT, 1]) @ M                               # pt -> mm
    M = T(-peg.X0, -peg.Y0) @ M                                # origen en la pegatina
    M = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]]) @ M      # giro
    M = T(-rb[0] + px, -rb[1] + py) @ M                        # posición en la hoja
    return np.array([[1 / PT, 0, 0], [0, -1 / PT, SH_pt], [0, 0, 1.]]) @ M


def construir_pdf(pegatinas, res, expandir_copias=True):
    SW, SH = res['SW'], res['SH']
    SW_pt, SH_pt = SW / PT, SH / PT
    doc = pikepdf.new()
    forms = [doc.copy_foreign(p.pdf.pages[0].as_form_xobject()) for p in pegatinas]
    xobj = pikepdf.Dictionary({f'/S{i}': f for i, f in enumerate(forms)})
    marcas_ops = marcas.a_pdf(res['figs'], SH_pt, PT)
    for hoja in res['hojas']:
        cs = [marcas_ops]
        for i, a, px, py in hoja['items']:
            M = _matriz(pegatinas[i], a, px, py, SH_pt)
            cs.append('q %.5f %.5f %.5f %.5f %.4f %.4f cm /S%d Do Q' % (M[0, 0], M[1, 0], M[0, 1], M[1, 1], M[0, 2], M[1, 2], i))
        contenido = doc.make_stream('\n'.join(cs).encode())
        for _ in range(hoja['copias'] if expandir_copias else 1):
            doc.pages.append(pikepdf.Page(pikepdf.Dictionary(
                Type=pikepdf.Name.Page, MediaBox=[0, 0, SW_pt, SH_pt],
                Resources=pikepdf.Dictionary(XObject=xobj), Contents=contenido)))
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def vistas_previas(pegatinas, res, ancho_px=1400):
    pdf = pymupdf.open('pdf', construir_pdf(pegatinas, res, expandir_copias=False))
    dpi = ancho_px / (res['SW'] / 25.4)
    return [p.get_pixmap(dpi=max(1, int(round(dpi)))).tobytes('png') for p in pdf]
