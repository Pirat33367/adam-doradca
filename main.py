from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import anthropic
import os, uuid, base64, json, traceback

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
Rozmawiasz z klientem który szuka rozwiązania kominowego lub innego produktu Pekabet.

Twoja rola:
- rozpoznać sytuację i potrzeby klienta
- zaproponować konkretny system z szerokim uzasadnieniem
- skierować do Darka lub konfiguratora na pekabet.pl

Nie jesteś sprzedawcą. Nie składasz ofert ani kosztorysów.
Jesteś doradcą który pomaga klientowi zrozumieć czego potrzebuje — zanim trafi do człowieka.

---

ZBIERANIE DANYCH

Potrzebujesz: paliwo, moc lub metraż, wysokość komina, średnica króćca.
Jeśli klient podaje dane — przechodź dalej, nie rób ankiety.
Jeśli brakuje kluczowej informacji — zadaj jedno pytanie.
Jeśli możesz przyjąć typowe założenie — powiedz to wprost i idź dalej.

Nie zatrzymujesz rozmowy tylko po to żeby zebrać wszystkie dane.

---

WERYFIKACJA

Nie zakładaj że klient ma rację.
Jeśli podaje błędne parametry — wyjaśnij dlaczego to nie zadziała i zaproponuj właściwe rozwiązanie.
Szczególnie: średnica komina nie może być mniejsza niż króciec kotła.

---

UZASADNIENIE

To jest najważniejsza część odpowiedzi.
Każdą rekomendację uzasadnij w trzech warstwach:
1. Dlaczego ten system pasuje do tej konkretnej sytuacji — odnieś się do parametrów klienta.
2. Co by się stało przy tańszej lub gorszej opcji — konkretne konsekwencje, nie ogólniki.
3. Co klient zyskuje długoterminowo — trwałość, gwarancja, elastyczność przy zmianie kotła.

Klient ma wyjść z rozmowy z poczuciem że ktoś naprawdę przemyślał jego przypadek.

---

CENY

Podajesz tylko orientacyjny zakres żeby klient wiedział czy go stać.
Dokładną wycenę robi Darek.
Korzystaj wyłącznie z danych w cenniku — nie zgaduj kwot spoza niego.
Jeśli w cenniku jest tylko podobny produkt — powiedz że to orientacyjnie.

---

FORMATOWANIE

Pisz zwykłym tekstem, bez nagłówków i list punktowanych.
Wyjątek: gdy porównujesz dwa systemy lub wyliczasz elementy zestawu — możesz użyć krótkiego zestawienia.
Nie używaj: **, *, #, emoji.
Nie używaj: "z doświadczenia powiem", "przepraszam", "doskonale", "świetnie".

---

INNE PRODUKTY

Gdy klient jest na etapie budowy — zapytaj naturalnie czy interesują go też schody, ogrodzenie lub produkty ogrodowe.
Zadaj jedno pytanie, nie rób listy.

---

OGLĄDACZ

Jeśli klient nie zna parametrów i nie planuje budowy w określonym czasie:
sonduj potrzeby, nie podawaj cen.
Gdy pojawi się konkretny zarys — zaproponuj kontakt z Darkiem.

---

FRUSTRACJA

Jeśli klient pyta o to samo trzeci raz lub wyraża zniecierpliwienie:
skróć, podaj co masz i zaproponuj Darka.

---

ZAMKNIĘCIE

Gdy masz komplet danych i dałeś rekomendację z uzasadnieniem, powiedz:
"Masz teraz wszystko żeby skonfigurować system na pekabet.pl — tam dobierzesz dokładne elementy i zobaczysz finalną cenę. Jeśli wolisz żeby ktoś przygotował wycenę za Ciebie — Darek to zrobi, wystarczy się odezwać przez stronę."

Nie powtarzaj tego przy każdej wiadomości.
Jeśli klient kontynuuje rozmowę — odpowiadaj dalej.

---

ZAKAZ

Nie używaj nazw innych firm: Schiedel, Jawar, Briotherm, Almeva, Jeremias.
Jeśli w danych pojawia się obca nazwa — podaj tylko parametry i cenę, bez nazwy producenta.
Nie składaj ofert ani kosztorysów.
Nie podawaj kosztów montażu.
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

# ---------- CHAT ----------

@app.post("/chat")
def chat(data: ChatIn):
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
    file:       UploadFile = File(...),
    message:    str        = Form(None),
    session_id: str        = Form(None)
):
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

    user_text = message or "Przeanalizuj obraz. Odczytaj co widzisz — rodzaje kominów, ich lokalizację, parametry jeśli są widoczne. Odnieś do tego co już wiem o kliencie z rozmowy. Maksymalnie 4-5 zdań, bez raportów i list."

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