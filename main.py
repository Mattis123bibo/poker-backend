import os
import json
import httpx
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

IMAGE_PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em.

═══ SCHRITT 1: HOLE CARDS (vorne unten im Bild) ═══
- Karte 1: Wert oben links + Farbe
- Karte 2: Wert oben links + Farbe

═══ SCHRITT 2: BOARD (Tischmitte, STRIKT von LINKS nach RECHTS) ═══
- Flop = genau 3 Karten, Turn = 4, River = 5
- Jede Karte einzeln von links nach rechts beschreiben
- Mittlere Karte NICHT übersehen!
- Reihenfolge NIEMALS umsortieren!
- Wert immer oben links ablesen — kleine umgedrehte Zahl unten rechts IGNORIEREN!

═══ SCHRITT 3: GEGNER ═══
- Verdeckte Karten (Kartenrücken) zählen → jeder Stapel = 1 Gegner
- Keine verdeckten Karten sichtbar → opponents = 1 (Minimum)
- Nur zählen was wirklich sichtbar ist!

═══ SCHRITT 4: HANDSTÄRKE KORREKT BESTIMMEN ═══
Die Kartenwerte in absteigender Reihenfolge: A K Q J T 9 8 7 6 5 4 3 2

PAARE mit Board-Karten — SEHR WICHTIG:
• TOP PAIR = eine meiner Hole Cards bildet ein Paar mit der HÖCHSTEN Board-Karte
  Beispiel: Ich habe K♠, Board ist K♥ 9♣ 4♦ → Top Pair (K ist höchste Board-Karte)
  Beispiel: Ich habe J♥, Board ist Q♥ J♠ 9♣ → KEIN Top Pair! Q ist höher → Middle Pair!
• MIDDLE PAIR = Paar mit der zweithohen Board-Karte
  Beispiel: Ich habe J♥, Board ist Q♥ J♠ 9♣ → Middle Pair (J ist zweithöchste)
• BOTTOM PAIR = Paar mit der niedrigsten Board-Karte
• OVERPAIR = Pocket Pair höher als alle Board-Karten
• TWO PAIR = zwei verschiedene Paare
• SET / TRIPS = drei gleiche Karten
• STRAIGHT = fünf aufeinanderfolgende Karten
• FLUSH = fünf Karten gleicher Farbe
• DRAWS korrekt benennen: Flush Draw, Straight Draw, OESD, Gutshot

PRÜFE IMMER: Welches ist die höchste Karte am Board? Bilde ich ein Paar damit? Wenn nein → kein Top Pair!

═══ SCHRITT 5: ANALYSE ═══
• Gewinnwahrscheinlichkeit % gegen typische Ranges (realistisch!)
• Handstärke mit KORREKTEM Namen (siehe oben)
• Aktion: Raise / Call / Check / Fold mit Begründung
• Sizing (z.B. "60% Pot")
• Gegner-Ranges
• Board-Textur: nass (connected, flush-möglich) oder trocken?

Antworte NUR als JSON:
{
  "myHand": "K♠ J♥",
  "myHandConfidence": "sicher",
  "board": "9♣ J♠ Q♥",
  "boardStage": "Flop",
  "opponents": 1,
  "opponentsConfidence": "geschätzt",
  "position": "unbekannt",
  "winPct": 45,
  "handStrength": "Mittel",
  "handName": "Middle Pair (Buben) + Overcards",
  "action": "Call",
  "actionReason": "Middle Pair auf nassem Board, Q gefährlich für Gegner",
  "sizing": "",
  "opponentRanges": "Q9s, QJ, T8 für Straight Draw, Pocket Pairs",
  "analysis": "Detaillierte Analyse auf Deutsch mit korrekter Handbewertung.",
  "whatISee": "Hole Cards = [X] [X]. Board links nach rechts = [X] [X] [X]. Verdeckte Karten = X Stapel."
}"""

RECALC_PROMPT = """Du bist ein professioneller Texas Hold'em Poker-Analyst.

Analysiere diese exakte Hand:
MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

HANDSTÄRKE KORREKT BESTIMMEN:
Kartenwerte absteigend: A K Q J T 9 8 7 6 5 4 3 2

PAARE — GENAU PRÜFEN:
• TOP PAIR = Paar mit der HÖCHSTEN Board-Karte
  → Welche ist die höchste Board-Karte? Habe ich diese in der Hand?
• MIDDLE PAIR = Paar mit der zweithohen Board-Karte
• BOTTOM PAIR = Paar mit der niedrigsten Board-Karte  
• OVERPAIR = Pocket Pair höher als ALLE Board-Karten
• TWO PAIR, SET, STRAIGHT, FLUSH korrekt erkennen
• DRAWS: Flush Draw (4 gleiche Farbe), OESD (4 aufeinanderfolgend, beide Seiten offen), Gutshot (1 Karte fehlt innen)

Beispiel: Hand K♠ J♥, Board 9♣ J♠ Q♥
→ Höchste Board-Karte = Q♥. Habe ich Q? Nein.
→ Zweithöchste Board-Karte = J♠. Habe ich J? Ja! → Middle Pair Buben, K als Kicker

Berechne präzise:
- Gewinnwahrscheinlichkeit % gegen typische Ranges
- Handstärke mit KORREKTEM Namen
- Aktion: Raise / Call / Check / Fold mit Begründung
- Bet Sizing
- Gegner-Ranges
- Board-Textur (nass/trocken)
- Detaillierte Analyse auf Deutsch

Antworte NUR als JSON:
{{
  "myHand": "{myHand}",
  "board": "{board}",
  "boardStage": "{boardStage}",
  "opponents": {opponents},
  "winPct": 45,
  "handStrength": "Mittel",
  "handName": "Middle Pair (Buben) + K Kicker",
  "action": "Call",
  "actionReason": "Middle Pair auf nassem Board, vorsichtig spielen",
  "sizing": "",
  "opponentRanges": "QJ, Q9, T8 Straight Draw, Pocket Pairs",
  "analysis": "Detaillierte Analyse auf Deutsch mit konkreten Empfehlungen.",
  "whatISee": ""
}}"""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 1
    boardStage: str = "Preflop"

class ImageRequest(BaseModel):
    image: str
    override: Optional[Override] = None

def get_board_stage(board: str) -> str:
    cards = re.findall(r'[AKQJT2-9]{1,2}[♠♥♦♣]', board)
    return {0:"Preflop",3:"Flop",4:"Turn",5:"River"}.get(len(cards),"Flop")

@app.post("/analyze")
async def analyze(req: ImageRequest):
    async with httpx.AsyncClient(timeout=45) as client:
        if req.override:
            stage = req.override.boardStage or get_board_stage(req.override.board)
            board_display = req.override.board if req.override.board else "Kein Board (Preflop)"
            prompt = RECALC_PROMPT.format(
                myHand=req.override.myHand or "Unbekannt",
                board=board_display,
                boardStage=stage,
                opponents=req.override.opponents
            )
            messages = [{"role":"user","content":[{"type":"text","text":prompt}]}]
        else:
            messages = [{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":req.image}},
                {"type":"text","text":IMAGE_PROMPT}
            ]}]

        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model":"claude-opus-4-5","max_tokens":1500,"messages":messages}
        )

    data = resp.json()
    raw = data.get("content",[{}])[0].get("text","")
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        parsed = json.loads(match.group(0) if match else clean)
        return parsed
    except Exception:
        return {"error":"Parse error","raw":raw}

@app.get("/")
def root():
    return {"status":"Poker AI Backend online"}
