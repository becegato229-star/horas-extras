from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pdfminer.high_level import extract_text
from collections import Counter
import re
import io
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="MUBEC — Calculadora de Horas Extras")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import Response

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


def parse_hhmm(s: str) -> float:
    mins = parse_min(s)
    return round(mins / 60, 4)


def extract_data(text: str) -> dict:
    result = {
        "nome": "",
        "he_uteis": 0.0,
        "he_sabado": 0.0,
        "he_feriado": 0.0,
        "he_acima8h": 0.0,
        "horas_desconto": 0.0,
    }

    # ── Nome ──────────────────────────────────────────────────────
    nome_match = re.search(
        r"Nome:\s+([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ\s]+?)(?:\n|Matrícula|PIS|CPF)",
        text, re.IGNORECASE
    )
    if nome_match:
        result["nome"] = nome_match.group(1).strip()

    # ── HE Sábado: campo "H.E. Dia Útil" do resumo Flash ─────────
    # No sistema Flash/MUBEC, sábados DUNT são classificados como "Dia Útil"
    he_util_flash = re.search(
        r"H\.E\.?\s*Dia\s*[ÚU]til[^\n]{0,80}?(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    if he_util_flash:
        result["he_sabado"] = parse_hhmm(he_util_flash.group(1))

    # ── HE Feriado: campo "H.E. Feriado" do resumo ───────────────
    he_feriado_match = re.search(
        r"H\.E\.?\s*Feriado[^\n]{0,60}?(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    feriado_str = None
    if he_feriado_match:
        feriado_str = he_feriado_match.group(1)
        result["he_feriado"] = parse_hhmm(feriado_str)

    # ── HE Dias Úteis: horas positivas de TRAB que aparecem 2x ───
    # O pdfminer extrai a coluna "Horas Positivas" e "Crédito" separadamente,
    # fazendo com que cada valor de HE de dia útil apareça exatamente 2x no texto.
    # Filtramos valores <= 3h59 (máximo realista de HE diária) excluindo feriado.
    corpo = text[:text.find("Totais Gerais")] if "Totais Gerais" in text else text
    todos = re.findall(r'\b(\d{1,2}:\d{2})\b', corpo)
    pequenos = [v for v in todos if 0 < parse_min(v) <= 239]
    contagem = Counter(pequenos)
    he_uteis_vals = [v for v, cnt in contagem.items() if cnt == 2 and v != feriado_str]
    result["he_uteis"] = round(sum(parse_min(v) for v in he_uteis_vals) / 60, 4)

    # ── Total Horas a Descontar ─────────────────────────────────
    desconto_match = re.search(
        r"Total\s+Horas?\s+a\s+Descontar[^\d]*(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    if desconto_match:
        result["horas_desconto"] = parse_hhmm(desconto_match.group(1))

    return result


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF")

    try:
        contents = await file.read()
        texto = extract_text(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao extrair texto do PDF: {str(e)}")

    try:
        data = extract_data(texto)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao interpretar espelho: {str(e)}")

    if not data["nome"]:
        data["nome"] = file.filename.replace(".pdf", "").replace("_", " ")

    return {
        "nome": data["nome"],
        "he_uteis": data["he_uteis"],
        "he_sabado": data["he_sabado"],
        "he_feriado": data["he_feriado"],
        "he_acima8h": data["he_acima8h"],
        "horas_desconto": data["horas_desconto"],
    }


@app.get("/api/health")
def health():
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ok", "api_key_configured": True},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


# Servir frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
