"""Router luật cho chatbot Smart Home: xử lý lệnh phổ biến KHÔNG cần LLM.

route(text, ctx) trả (kind, payload). Lệnh control có thể kèm "level" (1..3) cho quạt bật:
    {"room": "bedroom", "device": "fan", "state": "ON", "level": 2}
route(text, ctx) trả (kind, payload):
    guide_gas | summary | risk | comfort | refuse | smalltalk | control | control_confirm | ask_room | status | history | security | away | llm
ctx là ngữ cảnh câu trước (do Core giữ, tự hết hạn), dùng cho "tắt nó đi", "còn phòng ngủ thì sao".
"""
import re
import unicodedata
from datetime import datetime, timedelta

ROOMS = {"phong khach": "living_room", "phong ngu": "bedroom", "bep": "kitchen"}
ALL_ROOMS = list(ROOMS.values())
DEVS = {"den": "led", "quat": "fan"}
DEV_VI = {"led": "đèn", "fan": "quạt"}
BLOCK = ("cua", "khoa", "coi", "bao dong", "nguong", "bo qua", "quy tac")
METRICS = [("nhiet do", "temp"), ("do am", "humid"), ("gas", "gas_raw"), ("anh sang", "light")]
AGGS = [("cao nhat", "max"), ("thap nhat", "min"), ("trung binh", "avg")]
QUERY_RE = re.compile(r"dang (bat|tat|nong|lanh)|hay tat|bao nhieu|the nao|sao roi|co ai|ro gas|co .*khong$|tinh hinh")
HISTORY_RE = re.compile(r"cao nhat|thap nhat|trung binh|\d+ (gio|phut) qua|hom nay")
# Câu hỏi trạng thái không có động từ điều khiển: "nhiệt độ phòng khách", "kiểm tra phòng ngủ"...
STATUS_RE = re.compile(r"trang thai|tinh trang|kiem tra|nhiet do|do am|anh sang|\bgas\b|nong|lanh|chuyen dong")
CONTROL_RE = re.compile(r"\b(bat|mo|tat)\b")
# "tắt hết thiết bị phòng ngủ", "bật tất cả đồ điện bếp": không nêu đèn/quạt -> mọi thiết bị của phòng
ALL_DEV_RE = re.compile(r"\b(het|tat ca|toan bo|moi thu|thiet bi|do dien)\b")
ALL_HOUSE_RE = re.compile(r"\b(ca nha|het|toan bo|tat ca|moi phong|cac phong)\b")

# ---- mức quạt: "quạt mức 2", "bật quạt số 3", "quạt 1", "quạt mạnh nhất" ----
_LEVEL_NUM = {"1": 1, "2": 2, "3": 3, "mot": 1, "hai": 2, "ba": 3}
LEVEL_RE = re.compile(r"\b(?:muc|so|cap|toc do)\s*(1|2|3|mot|hai|ba)\b|\bquat\s+(1|2|3)\b")
LEVEL_NAMED = [(re.compile(r"manh nhat|toi da|\bmax\b|(muc|che do|gio) manh"), 3),
               (re.compile(r"(muc|che do|gio) (vua|trung binh)"), 2),
               (re.compile(r"nhe nhat|yeu nhat|cham nhat|(muc|che do|gio) (nhe|yeu|cham)"), 1)]
# Trả lời câu "quạt bật mức mấy?"
LEVEL_ONLY_RE = re.compile(r"^(?:muc |so |cap )?(1|2|3|mot|hai|ba)(?: (?:nhe|nha|di|a|thoi))*$")
YES_RE = re.compile(r"^(u+|uh+|um+|ok|oke|okay|dong y|duoc|co|vang|da|chuan|dung roi|theo goi y|nhu goi y|goi y"
                    r"|bat di|lam di|bat luon|lam luon)(?: (?:di|nhe|nha|luon|vay|a))*$")
