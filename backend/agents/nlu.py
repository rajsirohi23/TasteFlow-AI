"""Rule-based language understanding for the Supervisor Agent.

Deterministic and testable: the same sentence always gives the same intent.
It understands English plus common Hinglish (haan, nahi, hatao, kam teekha ...).
An optional LLM parser (agents/nlu_llm.py) can run first when an API key is set;
this module is always the validated fallback.
"""
import re

from agents.supervisor_agent import extract_menu_preferences

NUM_WORDS = {
    "one": 1, "ek": 1, "two": 2, "three": 3, "teen": 3, "four": 4, "char": 4,
    "chaar": 4, "five": 5, "paanch": 5, "panch": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
ORDINALS = {
    "first": 1, "1st": 1, "pehla": 1, "pehle": 1, "second": 2, "2nd": 2, "dusra": 2,
    "third": 3, "3rd": 3, "teesra": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5,
}
YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
             "correct", "haan", "ha", "han", "haanji", "theek", "thik", "bilkul",
             "absolutely", "proceed", "please"}
YES_PHRASES = ("go ahead", "place it", "do it", "looks good", "that's right", "thats right",
               "kar do", "theek hai", "thik hai", "yes please")
NO_WORDS = {"no", "nope", "nah", "nahi", "nahin", "cancel", "stop", "mat", "ruko", "wait"}
NO_PHRASES = ("don't", "dont", "do not", "not now", "not yet", "no thanks", "mat karo",
              "rehne do", "never mind", "nevermind")
MODIFY_WORDS = ("add", "remove", "delete", "change", "make", "actually", "instead", "hatao",
                "replace", "update", "edit")


HI_PHRASES = [  # longer phrases first
    ("ऑर्डर कर दो", "place my order"), ("ऑर्डर करो", "place my order"), ("ऑर्डर कर दीजिए", "place my order"), ("आर्डर कर दो", "place my order"),
    ("मेरा ऑर्डर कहाँ है", "where is my order"), ("मेरा ऑर्डर कहां है", "where is my order"), ("ऑर्डर कहाँ है", "where is my order"),
    ("कितना समय लगेगा", "how long"), ("कितनी देर", "how long"), ("कितना टाइम", "how long"), ("कार्ट दिखाओ", "show cart"),
    ("मेन्यू दिखाओ", "show menu"), ("मेनू दिखाओ", "show menu"), ("ऑर्डर रद्द करो", "cancel my order"), ("रसोई कितनी व्यस्त है", "how busy is the kitchen"),
    ("कम तीखा", "not too spicy"), ("कम मसालेदार", "not too spicy"), ("बिना मसाले", "no spice"), ("दो प्लेट", "two"), ("दो पीस", "two"),
]
HI_WORDS = {
    "हाँ": "yes", "हां": "yes", "जी": "yes", "ठीक": "yes", "ओके": "yes", "हाँजी": "yes", "बिल्कुल": "yes", "नहीं": "no", "नही": "no", "मत": "no",
    "शाकाहारी": "vegetarian", "वेज": "vegetarian", "वीगन": "vegan", "मसालेदार": "spicy", "तीखा": "spicy", "पनीर": "paneer", "चिकन": "chicken",
    "पिज़्ज़ा": "pizza", "पिज्जा": "pizza", "बिरयानी": "biryani", "दाल": "dal", "खाना": "food", "मिठाई": "dessert", "पेय": "drinks", "ड्रिंक": "drinks",
    "हटाओ": "remove", "जोड़ो": "add", "जोड़": "add", "डालो": "add", "पहला": "first", "दूसरा": "second", "तीसरा": "third", "एक": "one", "तीन": "three",
    "चार": "four", "पाँच": "five", "सुझाओ": "recommend", "दिखाओ": "show", "बताओ": "show", "सस्ता": "cheaper", "रुपये": "", "रुपए": "", "मुझे": "", "चाहिए": "",
    "ऑर्डर": "order", "आर्डर": "order", "टेबल": "table", "नमस्ते": "hello", "धन्यवाद": "thanks", "लो": "add", "लीजिए": "add",
}
_DEVANAGARI = re.compile("[\u0900-\u097F]")


