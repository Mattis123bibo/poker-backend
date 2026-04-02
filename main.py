import os
import json
import httpx
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em.

═══ REGEL #1 — JEDE KARTE NUR EINMAL ZÄHLEN ═══
Jede physische Spielkarte zeigt ihren Wert ZWEIMAL auf derselben Karte:
• Oben links: große Zahl — der ECHTE Wert der Karte
• Unten rechts: DIESELBE Zahl, 180° gedreht und kleiner — NUR zur Orientierung wenn die Karte umgedreht gehalten wird

BEISPIELE was du NICHT tun darfst:
• Eine 9 hat unten rechts eine umgedrehte 9 die wie eine 6 aussieht → NICHT als extra "6" zählen!
• Eine 6 hat unten rechts eine umgedrehte 6 die wie eine 9 aussieht → NICHT als extra "9" zählen!
• Eine q hat unten rechts ein umgedrehtes q → NICHT als extra Karte zählen!
Zähle jede physische Karte nur EINMAL — lies nur den Wert OBEN LINKS!

═══ BOARD KARTEN ZÄHLEN ═══
• Flop = GENAU 3 Karten in der Tischmitte
• Turn = GENAU 4 Karten in der Tischmitte  
• River = GENAU 5 Karten in der Tischmitte
Wenn du 3 physische Karten in der Mitte siehst → Flop, board hat 3 Karten, NICHT 4!
Prüfe nochmal: Sind es wirklich separate physische Karten oder nur die Rückseiten-Markierung?

═══ FARBEN-ERKENNUNG ═══
ROT: ♥ HERZ, ♦ KARO
SCHWARZ: ♠ PIK (Spaten/Pfeil oben spitz), ♣ KREUZ (Kleeblatt, 3 runde Kreise)

═══ KARTEN-POSITIONEN ═══
• MEINE 2 HOLE CARDS: Ganz vorne unten im Bild
• BOARD: Offene Karten in der Tischmitte
• Nur tatsächlich separate physische Karten zählen!

═══ GEGNER ZÄHLEN ═══
Zähle SPIELER nicht Karten — jeder Gegner = 2 verdeckte Karten

═══ ANALYSE ═══
Gewinnwahrscheinlichkeit %, Handstärke, Aktion, Sizing, Gegner-Ranges

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "9♣ 7♠ J♠",
  "boardStage": "Flop",
  "opponents": 2,
  "position": "BTN",
  "winPct": 55,
  "handStrength": "Mittel",
  "handName": "Overcards",
  "action": "Check",
  "actionReason": "Keine Verbindung zum Board, abwarten",
  "sizing": "",
  "opponentRanges": "Typische Ranges: Pocket Pairs, Broadway-Karten, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards vorne = X, Board Mitte = genau X separate Karten, Gegner = X"
}"""

class ImageRequest(BaseModel):
    image: str

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-4-5",
                "max_tokens": 1500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": req.image
                            }
                        },
                        {"type": "text", "text": PROMPT}
                    ]
                }]
            }
        )
    data = resp.json()
    raw = data.get("content", [{}])[0].get("text", "")
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        parsed = json.loads(match.group(0) if match else clean)
        return parsed
    except Exception:
        return {"error": "Parse error", "raw": raw}

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
