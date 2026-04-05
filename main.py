import os
import json
import httpx
import re
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from treys import Card, Evaluator, Deck

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["Content-Type"])

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
evaluator = Evaluator()

SUIT_MAP = {'♠':'s','♥':'h','♦':'d','♣':'c'}
VAL_MAP = {'A':'A','K':'K','Q':'Q','J':'J','T':'T','9':'9','8':'8','7':'7','6':'6','5':'5','4':'4','3':'3','2':'2'}
rank_chars = "23456789TJQKA"
rank_names = {'2':'Zwei','3':'Drei','4':'Vier','5':'Fünf','6':'Sechs','7':'Sieben','8':'Acht',
              '9':'Neun','T':'Zehn','J':'Bube','Q':'Dame','K':'König','A':'Ass'}
suit_names = {'s':'♠','h':'♥','d':'♦','c':'♣'}
VAL_ORDER = {'A':14,'K':13,'Q':12,'J':11,'T':10,'9':9,'8':8,'7':7,'6':6,'5':5,'4':4,'3':3,'2':2}

def to_treys(card_str):
    card_str = card_str.strip()
    if len(card_str) < 2: return None
    suit = card_str[-1]
    val = card_str[:-1]
    if val == '10': val = 'T'
    t_suit = SUIT_MAP.get(suit)
    t_val = VAL_MAP.get(val)
    if not t_suit or not t_val: return None
    try: return Card.new(t_val + t_suit)
    except: return None

def parse_cards(s):
    if not s: return []
    cards = re.findall(r'[AKQJT2-9]{1,2}[♠♥♦♣]', s)
    result = []
    for c in cards:
        t = to_treys(c)
        if t: result.append(t)
    return result

def card_val(c):
    return VAL_ORDER.get(rank_chars[Card.get_rank_int(c)], 0)

def simulate_win(hole, board, opponents, n=2000):
    if len(hole) != 2: return 0
    wins = ties = 0
    known = set(hole + board)
    for _ in range(n):
        deck = Deck()
        deck.cards = [c for c in deck.cards if c not in known]
        random.shuffle(deck.cards)
        needed = 5 - len(board)
        sim_board = board + deck.cards[:needed]
        rem = deck.cards[needed:]
        opp_hands = [[rem[i*2], rem[i*2+1]] for i in range(opponents) if i*2+1 < len(rem)]
        if len(opp_hands) < opponents: continue
        try:
            my_rank = evaluator.evaluate(sim_board, hole)
            opp_ranks = [evaluator.evaluate(sim_board, h) for h in opp_hands]
            if all(my_rank < r for r in opp_ranks): wins += 1
            elif my_rank == min(opp_ranks): ties += 0.5
        except: continue
    return round((wins + ties) / n * 100)

def get_flush_name(hole, board):
    all_cards = hole + board
    suit_counts = {'s':[],'h':[],'d':[],'c':[]}
    for c in all_cards:
        cs = Card.int_to_str(c)[-1]
        suit_counts[cs].append(Card.get_rank_int(c))
    for s, ranks in suit_counts.items():
        if len(ranks) >= 5:
            sym = suit_names.get(s, s)
            hole_ranks = [Card.get_rank_int(c) for c in hole if Card.int_to_str(c)[-1] == s]
            board_ranks = [Card.get_rank_int(c) for c in board if Card.int_to_str(c)[-1] == s]
            if not hole_ranks: return "Flush"
            my_best = max(hole_ranks)
            ace_rank = 12
            king_rank = 11
            # Nuts: I have the ace, or ace is on board and I have the king
            if my_best == ace_rank:
                return f"Ass-High Flush ({sym}) — Nuts"
            if ace_rank in board_ranks and my_best == king_rank:
                return f"König-High Flush ({sym}) — Nuts"
            # Normal: named by MY highest card
            hc = rank_chars[my_best]
            return f"{rank_names.get(hc,hc)}-High Flush ({sym})"
    return "Flush"

def get_pair_type(hole, board):
    hv = sorted([card_val(c) for c in hole], reverse=True)
    bv = sorted([card_val(c) for c in board], reverse=True)
    if hv[0] == hv[1]:
        return "Overpair" if hv[0] > bv[0] else "Pair"
    pv = next((v for v in hv if v in bv), None)
    if pv is None: return "Pair"
    if pv == bv[0]: return "Top Pair"
    elif len(bv) > 1 and pv == bv[1]: return "Middle Pair"
    else: return "Bottom Pair"