NO_RE = re.compile(r"^(thoi|khong|ko|huy|khoi|dung|khong can|khong bat)(?: (?:di|nhe|nha|nua|bat|a))*$")

# ---- chế độ vắng nhà ----
AWAY_ON_RE = re.compile(r"(bat|kich hoat|mo) (che do )?vang nha|toi (se )?(ra khoi nha|di vang|di lam|ra ngoai|di choi)"
                        r"|^(ra khoi nha|di vang)$|nha khong co ai")
AWAY_OFF_RE = re.compile(r"(tat|huy|ket thuc) (che do )?vang nha|toi (da )?ve( nha)?( roi)?$|^(da )?ve nha( roi)?$"
                         r"|toi o nha")
AWAY_Q_RE = re.compile(r"(che do )?vang nha")

# ---- hỏi lịch sử an ninh (chỉ ĐỌC dữ liệu, không điều khiển gì -> kiểm tra trước BLOCK cũng an toàn) ----
SEC_QUESTION_RE = re.compile(r"\bai\b|khi nao|luc nao|may gio|lan cuoi|bao nhieu lan|lich su|nhat ky|co ai"
                             r"|co nguoi la|nguoi la|co gi moi|co gi la|thong bao")
TIME_RE = re.compile(r"hom nay|sang nay|chieu nay|toi nay|dem qua|hom qua|tuan nay|\d+ (gio|phut) qua"
                     r"|lan cuoi|khi nao|luc nao|may gio|bao nhieu lan")
SEC_DOOR_RE = re.compile(r"\bcua\b|ve nha|vao nha|mo khoa|\bden\b nha|ai (da )?(vao|ve|den|mo)")
SEC_STRANGER_RE = re.compile(r"nguoi la|la mat|khong quen")
SEC_GAS_RE = re.compile(r"(canh bao|ro|bao) gas|\bgas\b")
SEC_MOTION_RE = re.compile(r"chuyen dong|co nguoi|co ai")
SEC_ALL_RE = re.compile(r"co gi moi|co gi la|thong bao|tinh hinh an ninh|an ninh")

# ---- sự cố gas, mức nguy hiểm, tóm tắt ----
GUIDE_GAS_RE = re.compile(r"(ro gas|mui gas|\bgas\b).*(lam gi|lam sao|xu ly|phai lam|nen lam|the nao)"
                          r"|(lam gi|xu ly|phai lam sao).*(ro gas|\bgas\b)")
RISK_RE = re.compile(r"(co )?an toan khong|nguy hiem khong|muc (do )?(nguy hiem|canh bao|rui ro)|co on khong|co van de gi")
SUMMARY_RE = re.compile(r"tom tat|tong ket|bao cao|(?<!ca )nha (hom nay |hom qua )?(the nao|sao roi|ra sao)"
                        r"|hom (nay|qua) (o )?nha (the nao|ra sao|sao roi|co gi)")

# ---- câu than phiền -> đề xuất bật/tắt (luôn hỏi xác nhận) ----
# Lưu ý: bỏ dấu thì "tôi" và "tối" đều là "toi" -> chỉ nhận "toi" khi đi cùng từ chỉ mức độ.
COMFORT = [
    (re.compile(r"\b(hoi|qua|bi|kha|rat|that|toi thui|toi om|toi tham|toi qua|toi vay|toi the)\b toi\b|\btoi (qua|thui|om|tham|vay|the)\b"
                r"|thieu (anh )?sang|khong du sang|khong thay (gi|duong)|(can|muon) (them )?(anh )?sang"),
     "led", "ON", "đang tối"),
    (re.compile(r"choi (mat|qua)|sang qua|qua sang|nhuc mat|muon ngu"), "led", "OFF", "đang sáng quá"),
    (re.compile(r"nong (qua|nuc|vay|the|buc)|hoi nong|\bnong\b$|ngot ngat|oi (buc|qua)|nuc qua|bi bach|toat (ca )?mo hoi"),
     "fan", "ON", "đang nóng"),
    (re.compile(r"lanh (qua|vay|the|run)|hoi lanh|\blanh\b$|ret qua"), "fan", "OFF", "đang lạnh"),
]

