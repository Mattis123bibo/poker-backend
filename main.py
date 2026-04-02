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

PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em. Analysiere das Bild exakt.

═══ WICHTIG: KARTEN RICHTIG LESEN ═══
Jede Spielkarte zeigt den Wert ZWEIMAL:
• Oben links: große Zahl/Buchstabe — das ist der ECHTE Wert
• Unten rechts: DIESELBE Zahl, aber klein und um 180° GEDREHT — das ist KEINE separate Karte!
Lese immer nur den Wert OBEN LINKS auf jeder Karte. Ignoriere die kleine umgedrehte Zahl unten rechts!

═══ FARBEN-ERKENNUNG ═══
ROT:
• ♥ HERZ = rotes Herz-Symbol
• ♦ KARO = rote Raute/Diamant

SCHWARZ — genau unterscheiden:
• ♠ PIK = schwarzer Spaten, oben spitz, unten runde Beulen + gerader Stiel
• ♣ KREUZ = schwarzes Kleeblatt, 3 runde Kreise oben + Stiel unten

═══ KARTEN-POSITIONEN ═══
• MEINE 2 HOLE CARDS: Die 2 Karten GANZ VORNE UNTEN im Bild (nah an der Kamera)
• BOARD: Karten offen in der TISCHMITTE (Flop=3, Turn=4, River=5)
• Nur offene Karten in der Mitte zählen als Board!

═══ GEGNER ZÄHLEN ═══
Zähle SPIELER/SITZPLÄTZE, nicht Karten!
• Jeder Gegner hat genau 2 verdeckte Karten
• 4 verdeckte Karten = 2 Gegner
• 6 verdeckte Karten = 3 Gegner
• Ich selbst zähle NICHT als Gegner

═══ ANALYSE ═══
• Gewinnwahrscheinlichkeit % gegen typische Ranges
• Aktuelle Handstärke mit Name
• Optimale Aktion: Raise / Call / Check / Fold
• Bet Sizing (z.B. "60% Pot")
• Gegner-Ranges Erklärung

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "",
  "boardStage": "Preflop",
  "opponents": 2,
  "position": "BTN",
  "winPct": 67,
  "handStrength": "Premium",
  "handName": "Big Slick",
  "action": "Raise",
  "actionReason": "Premium Hand, Raise preflop",
  "sizing": "3x BB",
  "opponentRanges": "Typische Ranges: Pocket Pairs, Broadway-Karten, Suited Connectors",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards vorne = X und X, Board Mitte = X, Gegner-Sitzplätze = X"
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