def detect_draws(hole, board):
    all_cards = hole + board
    draws = []
    suit_counts = {'s':[],'h':[],'d':[],'c':[]}
    for c in all_cards:
        cs = Card.int_to_str(c)[-1]
        suit_counts[cs].append(Card.get_rank_int(c))
    for s, ranks in suit_counts.items():
        if len(ranks) == 4:
            hole_ranks = [Card.get_rank_int(c) for c in hole if Card.int_to_str(c)[-1] == s]
            board_ranks = [Card.get_rank_int(c) for c in board if Card.int_to_str(c)[-1] == s]
            is_nut = (12 in hole_ranks) or (12 in board_ranks and 11 in hole_ranks)
            my_best = rank_chars[max(hole_ranks)] if hole_ranks else '?'
            sym = suit_names.get(s, s)
            draws.append("Nut Flush Draw (" + sym + ")" if is_nut else f"Flush Draw ({my_best}{sym})")
    vals = sorted(set([Card.get_rank_int(c) for c in all_cards]))
    consec = max_c = 1
    for i in range(1, len(vals)):
        if vals[i] == vals[i-1]+1: consec += 1; max_c = max(max_c, consec)
        else: consec = 1
    if max_c >= 4: draws.append("OESD (Open Ended Straight Draw)")
    elif max_c == 3: draws.append("Gutshot Straight Draw")
    return list(dict.fromkeys(draws))

def win_pct_to_strength(pct):
    if pct >= 80: return "Sehr Stark"
    if pct >= 60: return "Stark"
    if pct >= 40: return "Mittel"
    if pct >= 20: return "Schwach"
    return "Sehr Schwach"

def get_hand_name(hole, board):
    if len(hole) != 2 or len(board) < 3: return "Preflop Starthand"
    try:
        rank = evaluator.evaluate(board, hole)
        rc = evaluator.get_rank_class(rank)
        raw = evaluator.class_to_string(rc)
        if raw in ["Royal Flush", "Straight Flush"]: return raw
        if raw == "Flush": return get_flush_name(hole, board)
        if raw == "Pair": return get_pair_type(hole, board)
        return raw
    except: return "Unbekannt"

def recommend_action(win_pct):
    if win_pct >= 60: return "Raise", "Starke Hand — Value Bet"
    if win_pct >= 45: return "Call", "Mittlere Hand — Pot Odds ok"
    if win_pct >= 35: return "Check", "Schwache Hand — abwarten"
    return "Fold", "Zu schwach — aufgeben"

def make_analysis(hand_name, win_pct, opponents, board_stage):
    if "Royal Flush" in hand_name: desc = "Du hast einen Royal Flush — die beste Hand überhaupt!"
    elif "Straight Flush" in hand_name: desc = "Du hast einen Straight Flush."
    elif "Four of a Kind" in hand_name: desc = "Du hast Four of a Kind."
    elif "Full House" in hand_name: desc = "Du hast ein Full House."
    elif "Flush" in hand_name and "Draw" not in hand_name: desc = f"Du hast einen {hand_name}."
    elif "Straight" in hand_name and "Draw" not in hand_name: desc = "Du hast eine Straße."
    elif "Three of a Kind" in hand_name: desc = "Du hast einen Drilling."
    elif "Two Pair" in hand_name: desc = "Du hast Two Pair."
    elif "Overpair" in hand_name: desc = "Du hast ein Overpair."
    elif "Top Pair" in hand_name: desc = "Du hast Top Pair."
    elif "Middle Pair" in hand_name: desc = "Du hast Middle Pair."
    elif "Bottom Pair" in hand_name: desc = "Du hast Bottom Pair."
    elif "Nut Flush Draw" in hand_name: desc = f"Du hast den {hand_name}."
    elif "Flush Draw" in hand_name: desc = f"Du hast einen {hand_name}."
    elif "OESD" in hand_name: desc = "Du hast einen Open Ended Straight Draw — 8 Outs."
    elif "Gutshot" in hand_name: desc = "Du hast einen Gutshot Straight Draw — 4 Outs."
    elif "Preflop" in hand_name: desc = "Preflop Analyse."
    else: desc = f"Du hast {hand_name}."

    if win_pct >= 90: assess = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du klarer Favorit."
    elif win_pct >= 75: assess = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner hast du eine starke Hand."
    elif win_pct >= 60: assess = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du Favorit."
    elif win_pct >= 45: assess = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner ist die Situation ausgeglichen."
    elif win_pct >= 30: assess = f"Mit {win_pct}% Gewinnchance gegen {opponents} Gegner bist du Außenseiter."
    else: assess = f"Mit nur {win_pct}% Gewinnchance gegen {opponents} Gegner — fold empfohlen."

    stage_map = {"Preflop":"Preflop.", "Flop":"Noch Turn und River kommen.", "Turn":"Noch eine Karte — der River.", "River":"Alle Karten liegen."}
    stage = stage_map.get(board_stage, "")
    return f"{desc} {assess} {stage}".strip()

