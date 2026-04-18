from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
from pydantic import BaseModel
from dotenv import load_dotenv
import anthropic
import os, uuid, base64, json, traceback, time

# ---------- RATE LIMITING ----------
ip_log = defaultdict(list)
MAX_PER_IP_15MIN = 30

def get_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")

def rate_ok(ip: str) -> bool:
    now = time.time()
    ip_log[ip] = [t for t in ip_log[ip] if now - t < 900]
    if len(ip_log[ip]) >= MAX_PER_IP_15MIN:
        return False
    ip_log[ip].append(now)
    return True

try:
    import fitz
except:
    fitz = None

# ---------- INIT ----------

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- DATA ----------

def load_json(name):
    try:
        with open(name, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR loading {name}:", e)
        return None

KATALOG = load_json("pekabet-data.json") or {}
CENNIK  = load_json("cennik.json") or {}

# ---------- CONTEXT ----------

def build_context() -> str:
    context = ""
    if KATALOG:
        context += "\nKATALOG PRODUKTÓW PEKABET:\n" + json.dumps(KATALOG, ensure_ascii=False)
    if CENNIK:
        context += "\nCENNIK:\n" + json.dumps(CENNIK, ensure_ascii=False)
    return context

CONTEXT = build_context()

# ---------- PROMPT ----------

SYSTEM_PROMPT = """
Jesteś Adam — asystent techniczny Pekabet.
...
(nie zmieniane)
"""

# ---------- MEMORY ----------

conversations = {}

class ChatIn(BaseModel):
    message: str
    session_id: str | None = None

# ---------- ROUTES ----------

@app.get("/")
def home():
    return FileResponse("index.html")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

# ---------- CHAT ----------

@app.post("/chat")
def chat(data: ChatIn, request: Request):
    if not rate_ok(get_ip(request)):
        return JSONResponse(status_code=429, content={"reply": "Za dużo zapytań — spróbuj za chwilę.", "session_id": data.session_id or ""})
    sid     = data.session_id or str(uuid.uuid4())
    history = conversations.get(sid, [])

    history.append({"role": "user", "content": data.message})

    system = SYSTEM_PROMPT + CONTEXT

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            temperature=0.4,
            system=system,
            messages=history[-12:]
        )
        reply = response.content[0].text.strip()

    except Exception:
        print("CHAT ERROR:")
        traceback.print_exc()
        return {"reply": "Błąd odpowiedzi — spróbuj ponownie.", "session_id": sid}

    history.append({"role": "assistant", "content": reply})
    conversations[sid] = history

    return {"reply": reply, "session_id": sid}

# ---------- ANALYZE ----------

@app.post("/analyze")
async def analyze(
    request:    Request,
    file:       UploadFile = File(...),
    message:    str        = Form(None),
    session_id: str        = Form(None)
):
    if not rate_ok(get_ip(request)):
        return JSONResponse(status_code=429, content={"reply": "Za dużo zapytań — spróbuj za chwilę.", "session_id": session_id or ""})
    sid     = session_id or str(uuid.uuid4())
    history = conversations.get(sid, [])

    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        return {"reply": "Plik za duży (max 10 MB).", "session_id": sid}

    if file.filename.lower().endswith(".pdf") and fitz:
        doc  = fitz.open(stream=content, filetype="pdf")
        img  = doc.load_page(0).get_pixmap(dpi=100).tobytes("png")
        mime = "image/png"
    elif file.filename.lower().endswith(".png"):
        img  = content
        mime = "image/png"
    else:
        img  = content
        mime = "image/jpeg"

    b64 = base64.b64encode(img).decode()

    user_text = message or "Przeanalizuj obraz..."

    history.append({"role": "user", "content": user_text})

    system = SYSTEM_PROMPT + CONTEXT

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            temperature=0.4,
            system=system,
            messages=[
                *history[:-1],
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": b64
                            }
                        }
                    ]
                }
            ]
        )
        reply = response.content[0].text.strip()

    except Exception:
        print("ANALYZE ERROR:")
        traceback.print_exc()
        return {"reply": "Błąd analizy — spróbuj ponownie.", "session_id": sid}

    history.append({"role": "assistant", "content": reply})
    conversations[sid] = history

    return {"reply": reply, "session_id": sid}

# ---------- STATIC FILES ----------

@app.get("/icon-192.png")
def icon192(): return FileResponse("icon-192.png", media_type="image/png")

@app.get("/icon-512.png")
def icon512(): return FileResponse("icon-512.png", media_type="image/png")

@app.get("/icon-maskable.png")
def iconmaskable(): return FileResponse("icon-maskable.png", media_type="image/png")

@app.get("/apple-touch-icon.png")
def appleicon(): return FileResponse("apple-touch-icon.png", media_type="image/png")

@app.get("/favicon.ico")
def favicon(): return FileResponse("favicon.ico", media_type="image/x-icon")

@app.get("/manifest.json")
def manifest_file(): return FileResponse("manifest.json", media_type="application/json")

@app.get("/service-worker.js")
def sw(): return FileResponse("service-worker.js", media_type="application/javascript")