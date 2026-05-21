from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pdfminer.high_level import extract_text
import google.generativeai as genai
import json
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

PROMPT_TEMPLATE = """Você é um assistente especializado em leitura de espelhos de ponto brasileiros.

Analise o texto abaixo extraído de um espelho de ponto e extraia:
1. Nome completo do funcionário (campo "Nome:" no cabeçalho)
2. H.E. Dia Útil total (campo "H.E. Dia Útil" no resumo "Horas a Pagar ou Descontar")
3. H.E. Sábado total (dias marcados como DUNT que tiveram marcação de ponto — some as horas positivas desses dias; sábados sem marcação = 0)
4. H.E. Feriado total (campo "H.E. Feriado" no resumo final)
5. H.E. acima de 8h em dom/feriado (horas extras além de 8h diárias em domingo ou feriado — geralmente ausente)

REGRAS IMPORTANTES:
- Use os campos do resumo "Horas a Pagar ou Descontar" como fonte principal para HE úteis e feriados
- Para sábados (DUNT): some manualmente as horas positivas de cada dia DUNT que teve marcação de ponto
- Converta para decimal: 5h22 = 5 + 22/60 = 5.367, 5h32 = 5 + 32/60 = 5.533
- Se um campo não existe ou é zero, retorne 0
- Retorne SOMENTE JSON puro, sem markdown, sem aspas especiais, sem texto antes ou depois

Formato EXATO de resposta (use aspas duplas simples):
{"nome":"NOME COMPLETO","he_uteis":0.0,"he_sabado":0.0,"he_feriado":0.0,"he_acima8h":0.0}

Texto do espelho de ponto:
{texto}"""


def clean_json(raw: str) -> str:
    """Limpa artefatos comuns da resposta do Gemini antes de parsear."""
    # aspas tipográficas
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    # blocos markdown
    raw = raw.replace("```json", "").replace("```", "")
    # espaços e quebras extras
    raw = raw.strip()
    # extrair só o JSON se houver texto antes/depois
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return raw


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF")

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY não configurada. Defina a variável de ambiente."
        )

    try:
        contents = await file.read()
        texto = extract_text(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao extrair texto do PDF: {str(e)}")

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(PROMPT_TEMPLATE.format(texto=texto[:4000]))
        raw = clean_json(response.text)
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON inválido na resposta da IA: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na API Gemini: {str(e)}")

    return {
        "nome": str(data.get("nome", "")),
        "he_uteis": float(data.get("he_uteis", 0)),
        "he_sabado": float(data.get("he_sabado", 0)),
        "he_feriado": float(data.get("he_feriado", 0)),
        "he_acima8h": float(data.get("he_acima8h", 0)),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "api_key_configured": bool(GEMINI_API_KEY)}


# Servir frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