def normalize_hindi(text: str) -> str:
    """Map common Devanagari Hindi words/phrases and digits onto the English tokens the rules understand."""
    if not _DEVANAGARI.search(text):
        return text
    text = text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    for hi, en in HI_PHRASES:
        text = text.replace(hi, f" {en} ")
    text = re.sub(r"(\d+)\s*(?:से कम|के अंदर|के नीचे|तक|में)", r" under \1 ", text)
    out = []
    for w in re.split(r"[\s,।?!.]+", text):
        if w:
            out.append(HI_WORDS.get(w, w))
    return " ".join(x for x in out if x)


def _norm(text: str) -> str:
    text = normalize_hindi(text)
    return " ".join(text.lower().replace("’", "'").strip().split())


def _has_word(text: str, words) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _quantity(text: str) -> int | None:
    m = re.search(r"\b(\d{1,2})\b", text)
    if m and 0 < int(m.group(1)) <= 50:
        return int(m.group(1))
    for word, n in NUM_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    if re.search(r"\bdo\s+(?:plate|plates|piece|pieces|portion)", text):
        return 2
    return None


def _ordinal(text: str) -> int | None:
    for word, n in ORDINALS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return n
    m = re.search(r"(?:number|no\.?|option|item|#)\s*(\d)\b", text)
    return int(m.group(1)) if m else None


def match_dish_names(text: str, menu: list[dict]) -> list[int]:
    """Menu item ids whose name (or all its significant words) appear in text."""
    tokens = set(re.findall(r"[a-z]+", text))
    hits: list[tuple[int, int]] = []
    for item in menu:
        name = item["name"].lower()
        words = [w for w in re.findall(r"[a-z]+", name) if len(w) > 2]
        if name in text or (words and all(w in tokens for w in words)):
            hits.append((len(name), item["id"]))
    hits.sort(reverse=True)
    return [i for _, i in hits]


