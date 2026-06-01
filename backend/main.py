from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text, extract_pages
from pdfminer.layout import LTTextBox, LTTextLine
from collections import defaultdict
import re, io, os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="MUBEC — Calculadora de Horas Extras")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.endswith(".html") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def parse_min(s: str) -> int:
    m = re.match(r"(\d{1,3}):(\d{2})", s.strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def extract_all(pdf_bytes: bytes) -> dict:
    result = {
        "nome": "",
        "he_uteis": 0.0,
        "he_sabado": 0.0,
        "he_feriado": 0.0,
        "he_acima8h": 0.0,
        "horas_desconto": 0.0,
    }

    items = []
    for page_layout in extract_pages(io.BytesIO(pdf_bytes)):
        for element in page_layout:
            if isinstance(element, LTTextBox):
                for line in element:
                    if isinstance(line, LTTextLine):
                        txt = line.get_text().strip()
                        if txt:
                            items.append({
                                "text": txt,
                                "x": round(line.x0),
                                "y": round(line.y0, 1),
                            })

    linhas = defaultdict(list)
    for item in items:
        linhas[item["y"]].append(item)

    he_uteis = he_sabado = he_feriado = total_af = total_debito = 0

    for y in sorted(linhas.keys(), reverse=True):
        linha = sorted(linhas[y], key=lambda i: i["x"])
        textos = [i["text"] for i in linha]

        # Extrair nome
        if not result["nome"]:
            for t in textos:
                nm = re.match(r"Nome:\s+(.+)", t)
                if nm:
                    result["nome"] = nm.group(1).strip()
                    break

        # Detectar data e tipo
        data_match = next((t for t in textos if re.match(r"\d{2} \w+\.,", t)), None)
        if not data_match:
            continue

        tipo_sep = next((t for t in textos if t in ("TRAB", "DUNT", "FERIADO", "FOLG")), None)
        tipo_emb = None
        if not tipo_sep:
            for kw in ("TRAB", "DUNT", "FERIADO", "FOLG"):
                if kw in data_match:
                    tipo_emb = kw
                    break
        tipo = tipo_sep or tipo_emb
        if not tipo or tipo == "FOLG":
            continue

        def val_at(x_min, x_max, _linha=linha):
            for i in sorted(_linha, key=lambda i: i["x"]):
                if x_min <= i["x"] <= x_max:
                    return i["text"]
            return ""

        hp  = val_at(435, 492)   # Horas Positivas
        af  = val_at(493, 535)   # Atrasos e Faltas
        deb = val_at(570, 640)   # Debito (negativo)

        # HE por tipo de dia
        if hp and re.match(r"\d{1,2}:\d{2}", hp):
            mins = parse_min(hp)
            if tipo == "TRAB":
                he_uteis += mins
            elif tipo == "DUNT":
                he_sabado += mins
            elif tipo == "FERIADO":
                he_feriado += mins

        # Descontar AF apenas se coluna Eventos (x > 600) estiver VAZIA
        # Se houver qualquer texto em Eventos (Atestado, Feriado, etc.) nao descontar
        _linha_local = linha[:]
        coluna_eventos_vazia = not any(i["x"] > 600 and i["text"] for i in _linha_local)
        if af and re.match(r"\d{1,2}:\d{2}", af) and coluna_eventos_vazia:
            total_af += parse_min(af)

        # Debitos negativos: descontar sempre
        if deb and re.match(r"-\d{1,2}:\d{2}", deb):
            total_debito += parse_min(deb[1:])

    result["he_uteis"]       = round(he_uteis / 60, 4)
    result["he_sabado"]      = round(he_sabado / 60, 4)
    result["he_feriado"]     = round(he_feriado / 60, 4)
    result["horas_desconto"] = round((total_af + total_debito) / 60, 4)

    # Fallback para nome
    if not result["nome"]:
        text = extract_text(io.BytesIO(pdf_bytes))
        nm = re.search(
            r"Nome:\s+([A-Z][A-Z\s]+?)(?:\n|Matricula|PIS|CPF)",
            text, re.IGNORECASE
        )
        if nm:
            result["nome"] = nm.group(1).strip()

    return result


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF")
    try:
        contents = await file.read()
        data = extract_all(contents)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao processar PDF: {str(e)}")

    if not data["nome"]:
        data["nome"] = file.filename.replace(".pdf", "").replace("_", " ")

    return {
        "nome":           data["nome"],
        "he_uteis":       data["he_uteis"],
        "he_sabado":      data["he_sabado"],
        "he_feriado":     data["he_feriado"],
        "he_acima8h":     data["he_acima8h"],
        "horas_desconto": data["horas_desconto"],
    }


@app.get("/api/health")
def health():
    return JSONResponse(
        content={"status": "ok", "api_key_configured": True, "version": "4.1"},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
