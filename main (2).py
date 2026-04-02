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

═══ FARBEN-ERKENNUNG ═══
ROT:
• ♥ HERZ = rotes Herz-Symbol
• ♦ KARO = rote Raute/Diamant

SCHWARZ — genau unterscheiden:
• ♠ PIK = schwarzer Spaten, oben spitz zulaufend, unten runde Beulen + gerader Stiel
• ♣ KREUZ = schwarzes Kleeblatt, 3 runde Kreise oben + Stiel unten

═══ KARTEN-POSITIONEN ═══
• MEINE 2 HOLE CARDS: Die 2 Karten GANZ VORNE UNTEN im Bild
• BOARD: Karten offen in der TISCHMITTE (Flop=3, Turn=4, River=5)
• GEGNER KARTEN: Verdeckte Karten der anderen Spieler

═══ GEGNER ZÄHLEN — WICHTIG ═══
Zähle die ANZAHL DER SPIELER, NICHT die Anzahl der Karten!
• Jeder Gegner hat genau 2 verdeckte Karten
• 4 verdeckte Karten = 2 Gegner
• 6 verdeckte Karten = 3 Gegner
• Zähle PERSONEN/SITZPLÄTZE, nicht Karten
• Ich selbst zähle NICHT als Gegner

═══ ANALYSE ═══
• Gewinnwahrscheinlichkeit % gegen typische Ranges
• Aktuelle Handstärke
• Optimale Aktion: Raise / Call / Check / Fold
• Bet Sizing (z.B. "60% Pot")
• Gegner-Ranges Erklärung

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "J♦ 9♣ 3♥",
  "boardStage": "Flop",
  "opponents": 2,
  "position": "BTN",
  "winPct": 58,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Top Pair Top Kicker, Value gegen Draws",
  "sizing": "60% Pot",
  "opponentRanges": "Typische Ranges: Pocket Pairs 77+, Broadway AJ+, Suited Connectors 87s+",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards vorne = X und X, Board Mitte = X, Anzahl Gegner-Sitzplätze = X"
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