IMAGE_PROMPT = """Du bist ein Poker-Kartenscanner für Texas Hold'em.

Analysiere das Bild in diesen Schritten — denke laut nach, dann gib JSON aus:

SCHRITT 1 — PHYSISCHE KARTEN ZÄHLEN:
Wie viele einzelne Karten siehst du insgesamt?
- Vorne unten (nah zur Kamera) = meine HOLE CARDS (immer genau 2)
- Mitte/hinten = BOARD Karten (3, 4 oder 5)
- Jede Karte NUR EINMAL zählen!
- Kleine gedrehte Kopie unten rechts auf jeder Karte = IGNORIEREN (gleiche Karte)

SCHRITT 2 — JEDE KARTE EINZELN BESTIMMEN:
Für jede Karte:
a) Welcher WERT? (Schaue auf die große Zahl/Buchstabe oben links)
   A=Ass, K=König, Q=Dame, J=Bube, T=10, 9,8,7,6,5,4,3,2
b) Welche FARBE? Schaue auf das Symbol:
   ♥ Herz = ROT (Herzform)
   ♦ Karo = ROT (Raute/Diamant)  
   ♠ Pik = SCHWARZ (Spaten, oben spitz zulaufend)
   ♣ Kreuz = SCHWARZ (Kleeblatt, 3 runde Kreise)
c) WICHTIG: Ist das Symbol ROT oder SCHWARZ? ROT=♥♦, SCHWARZ=♠♣ — niemals verwechseln!

SCHRITT 3 — SELBST-KONTROLLE:
- Habe ich genau 2 Hole Cards? (nicht mehr, nicht weniger)
- Sind alle roten Symbole als ♥ oder ♦ eingetragen?
- Sind alle schwarzen Symbole als ♠ oder ♣ eingetragen?
- Habe ich die kleine gedrehte Zahl als extra Karte gezählt? → Fehler korrigieren!

SCHRITT 4 — GEGNER:
Verdeckte Karten (Kartenrücken) = Gegner zählen, minimum 1

Antworte NUR als JSON:
{"myHand":"K♠ 2♥","board":"T♠ 3♠ J♠","opponents":2,"confidence":"sicher"}"""

class Override(BaseModel):
    myHand: str = ""
    board: str = ""
    opponents: int = 1
    boardStage: str = "Preflop"

class ImageRequest(BaseModel):
    image: str = ""
    override: Optional[Override] = None

