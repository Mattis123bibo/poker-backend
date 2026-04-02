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

PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em. Deine Hauptaufgabe ist die EXAKTE Erkennung jeder einzelnen Spielkarte.

═══ FARBEN-ERKENNUNG — KRITISCH ═══
Es gibt 2 ROTE und 2 SCHWARZE Farben. Schaue IMMER zuerst auf die Farbe des Symbols:

ROT:
• ♥ HERZ = rotes Herz-Symbol (wie ein umgekehrtes V mit Rundungen)
• ♦ KARO = rote Raute/Diamant (auf der Spitze stehendes Quadrat)

SCHWARZ — hier ist der Unterschied ENTSCHEIDEND:
• ♠ PIK = schwarzes Spaten/Pfeil-Symbol mit STIEL UNTEN — oben spitz, unten runde Beulen + gerader Stiel
• ♣ KREUZ = schwarzes KLEEBLATT — 3 runde Kreise oben + Stiel unten, wie ein Kleeblatt

MERKE: Bei schwarzen Karten IMMER das Symbol genau ansehen:
- Ist es ein spitzer Pfeil mit Stiel? → ♠ PIK
- Sind es 3 runde Bälle/Kreise wie ein Kleeblatt? → ♣ KREUZ

═══ POSITION DER KARTEN IM BILD ═══
• MEINE HOLE CARDS: Die 2 Karten GANZ VORNE UNTEN im Bild (nah an der Kamera)
• BOARD: Karten in der TISCHMITTE — Flop (3), Turn (4), River (5)
• GEGNER: Verdeckte Karten weiter hinten

═══ VORGEHEN ═══
1. Jeden sichtbaren Kartenwert einzeln ablesen (A K Q J T 9 8 7 6 5 4 3 2)
2. Bei JEDEM schwarzen Symbol nochmal genau hinschauen: Spaten oder Kleeblatt?
3. Hole Cards (vorne unten) identifizieren
4. Board Karten (Mitte) identifizieren
5. Gegneranzahl zählen

═══ ANALYSE ═══
• Gewinnwahrscheinlichkeit % gegen typische Ranges (berücksichtige Anzahl Gegner)
• Aktuelle Handstärke mit Namen (z.B. "Flush Draw", "Top Pair", "Zwei Paare")
• Optimale Aktion: Raise / Call / Check / Fold
• Bet Sizing Empfehlung (z.B. "50-75% Pot")
• Gegner-Ranges und warum

Antworte NUR als JSON:
{
  "myHand": "A♠ K♥",
  "myHandConfidence": "sicher",
  "board": "J♦ 9♣ 3♥",
  "boardStage": "Flop",
  "opponents": 3,
  "position": "BTN",
  "winPct": 58,
  "handStrength": "Stark",
  "handName": "Top Pair Top Kicker",
  "action": "Raise",
  "actionReason": "Top Pair Top Kicker, Value gegen Draws",
  "sizing": "60% Pot",
  "opponentRanges": "Typische Ranges: Pocket Pairs 77+, Broadway AJ+, Suited Connectors 87s+",
  "analysis": "Detaillierte Analyse auf Deutsch: Hand-Stärke, Board-Textur, Pot Odds, Empfehlung.",
  "whatISee": "Genaue Beschreibung: Hole Cards vorne = X, Board Mitte = X, Gegner = X"
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
