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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

HAND_EVAL = """
═══ HANDSTÄRKE SCHRITT FÜR SCHRITT ═══

Kartenwerte: A=14, K=13, Q=12, J=11, T=10, 9-2 entsprechend

SCHRITT A: Board sortieren hoch nach niedrig
SCHRITT B: Pair-Typ bestimmen
• TOP PAIR = Paar mit HÖCHSTER Board-Karte
• MIDDLE PAIR = Paar mit zweithöchster Board-Karte  
• BOTTOM PAIR = Paar mit niedrigster Board-Karte
• OVERPAIR = Pocket Pair höher als ALLE Board-Karten
KRITISCH: Immer fragen — welche ist die höchste Board-Karte? Bilde ich Paar DAMIT?

SCHRITT C: Straights prüfen (alle 5+ Karten zusammen)
SCHRITT D: Flush prüfen (4+ gleiche Farbe)

SCHRITT E: ABSOLUTE NUTS bestimmen
Nuts = DIE EINE bestmögliche Hand auf diesem Board — es gibt nur EINE Nuts, kein "oder"!
Handrangfolge: Straight Flush > Quads > Full House > Flush > Straight > Set > Two Pair > Pair
Wenn Straight möglich → Set ist NICHT Nuts!
Wenn Flush möglich → Straight ist NICHT Nuts!

SCHRITT F: Win% realistisch
• Nuts/nahe Nuts: 80-95% | Top Pair Top Kicker: 60-75%
• Overpair: 65-75% | Middle Pair: 35-50% | Bottom Pair: 25-40%
• Flush Draw: 35% Flop, 20% Turn | Straight Draw OESD: 32% Flop, 18% Turn
• Combo Draw: 50-60% | Overcards only: 25-35%

SCHRITT G: Aktion
Raise/Bet: Starke Hands (Value) oder starke Draws (Semi-Bluff)
Call: Mittlere Hands, gute Draws mit Pot Odds
Check: Schwache Hands, Kontrolle, Trapping
Fold: Sehr schwach, keine Draws, schlechte Pot Odds
"""

IMAGE_PROMPT = """Du bist ein professioneller Poker-Bildanalyst für Texas Hold'em.

═══ FARBERKENNUNG — ABSOLUT KRITISCH ═══
Es gibt NUR 2 rote und 2 schwarze Farben:

ROTE KARTEN (die Farbe ist ROT/ORANGE auf der Karte):
• ♥ HERZ — rotes Herz-Symbol (wie ein Herz)
• ♦ KARO — rote Raute/Diamant

SCHWARZE KARTEN (die Farbe ist SCHWARZ/DUNKEL auf der Karte):
• ♠ PIK — schwarzer Spaten (oben spitz zulaufend, unten runde Beulen)
• ♣ KREUZ — schwarzes Kleeblatt (3 runde Kreise oben)

FARBTEST — IMMER DURCHFÜHREN:
Für jede Karte: Ist das Symbol auf der Karte ROT oder SCHWARZ?
→ ROT = entweder ♥ oder ♦ (niemals ♠ oder ♣!)
→ SCHWARZ = entweder ♠ oder ♣ (niemals ♥ oder ♦!)

HÄUFIGE FEHLER VERMEIDEN:
• Dame Herz (Q♥) hat ein ROTES Symbol — auch bei schlechtem Licht bleibt es rot!
• Dame Kreuz (Q♣) hat ein SCHWARZES Symbol
• Wenn du Q♣ erkennst: Nochmal prüfen — ist das Symbol wirklich schwarz oder nur dunkel-rot?
• Bei Kunstlicht oder Schatten: Schaue auf die Grundfarbe des Symbols, nicht auf den Glanz

═══ ZWEI-SCHRITT VERIFIKATION ═══
Nach der ersten Erkennung jeder Karte: NOCHMAL HINSCHAUEN!
1. Erster Blick: Karte erkennen
2. Zweiter Blick: Ist die Farbe wirklich korrekt? Rot oder schwarz?
Erst dann weitermachen!

═══ KARTEN-POSITIONEN ═══
HOLE CARDS — MEINE 2 EIGENEN KARTEN:
Diese 2 Karten liegen IMMER am unteren Bildrand — egal ob das Handy quer oder hochkant gehalten wird!
• Hochkant: die 2 Karten ganz unten im Bild
• Querformat: die 2 Karten am unteren Rand
Sie sind NÄHER zur Kamera als alle anderen Karten und liegen VOR dem Tisch.
NIEMALS Tischkarten (Board/Flop) mit den Hole Cards verwechseln!
Die Hole Cards sind IMMER die 2 Karten die am nächsten zur Kamera/zum Betrachter liegen.
BOARD: Tischmitte STRIKT von LINKS nach RECHTS — Reihenfolge NICHT verändern!
• Flop = genau 3 Karten | Turn = 4 | River = 5
• Mittlere Karte beim Flop NICHT vergessen!
• Kleine umgedrehte Zahl unten rechts auf jeder Karte = IGNORIEREN (gleiche Karte nochmal)

GEGNER: Verdeckte Karten (Kartenrücken) zählen → 1 Stapel = 1 Gegner
Keine verdeckten Karten sichtbar → opponents = 1

""" + HAND_EVAL + """

Führe Schritte A-G durch und antworte NUR als JSON:
{
  "myHand": "K♠ J♥",
  "myHandConfidence": "sicher",
  "board": "9♣ Q♥ J♣",
  "boardStage": "Flop",
  "opponents": 1,
  "winPct": 42,
  "handStrength": "Mittel",
  "handName": "Middle Pair (Buben, K Kicker)",
  "isNuts": false,
  "nutsDescription": "Nuts wäre T+K für Straight 9-T-J-Q-K",
  "action": "Check",
  "actionReason": "Middle Pair auf nassem Board, defensiv spielen",
  "sizing": "",
  "boardTexture": "Nass — Straight- und Flush-Draws möglich",
  "opponentRanges": "QJ für Two Pair, T8 für Straight Draw, Flush Draws",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards = [X] [X]. Board links nach rechts = [X] [X] [X]. Farben nochmal geprüft: [bestätigung]. Gegner-Stapel = X."
}"""

RECALC_PROMPT = HAND_EVAL + """
═══ ANALYSE DIESER HAND ═══
MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

Führe Schritte A-G durch. Antworte NUR als JSON:
{{
  "myHand": "{myHand}",
  "board": "{board}",
  "boardStage": "{boardStage}",
  "opponents": {opponents},
  "winPct": 42,
  "handStrength": "Mittel",
  "handName": "Middle Pair (Buben, K Kicker)",
  "isNuts": false,
  "nutsDescription": "Nuts wäre ...",
  "action": "Check",
  "actionReason": "Begründung",
  "sizing": "",
  "boardTexture": "Nass",
  "opponentRanges": "Typische Ranges",
  "analysis": "Detaillierte Analyse auf Deutsch.",
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
    async with httpx.AsyncClient(timeout=60) as client:
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
            # Two-pass: first scan, then verify colors
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
            json={"model":"claude-opus-4-5","max_tokens":2000,"messages":messages}
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