@app.post("/analyze")
async def analyze(req: ImageRequest):
    # CASE 1: Manual override (Neu Berechnen)
    if req.override and req.override.myHand:
        my_hand_str = req.override.myHand
        board_str = req.override.board
        opponents = req.override.opponents
        board_stage = req.override.boardStage

        hole_cards = parse_cards(my_hand_str)
        board_cards = parse_cards(board_str)

        if len(hole_cards) != 2:
            return {"error": "Hole Cards ungültig", "myHand": my_hand_str, "board": board_str,
                    "opponents": opponents, "winPct": 0, "handStrength": "—", "handName": "—",
                    "action": "—", "actionReason": "—", "sizing": "", "boardTexture": "",
                    "opponentRanges": "", "analysis": "Hole Cards konnten nicht gelesen werden.", "whatISee": ""}

        hand_name = get_hand_name(hole_cards, board_cards)

        # Draw detection for weak hands
        if len(board_cards) >= 3 and hand_name in ["High Card", "Pair", "Unbekannt"]:
            draws = detect_draws(hole_cards, board_cards)
            if draws:
                hand_name = " + ".join(draws)

        sim_n = 3000 if len(board_cards) >= 3 else 2000
        win_pct = simulate_win(hole_cards, board_cards, opponents, sim_n)
        hand_strength = win_pct_to_strength(win_pct)
        action, action_reason = recommend_action(win_pct)
        analysis = make_analysis(hand_name, win_pct, opponents, board_stage)

        return {
            "myHand": my_hand_str, "board": board_str, "boardStage": board_stage,
            "opponents": opponents, "winPct": win_pct, "handStrength": hand_strength,
            "handName": hand_name, "action": action, "actionReason": action_reason,
            "sizing": "", "boardTexture": "", "opponentRanges": "",
            "analysis": analysis, "whatISee": ""
        }

    # CASE 2: Image scan
    if not req.image or req.image in ['', 'ping']:
        return {"error": "Kein Bild", "myHand": "", "board": "", "opponents": 1,
                "winPct": 0, "handStrength": "—", "handName": "—", "action": "—",
                "actionReason": "—", "sizing": "", "boardTexture": "", "opponentRanges": "",
                "analysis": "Bitte Foto machen.", "whatISee": ""}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-opus-4-5", "max_tokens": 300,
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": req.image}},
                      {"type": "text", "text": IMAGE_PROMPT}
                  ]}]}
        )

    resp_data = resp.json()
    raw = resp_data.get("content", [{}])[0].get("text", "") if resp_data.get("content") else ""
    if not raw:
        return {"error": f"Leere Antwort: {json.dumps(resp_data)[:200]}", "myHand": "Nicht erkennbar",
                "board": "", "opponents": 1, "winPct": 0, "handStrength": "—", "handName": "—",
                "action": "—", "actionReason": "—", "sizing": "", "boardTexture": "",
                "opponentRanges": "", "analysis": "Fehler beim Scan.", "whatISee": ""}

    try:
        clean = raw.replace("```json","").replace("```","").strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        card_data = json.loads(match.group(0) if match else clean)
    except:
        return {"error": "Parse error", "raw": raw, "myHand": "Nicht erkennbar", "board": "",
                "opponents": 1, "winPct": 0, "handStrength": "—", "handName": "—",
                "action": "—", "actionReason": "—", "sizing": "", "boardTexture": "",
                "opponentRanges": "", "analysis": raw[:200], "whatISee": ""}

    my_hand_str = card_data.get("myHand", "")
    board_str = card_data.get("board", "")
    opponents = int(card_data.get("opponents", 1))

    hole_cards = parse_cards(my_hand_str)
    board_cards = parse_cards(board_str)
    board_stage = {0:"Preflop",3:"Flop",4:"Turn",5:"River"}.get(len(board_cards),"Preflop")

    hand_name = get_hand_name(hole_cards, board_cards)

    if len(board_cards) >= 3 and hand_name in ["High Card", "Pair", "Unbekannt"]:
        draws = detect_draws(hole_cards, board_cards)
        if draws:
            hand_name = " + ".join(draws)

    sim_n = 3000 if len(board_cards) >= 3 else 2000
    win_pct = simulate_win(hole_cards, board_cards, opponents, sim_n) if len(hole_cards) == 2 else 0
    hand_strength = win_pct_to_strength(win_pct) if win_pct > 0 else "—"
    action, action_reason = recommend_action(win_pct)
    analysis = make_analysis(hand_name, win_pct, opponents, board_stage)

    return {
        "myHand": my_hand_str, "board": board_str, "boardStage": board_stage,
        "opponents": opponents, "winPct": win_pct, "handStrength": hand_strength,
        "handName": hand_name, "action": action, "actionReason": action_reason,
        "sizing": "", "boardTexture": "", "opponentRanges": "",
        "analysis": analysis, "whatISee": ""
    }

@app.get("/")
def root():
    return {"status": "Poker AI Backend online"}
