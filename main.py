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

HAND_EVAL = """
═══ PFLICHT: HANDSTÄRKE SCHRITT FÜR SCHRITT BERECHNEN ═══

Du MUSST diese Schritte der Reihe nach durchführen — kein Überspringen!

SCHRITT A: Board-Karten sortieren (hoch nach niedrig)
Kartenwerte: A=14, K=13, Q=12, J=11, T=10, 9=9, 8=8, 7=7, 6=6, 5=5, 4=4, 3=3, 2=2
Beispiel: Board 9♣ Q♥ J♣ → sortiert: Q(12) > J(11) > 9(9)

SCHRITT B: Pair-Typ bestimmen
• Bilde ich ein Paar mit der HÖCHSTEN Board-Karte? → TOP PAIR
• Bilde ich ein Paar mit der ZWEITHÖCHSTEN Board-Karte? → MIDDLE PAIR
• Bilde ich ein Paar mit der NIEDRIGSTEN Board-Karte? → BOTTOM PAIR
• Habe ich Pocket Pair HÖHER als alle Board-Karten? → OVERPAIR

KRITISCHES BEISPIEL — GENAU LERNEN:
Hand: K♠ J♥ | Board: 9♣ Q♥ J♣
Board sortiert: Q(12) > J(11) > 9(9)
- Höchste Board-Karte = Q → Habe ich Q in der Hand? NEIN
- Zweithöchste Board-Karte = J → Habe ich J in der Hand? JA (J♥)
→ ERGEBNIS: MIDDLE PAIR (Buben), K als Kicker
→ NIEMALS "Top Pair" nennen wenn die höchste Board-Karte kein Paar bildet!

SCHRITT C: Straights prüfen
Alle Karten: Hole Cards + Board-Karten zusammen
Gibt es 5 aufeinanderfolgende Werte?
Beispiel: K♠ J♥ + 9♣ Q♥ J♣ T♠ → K-Q-J-T-9 = STRAIGHT!
Ist es Nuts? Welche höhere Straight wäre möglich?
Beispiel: A+K würde A-K-Q-J-T (Broadway) machen → meine K-Q-J-T-9 ist NICHT Nuts

SCHRITT D: Flush prüfen
4+ Karten gleicher Farbe → Flush Draw oder Flush

SCHRITT E: Nuts bestimmen — ABSOLUTE NUTS
Die Nuts ist die EINZIGE bestmögliche Hand — nicht "beste Pair-Hand" oder "bestes Set"!
Handrangfolge beachten: Straight schlägt Set, Flush schlägt Straight, usw.
Wenn eine Straight möglich ist → Set ist NICHT Nuts!
Wenn ein Flush möglich ist → Straight ist NICHT Nuts!
Nur die absolut höchste erreichbare Hand auf diesem Board = Nuts
Was ist die bestmögliche Hand auf diesem Board?
Vergleiche mit meiner Hand → Nuts? Ja/Nein + Erklärung

SCHRITT F: Board-Textur
NASS = Straights/Flushes möglich (connected und/oder suited)
TROCKEN = wenige Draws möglich
MONOTON = alle gleiche Farbe
GEPAART = Pair am Board

SCHRITT G: Win% realistisch
• Nuts oder nahe Nuts: 80-95%
• Starke gemachte Hand (Top Pair Top Kicker): 60-75%
• Middle/Bottom Pair: 35-50%
• Overpair: 65-75%
• Flush/Straight Draw: 30-40% am Flop, 18-20% am Turn
• Combo Draw: 50-60%
• Luft/Overcards: 20-35%
Bei mehr Gegnern: Win% sinkt entsprechend

SCHRITT H: Aktion
• Raise/Bet: Starke Hands (Value), starke Draws (Semi-Bluff)
• Call: Mittlere Hands, gute Draws mit Pot Odds
• Check: Schwache Hands, Kontrolle, Trapping
• Fold: Sehr schwach, keine Draws, schlechte Pot Odds
"""

IMAGE_PROMPT = HAND_EVAL + """
═══ BILDANALYSE ═══

HOLE CARDS (ganz vorne unten im Bild):
FARBEN — NOCHMAL GENAU HINSCHAUEN:
• ♥ HERZ = ROT, Herz-Symbol
• ♦ KARO = ROT, Raute/Diamant
• ♠ PIK = SCHWARZ, Spaten (oben spitz)
• ♣ KREUZ = SCHWARZ, Kleeblatt (3 runde Kreise)
WICHTIG: Herz und Karo sind IMMER ROT — egal wie dunkel das Foto ist!
Kreuz und Pik sind IMMER SCHWARZ!
Wenn du dir bei einer Farbe unsicher bist: schaue ob das Symbol rot oder schwarz/dunkel ist!
Wert immer oben links ablesen — kleine umgedrehte Zahl unten rechts IGNORIEREN!

BOARD (Tischmitte, STRIKT von LINKS nach RECHTS, Reihenfolge NICHT verändern):
Flop=3, Turn=4, River=5 Karten — mittlere Karte NICHT vergessen!

GEGNER: Verdeckte Karten (Kartenrücken) zählen → 1 Stapel = 1 Gegner
Keine verdeckten Karten sichtbar → opponents = 1

Führe dann Schritte A-H durch und antworte NUR als JSON:
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
  "nutsDescription": "Nuts wäre Set oder Straight mit QJ oder T8",
  "action": "Check",
  "actionReason": "Middle Pair auf nassem Board, Q ist Gefahr, defensiv spielen",
  "sizing": "",
  "boardTexture": "Nass — Straight- und Flush-Draws möglich",
  "opponentRanges": "QJ für Two Pair, T8 für Straight Draw, Flush Draws, Q für Top Pair",
  "analysis": "Detaillierte Analyse auf Deutsch.",
  "whatISee": "Hole Cards = [X] [X]. Board links nach rechts = [X] [X] [X]. Gegner-Stapel = X."
}"""

RECALC_PROMPT = HAND_EVAL + """
═══ ANALYSE DIESER HAND ═══

MEINE HOLE CARDS: {myHand}
BOARD: {board}
BOARD PHASE: {boardStage}
ANZAHL GEGNER: {opponents}

Führe Schritte A-H durch:
A: Board sortieren von hoch nach niedrig
B: Pair-Typ bestimmen (Top/Middle/Bottom/Overpair) — SCHRITT FÜR SCHRITT!
C: Straight prüfen (alle Karten zusammen)
D: Flush prüfen
E: Nuts bestimmen
F: Board-Textur
G: Win% berechnen
H: Aktion empfehlen

Antworte NUR als JSON:
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
