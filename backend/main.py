from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pdfminer.high_level import extract_text
import anthropic
import json
import io
import os

app = FastAPI(title="MUBEC — Calculadora de Horas Extras")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

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
- Converta para decimal: 5h22 = 5 + 22/60 ≈ 5.367, 5h32 = 5 + 32/60 ≈ 5.533
- Se um campo não existe ou é zero, retorne 0
- Retorne SOMENTE JSON válido, sem texto adicional, sem markdown

Formato de resposta:
{"nome":"NOME COMPLETO","he_uteis":0.0,"he_sabado":0.0,"he_feriado":0.0,"he_acima8h":0.0}

Texto do espelho de ponto:
{texto}"""


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF")

    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY não configurada. Defina a variável de ambiente."
        )

    try:
        contents = await file.read()
        texto = extract_text(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro ao extrair texto do PDF: {str(e)}")

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": PROMPT_TEMPLATE.format(texto=texto[:4000])
            }]
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Resposta da IA não é JSON válido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na API Anthropic: {str(e)}")

    return {
        "nome": data.get("nome", ""),
        "he_uteis": float(data.get("he_uteis", 0)),
        "he_sabado": float(data.get("he_sabado", 0)),
        "he_feriado": float(data.get("he_feriado", 0)),
        "he_acima8h": float(data.get("he_acima8h", 0)),
    }


@app.get("/api/health")
def health():
    api_ok = bool(ANTHROPIC_API_KEY)
    return {"status": "ok", "api_key_configured": api_ok}


# Servir frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