# Câu xã giao: trả lời cố định, không gọi LLM
SMALLTALK = [
    (re.compile(r"^(xin )?chao( ban)?( bot)?$|^hello$|^hi$|^alo$"),
     "Xin chào! Mình có thể bật/tắt đèn, quạt, báo trạng thái các phòng và cho biết ai đã ra vào nhà."),
    (re.compile(r"cam on|thank"), "Không có gì, bạn cần gì cứ nhắn mình nhé!"),
    (re.compile(r"ban (la ai|lam duoc gi)|giup (gi|duoc gi)|huong dan|help"),
     "Bạn có thể nói: \"bật đèn phòng khách\", \"bật quạt phòng ngủ mức 2\", \"tắt hết thiết bị bếp\", "
     "\"tắt nó đi\", \"nhiệt độ bếp\", \"trạng thái cả nhà\", "
     "\"hôm nay ai mở cửa?\", \"có người lạ không?\", \"bật chế độ vắng nhà\", \"nhà có an toàn không?\", "
     "\"tóm tắt hôm nay\", \"rò gas phải làm gì?\"."),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"\s+", " ", s).strip()


def _word(w, t):
    return re.search(rf"\b{w}\b", t) is not None


def _room(t):
    # Tên phòng cụ thể thắng chữ "hết": "tắt hết đèn phòng ngủ" là phòng ngủ, không phải cả nhà
    for k, v in ROOMS.items():
        if _word(k, t):
            return v
    if ALL_HOUSE_RE.search(t):
        return "all"
    return None


def parse_level(t):
    """Mức quạt nêu trong câu (đã chuẩn hóa) -> 1..3 hoặc None."""
    m = LEVEL_RE.search(t)
    if m:
        return _LEVEL_NUM[m.group(1) or m.group(2)]
    for rx, lv in LEVEL_NAMED:
        if rx.search(t):
            return lv
    return None


def level_answer(text):
    """Trả lời câu hỏi mức quạt: 1..3, "yes" (theo gợi ý), "no" (hủy) hoặc None (không phải câu trả lời)."""
    t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", norm(text))).strip()
    m = LEVEL_ONLY_RE.match(t)
    if m:
        return _LEVEL_NUM[m.group(1)]
    if NO_RE.match(t):
        return "no"
    if YES_RE.match(t):
        return "yes"
    # "mức 2 nhé", "bật mức 3", "quạt số 1": có mức, không nêu phòng/đèn -> là câu trả lời.
    # Câu đầy đủ ("bật quạt phòng ngủ mức 2") để router xử lý như lệnh mới.
    lv = parse_level(t)
    if lv and not _room(t) and not _word("den", t):
        return lv
    return None


def _calls(room, devs, state, level=None):
    rooms = ALL_ROOMS if room == "all" else [room]
    out = []
    for d in devs:
        for r in rooms:
            c = {"room": r, "device": d, "state": state}
            if d == "fan" and state == "ON" and level:
                c["level"] = level
            out.append(c)
    return out


