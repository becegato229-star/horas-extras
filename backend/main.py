from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pdfminer.high_level import extract_text
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


def hm_to_decimal(h: int, m: int) -> float:
    return round(h + m / 60, 4)


def parse_hhmm(s: str) -> float:
    m = re.match(r"(\d{1,3}):(\d{2})", s.strip())
    if m:
        return hm_to_decimal(int(m.group(1)), int(m.group(2)))
    return 0.0


def extract_data(text: str) -> dict:
    result = {
        "nome": "",
        "he_uteis": 0.0,
        "he_sabado": 0.0,
        "he_feriado": 0.0,
        "he_acima8h": 0.0,
    }

    # ── Nome ──────────────────────────────────────────────────────────────
    nome_match = re.search(
        r"Nome:\s+([A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ][A-ZÁÉÍÓÚÀÂÊÎÔÛÃÕÇ\s]+?)(?:\n|Matrícula|PIS|CPF)",
        text, re.IGNORECASE
    )
    if nome_match:
        result["nome"] = nome_match.group(1).strip()

    # ── HE Dia Útil (busca em qualquer posição do texto) ──────────────────
    # Padrão Flash: "H.E. Dia Útil Não Trab. 1o.P. Diurno: 05:32"
    # Nota: no sistema Flash, sábado DUNT aparece aqui como "Dia Útil"
    # Na nossa regra, esse valor vai para coluna SÁBADO (pois sáb = DSR aqui)
    he_util_match = re.search(
        r"H\.E\.?\s*Dia\s*[ÚU]til[^\n]{0,80}?(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    if he_util_match:
        # No contexto MUBEC: sábado DUNT classificado como "Dia Útil" no Flash
        # vai para coluna sábado (+100%), não para dias úteis
        result["he_sabado"] = parse_hhmm(he_util_match.group(1))

    # ── HE Feriado ────────────────────────────────────────────────────────
    he_feriado_match = re.search(
        r"H\.E\.?\s*Feriado[^\n]{0,60}?(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    if he_feriado_match:
        result["he_feriado"] = parse_hhmm(he_feriado_match.group(1))

    # ── HE acima de 8h (dom/feriado) ──────────────────────────────────────
    he_acima_match = re.search(
        r"H\.E\.?\s*(?:acima|além)[^\n]{0,60}?(\d{1,3}:\d{2})",
        text, re.IGNORECASE
    )
    if he_acima_match:
        result["he_acima8h"] = parse_hhmm(he_acima_match.group(1))

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
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "api_key_configured": True}


# Servir frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
