"""Anidador de pegatinas · servidor web.  Arrancar:  python -m uvicorn app:app --host 0.0.0.0 --port 8000"""
import base64
import json
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

import marcas
from pegatina import DisenoError, Pegatina
from trabajo import calcular, construir_pdf, vistas_previas

app = FastAPI(title='Anidador de pegatinas')
# La tienda (tecnovinyl.com, GitHub Pages) llama a este servidor desde el navegador: hay que permitir su origen.
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['GET', 'POST'], allow_headers=['*'], expose_headers=['Content-Disposition'])
BASE = Path(__file__).parent
TRABAJOS: 'OrderedDict[str, tuple[bytes, str]]' = OrderedDict()   # últimos PDFs generados, en memoria


@app.get('/')
def inicio():
    return FileResponse(BASE / 'index.html')


@app.get('/api/marcas')
def tipos_marcas():
    return [{'id': k, 'nombre': v[0]} for k, v in marcas.TIPOS.items()]


@app.post('/api/anidar')
def anidar(disenos: list[UploadFile] = File(...),
           cantidades: str = Form(...),
           ancho: float = Form(1000), alto: float = Form(700),
           separacion: float = Form(3), marca: str = Form('circulos'),
           diametro: float = Form(5), color_corte: str = Form('#0BF786')):
    try:
        cant = [int(c) for c in json.loads(cantidades)]
    except (ValueError, TypeError):
        raise HTTPException(422, 'Las cantidades no son válidas.')
    if len(cant) != len(disenos):
        raise HTTPException(422, 'Falta la cantidad de algún diseño.')
    if any(c < 1 or c > 100000 for c in cant):
        raise HTTPException(422, 'Cada cantidad tiene que estar entre 1 y 100.000.')
    if not (100 <= ancho <= 5000 and 100 <= alto <= 5000):
        raise HTTPException(422, 'La hoja tiene que medir entre 100 y 5000 mm por lado.')
    if not 0 <= separacion <= 50:
        raise HTTPException(422, 'La separación tiene que estar entre 0 y 50 mm.')
    if marca not in marcas.TIPOS:
        raise HTTPException(422, 'Tipo de marca desconocido.')
    if not 1 <= diametro <= 30:
        raise HTTPException(422, 'El diámetro de las marcas tiene que estar entre 1 y 30 mm.')

    pegatinas = []
    for d in disenos:
        nombre = Path(d.filename or 'diseño').stem
        if not (d.filename or '').lower().endswith('.svg'):
            raise HTTPException(422, f'«{nombre}» no es un SVG. Exporta el diseño como SVG con el trazado de corte.')
        try:
            pegatinas.append(Pegatina(nombre, d.file.read(), color_corte))
        except DisenoError as e:
            raise HTTPException(422, f'«{nombre}»: {e}')
        except Exception:
            raise HTTPException(422, f'«{nombre}» no se ha podido leer. Comprueba que es un SVG válido.')

    try:
        res = calcular(pegatinas, cant, ancho, alto, separacion, marca, diametro)
    except DisenoError as e:
        raise HTTPException(422, str(e))

    pdf = construir_pdf(pegatinas, res)
    previas = vistas_previas(pegatinas, res)
    tid = uuid.uuid4().hex[:12]
    TRABAJOS[tid] = (pdf, time.strftime('anidado_%Y%m%d_%H%M.pdf'))
    while len(TRABAJOS) > 30:
        TRABAJOS.popitem(last=False)

    hojas = []
    for h, png in zip(res['hojas'], previas):
        cuenta = {}
        for i, *_ in h['items']:
            cuenta[i] = cuenta.get(i, 0) + 1
        hojas.append({'copias': h['copias'],
                      'piezas': [{'modelo': pegatinas[i].nombre, 'n': n} for i, n in cuenta.items()],
                      'png': base64.b64encode(png).decode()})
    return {'id': tid, 'resumen': res['resumen'], 'modelos': res['modelos'], 'hojas': hojas}


@app.get('/api/pdf/{tid}')
def descargar(tid: str):
    if tid not in TRABAJOS:
        raise HTTPException(404, 'Este PDF ya no está disponible. Vuelve a anidar el pedido.')
    pdf, nombre = TRABAJOS[tid]
    return Response(pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{nombre}"'})