def _period(t, now=None):
    """Khoảng thời gian nói trong câu -> (since, until, nhãn tiếng Việt)."""
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.search(r"(\d+) (gio|phut) qua", t)
    if m:
        n = int(m.group(1))
        mins = n * 60 if m.group(2) == "gio" else n
        return (now - timedelta(minutes=mins)).timestamp(), None, f"trong {n} {'giờ' if m.group(2) == 'gio' else 'phút'} qua"
    if "hom qua" in t or "dem qua" in t:
        return (midnight - timedelta(days=1)).timestamp(), midnight.timestamp(), "hôm qua"
    if "sang nay" in t:
        return midnight.timestamp(), midnight.replace(hour=12).timestamp(), "sáng nay"
    if "chieu nay" in t:
        return midnight.replace(hour=12).timestamp(), midnight.replace(hour=18).timestamp(), "chiều nay"
    if "toi nay" in t:
        return midnight.replace(hour=18).timestamp(), None, "tối nay"
    if "tuan nay" in t:
        return (midnight - timedelta(days=now.weekday())).timestamp(), None, "tuần này"
    if "hom nay" in t:
        return midnight.timestamp(), None, "hôm nay"
    return (now - timedelta(days=7)).timestamp(), None, "7 ngày qua"   # "lần cuối", "khi nào"...


def _security(t):
    """Nhận câu hỏi lịch sử an ninh. Trả payload hoặc None."""
    if not SEC_QUESTION_RE.search(t) and not TIME_RE.search(t):
        return None
    if SEC_STRANGER_RE.search(t):
        what = "stranger"
    elif SEC_DOOR_RE.search(t) and SEC_QUESTION_RE.search(t):
        what = "door"
    elif SEC_ALL_RE.search(t):
        what = "all"
    elif SEC_GAS_RE.search(t) and TIME_RE.search(t) and not any(k in t for k, _ in METRICS[:2] + METRICS[3:]):
        if re.search(r"cao nhat|thap nhat|trung binh", t):
            return None                    # "gas cao nhất 2 giờ qua" là câu lịch sử số liệu
        what = "gas"
    elif SEC_MOTION_RE.search(t) and TIME_RE.search(t):
        what = "motion"
    else:
        return None
    since, until, label = _period(t)
    room = _room(t)
    return {"what": what, "room": None if room == "all" else room, "since": since, "until": until,
            "label": label, "last_only": "lan cuoi" in t, "text": t}