def parse_message(text: str, state: dict, menu: list[dict], vocab: set[str]) -> dict:
    """Return {"intent": ..., entities...} for one customer message."""
    t = _norm(text)
    pending = (state.get("pending") or {}).get("type")
    result: dict = {"intent": "general", "text": t}

    if not t:
        return {**result, "intent": "empty"}

    modifies = _has_word(t, MODIFY_WORDS)

    # ---- 1. Answers to a question we just asked -------------------------
    if pending == "ask_name" and not modifies and not _has_word(t, NO_WORDS):
        return {**result, "intent": "provide_name"}
    if pending == "choose_item" and not modifies:
        ordinal, named = _ordinal(t), match_dish_names(t, menu)
        if ordinal or named:
            return {**result, "intent": "add_item", "quantity": None, "item_ids": named, "ordinal": ordinal}
    if pending in ("confirm_order", "offer_item", "confirm_cancel"):
        new_request = bool(re.search(r"\b(show|recommend|suggest|something|want|need|looking|options|mains|starters|desserts|drinks|bowls)\b", t)) \
            or len(t.split()) > 6
        is_note = bool(re.match(r"^(please )?(note|notes|special instructions?|instructions?)\b", t))  # "note: no onion" is not a refusal
        is_no = (_has_word(t, NO_WORDS) or any(p in t for p in NO_PHRASES)) and not new_request and not is_note
        is_yes = (_has_word(t, YES_WORDS) or any(p in t for p in YES_PHRASES))
        if is_no:
            return {**result, "intent": "decline"}
        if is_yes and not new_request and not is_note and not (modifies and not re.search(r"\badd it\b|\badd that\b", t)):
            return {**result, "intent": "confirm_yes"}

    # ---- 2. Changing mind / resetting -----------------------------------
    if re.search(r"\b(actually|wait)\b.*\b(change|modify|edit|update)\b.*\border\b|\bchange my order\b|\bmodify my order\b", t):
        return {**result, "intent": "modify_order"}
    if re.search(r"\b(reset|start over|forget|clear)\b.*\b(preference|preferences|filters|everything)\b|\bstart over\b|\breset\b", t):
        return {**result, "intent": "reset_prefs"}
    if re.search(r"\b(clear|empty)\b.*\bcart\b|\bcart\b.*\b(clear|empty)\b", t):
        return {**result, "intent": "clear_cart"}

    # ---- 3. Decline / cancel (nothing pending) --------------------------
    if re.search(r"(don't|dont|do not|not)\s+(place|order|confirm)|\bno\b.*\b(order|place)\b", t):
        return {**result, "intent": "decline"}
    if re.search(r"\bcancel (my |the |this )?order\b", t):
        return {**result, "intent": "cancel_order"}

    # ---- 3b. Order details: dine-in / takeaway / table / notes -----------------
    note = re.match(r"^(?:please )?(?:note|notes|special instruction|instruction|instructions)\s*[:\-]?\s*(.{3,200})$", t)
    if note:
        return {**result, "intent": "add_note", "note": note.group(1)}
    if re.search(r"\b(dine[\s-]?in|eat here|take[\s-]?away|parcel|pick[\s-]?up)\b|\btable\s*#?\s*\d{1,3}\b", t) \
            and not re.search(r"\b(place|checkout|confirm|remove|add)\b", t):
        tm = re.search(r"\btable\s*#?\s*(\d{1,3})", t)
        otype = "takeaway" if re.search(r"take[\s-]?away|parcel|pick[\s-]?up", t) else "dine_in"
        return {**result, "intent": "set_order_type", "order_type": otype, "table_number": tm.group(1) if tm else None}
    if re.search(r"\b(same again|order again|reorder|re-order|repeat (my |the )?(last )?order|same as (last time|before)|phir se wahi)\b", t):
        return {**result, "intent": "reorder"}

    # ---- 3c. Feedback (guest) and staff views -------------------------------
    if re.search(r"\b(show|view|see|latest|recent|customer|guest|all)\b.*\b(feedback|reviews?|ratings?)\b", t):
        return {**result, "intent": "feedback_summary"}
    stars = re.search(r"\b([1-5])\s*(?:/\s*5|stars?)\b", t) or re.search(r"\b(?:rate|rating|rated)\b\D{0,15}\b([1-5])\b", t)
    if stars and re.search(r"\b(rate|rating|rated|stars?|feedback|review)\b", t):
        comment = re.sub(r"\b(i\s+)?(rate|rated|rating|give|gave)\b|\b[1-5]\s*(/\s*5|stars?)\b|\bfeedback\b|[:,]", " ", t)
        return {**result, "intent": "give_feedback", "rating": int(stars.group(1)), "comment": " ".join(comment.split())}
    if re.search(r"\b(inventory|in stock|out of stock|running (low|out)|low (on )?stock|stock level|sold out)\b", t):
        return {**result, "intent": "inventory"}

    # ---- 4. Questions about the kitchen / my order ----------------------
    if re.search(r"\b(how long|how many minutes|how much longer|time left|eta|when will|kitni der|kitna time|ready yet)\b", t) \
            and state.get("last_order_id") and "kitchen" not in t:
        return {**result, "intent": "order_status"}
    if re.search(r"\b(how long|wait time|waiting|how busy|busy|ready in|kitni der|kitna time)\b", t):
        return {**result, "intent": "kitchen_status"}
    if re.search(r"\b(order status|where is my order|track|my order status|status of my order)\b", t):
        return {**result, "intent": "order_status"}

    # ---- 5. Staff analytics ---------------------------------------------
    if re.search(r"\b(sales|revenue|analytics|insight|insights|unmet|low demand|best selling|top selling|business|performance|report|how many orders|top dishes?|busiest|peak hour|average order|compare|worst sellers?|never sell|slowest)\b", t):
        return {**result, "intent": "analytics"}

    # ---- 6. Checkout / cart view -----------------------------------------
    if re.search(r"\b(place (the |my |this )?order|checkout|check out|confirm (my |the )?order|that'?s all|i'?m done|order now|bas itna|done ordering)\b", t):
        return {**result, "intent": "checkout"}
    if re.search(r"\b(my cart|show (me )?(the |my )?cart|what'?s in my cart|order summary|view cart|cart mein)\b", t):
        return {**result, "intent": "show_cart"}

    qty = _quantity(t)
    ordinal = _ordinal(t)
    named = match_dish_names(t, menu)

    # ---- 7. Cart edits ----------------------------------------------------
    if re.search(r"\b(remove|delete|hatao|hata do|take out|drop)\b", t):
        return {**result, "intent": "remove_item", "item_ids": named, "ordinal": ordinal,
                "last": bool(re.search(r"\blast\b|\bpichla\b", t))}
    if re.search(r"\b(make it|change (it |the )?(quantity|qty)|set (it )?to|instead)\b", t) and qty and (named or state.get("cart")):
        return {**result, "intent": "set_quantity", "quantity": qty, "item_ids": named,
                "last": True}
    if re.search(r"\b(add|i'?ll take|i will take|i'?ll have|i will have|get me|give me|i want to order|order|le lo|dal do|daal do|add kar do)\b", t) or re.fullmatch(r"(add )?(it|that|this one)( please)?", t):
        return {**result, "intent": "add_item", "quantity": qty, "item_ids": named,
                "ordinal": ordinal, "wants_all": bool(re.search(r"\b(both|all of them|all)\b", t))}

    # ---- 8. Greetings / help ----------------------------------------------
    if re.fullmatch(r"(hi|hello|hey|hii|namaste|namaskar|good (morning|afternoon|evening))[ !.]*", t):
        return {**result, "intent": "greet"}
    if re.search(r"\b(help|what can you do|how does this work)\b", t):
        return {**result, "intent": "help"}

    # ---- 9. Menu discovery ---------------------------------------------------
    prefs = extract_menu_preferences(t)
    prefs.pop("limit", None)
    if "budget" not in prefs:  # Hinglish: "300 ke andar", "200 tak"
        hm = re.search(r"(\d{2,5})\s*(?:rupees|rupaye|rs\.?|₹)?\s*(?:ke andar|ke neeche|tak|se kam|mein)\b", t)
        if hm:
            prefs["budget"] = int(hm.group(1))
    exclusions = _exclusions(t, vocab)
    wants_other = bool(re.search(r"\b(another|something else|other options|different|more options|else)\b", t))
    cheaper = bool(re.search(r"\b(cheaper|less expensive|lower price|sasta|budget friendly)\b", t))
    discovery_words = re.search(
        r"\b(recommend|suggest|show|what|something|hungry|food|meal|dish|dishes|menu|eat|craving|"
        r"lunch|dinner|breakfast|snack|khana|bhookh|chahiye|options|any)\b", t)
    if prefs or exclusions or wants_other or cheaper or discovery_words:
        return {**result, "intent": "recommend", "prefs": prefs, "exclusions": exclusions,
                "wants_other": wants_other, "cheaper": cheaper,
                "allergy": bool(re.search(r"\ballerg", t)),
                "relative_spice": bool(re.search(r"\bmake it\b", t))}

    # A bare dish name: describe it and offer to add.
    if named:
        return {**result, "intent": "show_item", "item_ids": named[:1]}

    if _has_word(t, YES_WORDS) and len(t.split()) <= 3:
        return {**result, "intent": "yes_no_context"}
    if _has_word(t, NO_WORDS) and len(t.split()) <= 3:
        return {**result, "intent": "decline"}
    return result


def _exclusions(text: str, vocab: set[str]) -> list[str]:
    found = []
    for m in re.finditer(r"\b(?:no|without|avoid|except|hold the|allergic to|allergy to|bina)\s+([a-z]+)", text):
        word = m.group(1)
        singular = word[:-1] if word.endswith("s") else word
        if word in ("spice", "spicy", "hot", "teekha", "mirch", "order", "thanks", "worries"):
            continue
        for candidate in (word, singular):
            if candidate in vocab:
                found.append(candidate)
                break
    return found
