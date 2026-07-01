from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTTextBox, LTTextLine
from pdfminer.high_level import extract_text
from collections import defaultdict
import re, io, os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="MUBEC")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.endswith(".html") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

def parse_min(s):
    m = re.match(r"(\d{1,3}):(\d{2})", s.strip())
    return int(m.group(1))*60+int(m.group(2)) if m else 0

EVENTO_JUSTIFICATIVA = re.compile(
    r"[Aa]testado|[Ff][eé]rias|[Ff]eriado|[Ff]olga|[Dd]ispensa|[Ll]icen[cç]",
    re.IGNORECASE
)

def tem_marcacao(linha):
    for i in linha:
        if re.search(r"\d{2}:\d{2}-\d{2}:\d{2}", i["text"]):
            if len(re.findall(r"\d{2}:\d{2}-\d{2}:\d{2}", i["text"])) > 2:
                return True
        if 180 <= i["x"] <= 360 and re.search(r"\d{2}:\d{2}-\d{2}:\d{2}", i["text"]):
            return True
    return False

def get_hp_af(linha, tipo):
    """
    HP = Horas Positivas (HE a pagar): x=431-490, < 4h para TRAB
    AF = Atrasos e Faltas (desconto):  x=491-599, ou HP >= 4h reclassificado
    Fallback: HP em x=426-430 quando HR fica em x<426 (layout Romildo)
    """
    def is_hhmm(t): return bool(re.match(r"^\d{1,2}:\d{2}$", t)) and parse_min(t) > 0

    hp_cands = [i for i in linha if 431 <= i["x"] <= 490 and is_hhmm(i["text"])]
    af_cands = [i for i in linha if 491 <= i["x"] <= 599 and is_hhmm(i["text"])]
    hp = hp_cands[0]["text"] if hp_cands else ""
    af = af_cands[0]["text"] if af_cands else ""

    # Para dias TRAB: HP >= 4h indica AF (desconto), não HE
    if hp and tipo == "TRAB" and parse_min(hp) >= 240:
        if not af: af = hp
        hp = ""

    # Fallback x=426-430 (layout com HR em x~382)
    if not hp:
        hp_ext = [i for i in linha if 426 <= i["x"] <= 430 and is_hhmm(i["text"])]
        hr_antes = [i for i in linha if 370 <= i["x"] <= 425 and is_hhmm(i["text"])]
        if hp_ext and hr_antes:
            hp_val = hp_ext[0]["text"]
            if tipo == "TRAB" and parse_min(hp_val) >= 240:
                if not af: af = hp_val
            else:
                hp = hp_val

    return hp, af

def get_items(pdf_bytes):
    rsrcmgr = PDFResourceManager(caching=False)
    device = PDFPageAggregator(rsrcmgr, laparams=LAParams())
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    items = []
    fp = io.BytesIO(bytes(pdf_bytes))
    for page in PDFPage.get_pages(fp, caching=False):
        interpreter.process_page(page)
        layout = device.get_result()
        for element in layout:
            if isinstance(element, LTTextBox):
                for line in element:
                    if isinstance(line, LTTextLine):
                        txt = line.get_text().strip()
                        if txt:
                            items.append({"text": txt, "x": round(line.x0), "y": round(line.y0, 1)})
    device.close(); fp.close()
    return items

def extract_all(pdf_bytes):
    result = {"nome":"","he_uteis":0.0,"he_sabado":0.0,"he_feriado":0.0,"he_acima8h":0.0,"horas_desconto":0.0}
    items = get_items(pdf_bytes)
    linhas = defaultdict(list)
    for item in items: linhas[item["y"]].append(item)
    he_uteis = he_sabado = he_feriado = total_af = total_debito = 0
    for y in sorted(linhas.keys(), reverse=True):
        linha = sorted(linhas[y], key=lambda i: i["x"])
        textos = [i["text"] for i in linha]
        if not result["nome"]:
            for t in textos:
                nm = re.match(r"Nome:\s+(.+)", t)
                if nm: result["nome"] = nm.group(1).strip(); break
        data_match = next((t for t in textos if re.match(r"\d{2} \w+\.,", t)), None)
        if not data_match: continue
        tipo_sep = next((t for t in textos if t in ("TRAB","DUNT","FERIADO","FOLG")), None)
        tipo_emb = None
        if not tipo_sep:
            for kw in ("TRAB","DUNT","FERIADO","FOLG"):
                if kw in data_match: tipo_emb = kw; break
        tipo = tipo_sep or tipo_emb
        if not tipo or tipo == "FOLG": continue

        hp, af = get_hp_af(linha, tipo)
        deb = next((i["text"] for i in linha if 570 <= i["x"] <= 640 and re.match(r"^-\d{1,2}:\d{2}$", i["text"])), "")
        linha_tem_marcacao = tem_marcacao(linha)
        # Bloquear AF apenas quando há evento que justifica ausência
        justificado = any(
            i["x"] > 580 and i["text"] and EVENTO_JUSTIFICATIVA.search(i["text"])
            for i in linha
        )

        if hp and linha_tem_marcacao:
            mins = parse_min(hp)
            if tipo == "TRAB":      he_uteis  += mins
            elif tipo == "DUNT":    he_sabado += mins
            elif tipo == "FERIADO": he_feriado += mins

        af_val = hp if (hp and not linha_tem_marcacao) else af
        if af_val and not justificado:
            total_af += parse_min(af_val)

        if deb:
            total_debito += parse_min(deb[1:])

    result["he_uteis"]       = round(he_uteis/60, 4)
    result["he_sabado"]      = round(he_sabado/60, 4)
    result["he_feriado"]     = round(he_feriado/60, 4)
    result["horas_desconto"] = round((total_af+total_debito)/60, 4)

    if not result["nome"]:
        try:
            text = extract_text(io.BytesIO(bytes(pdf_bytes)))
            nm = re.search(r"Nome:\s+([A-Z][A-Z\s]+?)(?:\n|Matricula|PIS|CPF)", text, re.IGNORECASE)
            if nm: result["nome"] = nm.group(1).strip()
        except: pass
    return result

@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF")
    try:
        contents = await file.read()
        data = extract_all(contents)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erro: {str(e)}")
    if not data["nome"]:
        data["nome"] = file.filename.replace(".pdf","").replace("_"," ")
    return {"nome":data["nome"],"he_uteis":data["he_uteis"],"he_sabado":data["he_sabado"],
            "he_feriado":data["he_feriado"],"he_acima8h":data["he_acima8h"],"horas_desconto":data["horas_desconto"]}

@app.get("/api/health")
def health():
    return JSONResponse(content={"status":"ok","api_key_configured":True,"version":"9.0"},
                        headers={"Cache-Control":"no-cache, no-store, must-revalidate"})

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