def route(text: str, ctx=None):
    t = norm(text)
    t = re.sub(r"[^\w\s,]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    ctx = ctx or {}
    for rx, reply in SMALLTALK:
        if rx.search(t):
            return "smalltalk", reply

    if GUIDE_GAS_RE.search(t):
        return "guide_gas", None
    if SUMMARY_RE.search(t):
        return "summary", {"day": "yesterday" if ("hom qua" in t or "dem qua" in t) else "today"}
    if RISK_RE.search(t):
        return "risk", None

    # Chế độ vắng nhà (trước phần điều khiển vì câu có chữ "bật/tắt" nhưng không có thiết bị)
    if AWAY_OFF_RE.search(t):
        return "away", False
    if AWAY_ON_RE.search(t):
        return "away", True
    if AWAY_Q_RE.search(t):
        return "away", None

    # Hỏi lịch sử an ninh: chỉ đọc dữ liệu nên đặt trước BLOCK ("hôm nay ai mở cửa?" không phải lệnh mở cửa)
    sec = _security(t)
    if sec:
        return "security", sec

    if any(_word(w, t) for w in BLOCK):
        return "refuse", None
    if HISTORY_RE.search(t):
        room = _room(t)
        metric = next((v for k, v in METRICS if k in t), None)
        agg = next((v for k, v in AGGS if k in t), "last")
        m = re.search(r"(\d+) (gio|phut)", t)
        minutes = int(m.group(1)) * (60 if m.group(2) == "gio" else 1) if m else (1440 if "hom nay" in t else None)
        if room and room != "all" and metric and minutes:
            return "history", {"room": room, "metric": metric, "minutes": minutes, "agg": agg}
        return "llm", None
    if not re.search(r"khong$|\bchua$|\bko$", t):        # câu cảm thán, không phải câu hỏi
        for rx, dev, st, why in COMFORT:
            if rx.search(t) and not CONTROL_RE.search(t):
                room = _room(t)
                return "comfort", {"room": None if room == "all" else room, "device": dev, "state": st, "why": why}
    if QUERY_RE.search(t):
        room = _room(t)
        if room:
            return "status", {"room": room}
        if ctx.get("room"):                     # "đang bật không?" -> phòng của câu trước
            return "status", {"room": ctx["room"]}
        return "llm", None

    calls, state, devs_wait = [], None, []   # devs_wait: thiết bị đã nêu nhưng chưa có phòng
    last_devs, last_room = [], None
    sentence_level = parse_level(t)
    level = None
    for clause in re.split(r",| va | roi | voi ", t):
        st = "ON" if re.search(r"\b(bat|mo)\b", clause) else "OFF" if _word("tat", clause) else None
        clause_level = parse_level(clause)
        if not st and clause_level and _word("quat", clause):
            st = "ON"               # "quạt phòng ngủ mức 2" = bật quạt mức 2
        if st and st != state:
            devs_wait = []          # đổi động từ -> bắt đầu nhóm lệnh mới
        state = st or state
        level = clause_level or level or sentence_level
        devs = [v for k, v in DEVS.items() if _word(k, clause)]
        if not devs and st and ALL_DEV_RE.search(clause):
            devs = list(DEVS.values())          # "tắt hết thiết bị ..." -> đèn + quạt
        devs_wait += [d for d in devs if d not in devs_wait]
        room = _room(clause)
        if not room or not state:
            continue
        last_room = room
        use = devs_wait or last_devs
        if not use:
            continue
        for c in _calls(room, use, state, level):
            if c not in calls:
                calls.append(c)
        last_devs, devs_wait = use, []
    if devs_wait and state and last_room:      # "tắt hết đèn và quạt": quạt dùng lại phòng trước
        for c in _calls(last_room, devs_wait, state, level):
            if c not in calls:
                calls.append(c)
    if calls:
        return "control", calls

    # ---------- dùng ngữ cảnh câu trước ----------
    room = _room(t)
    has_status_word = not CONTROL_RE.search(t) and STATUS_RE.search(t)
    if ctx and not has_status_word:
        c_room, c_devs, c_state = ctx.get("room"), ctx.get("devices") or [], ctx.get("state")
        # "tắt nó đi", "bật lại", "mở quạt" (thiếu phòng) -> phòng/thiết bị của câu trước. Có động từ rõ -> làm luôn.
        if state and not room and c_room and (devs_wait or c_devs):
            return "control", _calls(c_room, devs_wait or c_devs, state, sentence_level)
        # "phòng ngủ" (trả lời câu hỏi phòng nào?) -> làm luôn
        if room and not state and ctx.get("kind") == "control" and c_room is None and c_state and c_devs:
            return "control", _calls(room, devs_wait or c_devs, c_state, ctx.get("level"))
        # "còn phòng ngủ thì sao?" sau một lệnh -> có thể là hỏi, nên hỏi xác nhận trước khi làm
        if room and not state and ctx.get("kind") == "control" and c_state and (devs_wait or c_devs):
            return "control_confirm", _calls(room, devs_wait or c_devs, c_state)
        if room and not state and ctx.get("kind") == "status":
            return "status", {"room": room}
        # "cả quạt nữa" -> cùng động từ, cùng phòng
        if devs_wait and not state and not room and ctx.get("kind") == "control" and c_room and c_state:
            return "control", _calls(c_room, devs_wait, c_state)

    if state and devs_wait and not last_room:   # có lệnh nhưng thiếu phòng -> hỏi lại, không cần LLM
        return "ask_room", {"state": state, "devices": devs_wait, "level": sentence_level}
    if state and not devs_wait and not room and re.search(r"\b(no|lai|di)\b", t):
        return "smalltalk", f"Bạn muốn {'bật' if state == 'ON' else 'tắt'} đèn hay quạt, ở phòng nào?"
    if has_status_word:
        if room:
            return "status", {"room": room}
        if ctx.get("room"):
            return "status", {"room": ctx["room"]}
        return "llm", None
    return "llm", None
