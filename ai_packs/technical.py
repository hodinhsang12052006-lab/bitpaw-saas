# -*- coding: utf-8 -*-
"""
Gói AI cho ngành KỸ THUẬT / dịch vụ tại nhà (technical) — RESOURCE 'job': NHẬN VIỆC (job intake) + TRA TRẠNG THÁI.

Giống Jobber AI Receptionist / Housecall Pro CSR AI: khách nhắn "máy lạnh chảy nước ở 12 Lê Lợi" -> AI hỏi đủ tên, SĐT,
địa chỉ, mô tả hỏng hóc, ngày + buổi mong muốn, mức độ gấp -> tạo 1 việc THẬT trong db.tasks — đúng collection mà Bảng
điều phối (quanly_dichvu.html), Bản đồ điều phối (map_dashboard.html) và app nhân viên (app_nhanvien.html) đang đọc —
ở trạng thái 'Chờ Nhận' (chưa giao ai), cùng các trường như việc tạo tay (ten_khach, sdt, dia_chi, noi_dung, nguoi_nhan='',
lat/lng lấy bằng _geocode_address của app.py giống POST /api/tasks). AI KHÔNG hứa giờ tới, giá cuối hay người làm:
đội kỹ thuật gọi lại xác nhận.

Khẩn cấp (mùi gas, ngập nước, tia lửa / khói từ đồ điện, điện giật ĐANG xảy ra — classify_hazard): việc ghi mức
'emergency', cuộc chat chuyển người thật NGAY (giống handoff_to_staff, urgent) + email chủ tiệm; câu trả lời bảo khách ra
chỗ an toàn và gọi số khẩn cấp, không hẹn giờ. Có nhắc nguy hiểm mà KHÔNG loại trừ rõ (chuyện đã qua, chỉ hỏi / giả định,
không chắc, phủ định rồi lại nhắc lại): việc 'urgent' (GẤP) + chuyển người thật kiểm tra + báo chủ + dặn "nếu ngay lúc này
ngửi thấy gas / thấy tia lửa, khói thì ra chỗ an toàn và gọi số khẩn cấp" (không bảo sơ tán ngay). Máy hút mùi không hút
hết khói bếp / ống khói / pin báo khói: việc thường; nguy hiểm khách nói rõ là KHÔNG có hay đã hết: việc thường + câu dặn an
toàn (safety_tip).
Yêu cầu trùng 1 việc đã có mà chat không chứng minh được là chủ (trình duyệt khác gõ cùng SĐT): không lộ mã việc.

Tra trạng thái: chỉ việc CHỨNG MINH được là của khách (SĐT đã xác minh khớp sdt của việc — kể cả việc nhân viên tạo tay;
hoặc việc AI tạo trong đúng cuộc chat này). Không bao giờ trả noi_dung của việc tạo tay (có thể chứa hoa hồng thợ).
Dùng chung tiện ích SĐT / quyền sở hữu / tiền tệ / giờ tiệm với ai_packs/retail.py (4 gói "yêu cầu" cùng 1 luật).
"""
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta

import ai_packs
from ai_packs import retail as _c
from mongo_client import db, next_mongo_id

INDUSTRIES = ('technical',)
RESOURCE = 'job'
# Việc lưu SĐT ở trường 'sdt' (đúng như bảng điều phối) — mã SMS 1 lần chỉ gửi cho SĐT từng có việc ở tiệm này
BOOKING_COLLECTIONS = (('tasks', 'sdt'),)

WINDOWS = {'morning': ('buổi sáng', 'morning'), 'afternoon': ('buổi chiều', 'afternoon'),
           'evening': ('buổi tối', 'evening'), 'any': ('giờ nào cũng được', 'any time')}
URGENCY = {'normal': ('bình thường', 'normal'), 'urgent': ('GẤP', 'URGENT'), 'emergency': ('KHẨN CẤP', 'EMERGENCY')}
WAITING, TAKEN, DONE = 'Chờ Nhận', 'Đã Nhận', 'Hoàn Thành'   # trạng thái thật của db.tasks (bảng điều phối)
EMERGENCY_NUMBER = {'AU': '000', 'US': '911', 'CA': '911', 'NZ': '111', 'GB': '999', 'VN': '114'}
MAX_DAYS_AHEAD = 90
# Phát hiện NGUY HIỂM trong mô tả việc / tin nhắn của khách — ƯU TIÊN KHÔNG BỎ SÓT (bỏ sót là chết người, báo nhầm chỉ
# phiền): classify_hazard(text) -> 'danger' | 'uncertain' | 'negated' | 'none'.
#   'danger'    có ít nhất 1 nguy hiểm mà câu CUỐI nói về nó khẳng định nó đang / vừa xảy ra -> việc 'emergency', chuyển
#               người thật + báo chủ + dặn ra chỗ an toàn, gọi số khẩn cấp ("I can smell gas", "ổ cắm bốc khói", "the range
#               hood is smoking", "gas detector going off", "hôm qua không có khói, hôm nay có", "smelled gas yesterday,
#               still smells").
#   'uncertain' có nhắc nguy hiểm mà KHÔNG loại trừ rõ: chuyện đã qua mà không nói đã hết ("smelled gas last night"), câu
#               hỏi / giả định / lo sợ / nhờ kiểm tra ("is there a gas leak?", "what do I do if it sparks again?", "sợ chập
#               điện", "can you check for a gas leak?"), câu sàng lọc chưa có trả lời, phủ định rồi sau đó lại có từ nhắc lại
#               (now / today / still / again / stronger / worse / came back / keeps / won't stop / can't stop / can't get
#               ... to stop / giờ / nay / lại / vẫn / càng / nặng hơn, có dấu hay không dấu — kể cả khi câu đó tự có "không"
#               hay nói chuyện đặt lịch) -> việc 'urgent', chuyển người thật kiểm tra + báo chủ + dặn "nếu NGAY LÚC NÀY
#               ngửi thấy gas / thấy tia lửa, khói thì ra chỗ an toàn và gọi <số>" (KHÔNG bảo sơ tán ngay).
#   'negated'   MỌI lần nhắc đều bị phủ định rõ / đã HẾT rõ và không có gì nhắc lại sau đó ("no sparks or burning smell
#               when switching on", "không có mùi khét khi bật máy", "smelled gas earlier, it's gone now") -> việc thường +
#               câu dặn an toàn.
#   'none'      không nhắc nguy hiểm nào sau khi bỏ cụm KHÔNG nguy hiểm trong danh sách -> việc thường.
# BẤT BIẾN: tin nhắn có nhắc nguy hiểm chỉ thành 'negated' / 'none' qua phủ định RÕ hoặc cụm không-nguy-hiểm CÓ TRONG DANH
# SÁCH (_HZ_EXCLUDE, _HZ_HEAT, _HZ_COOK_SMOKE, _HZ_VENT_SMOKE, nước tràn chỉ do bồn cầu / máy giặt / máy rửa chén / ống
# thoát mà không nhắc đồ điện, báo khói / báo CO kêu vì PIN yếu / hết hay vì nấu ăn). Còn nghi ngờ -> 'uncertain', không
# bao giờ lặng lẽ thành việc thường. Thiết bị TỰ bốc khói / tóe lửa là NGUY HIỂM dù là máy hút mùi / quạt hút / lò nướng;
# nước gần / chảy vào đồ điện là NGUY HIỂM dù nguồn nước là bồn cầu hay máy giặt.
# Các bước (hazard_check):
#   1. Bỏ cụm KHÔNG phải nguy hiểm (_HZ_EXCLUDE; câu thành ngữ nóng _HZ_HEAT "burning hot / scorching weather / smoking
#      hot" trừ khi chủ ngữ là đồ điện; khói nấu ăn / máy hút mùi không hút hết khói _HZ_COOK_SMOKE — trừ khi khói ra từ
#      thiết bị: "the range hood is smoking", "smoke coming out of the exhaust fan" vẫn là NGUY HIỂM).
#   2. Tách câu ở . ! ? ; , : - ( ) và but / however / and / then / nhưng / mà / và, cùng TRƯỚC now / today / giờ /
#      bây giờ / hôm nay. Danh sách chỉ gồm từ khoá ("No gas smell, sparks or smoke") giữ trong 1 câu: phủ định đầu danh
#      sách phủ cả danh sách.
#   3. Mỗi câu: mỗi từ khoá (_HZ, theo loại gas / sparks / burning / smoke / shock / water / co / alarm / fire) được xếp
#      present | negated | past | question | hypothetical (_hz_state). Câu KHÔNG có từ khoá vẫn có thể LẬT LẠI ("but I
#      do now", "today it is stronger", "sáng nay vẫn còn", "again this morning") hoặc KẾT THÚC ("it's gone now", "hết
#      mùi rồi") nguy hiểm của câu trước; từ nhắc lại sau 1 phủ định (_HZ_AGAIN / _HZ_LATER) -> ít nhất 'uncertain'.
#   4. Câu CUỐI nói về mỗi loại quyết định. Lấp lửng ("not sure if it's sparking", "I don't think it's a gas leak",
#      "không biết có rò rỉ gas không") vẫn là NGUY HIỂM.
# Chuông / đầu báo ĐANG kêu (không phải hết pin, không phải do nấu ăn): là NGUY HIỂM ("the gas detector is going off",
# "smoke alarm keeps sounding", "báo động CO đang kêu"). Thiếu đuôi này thì "smoke alarm / gas detector / báo khói" chỉ là
# tên thiết bị (lắp, thay, kiểm tra) -> bỏ qua.
_HZ_ALARM_PRE = (
    r"(?:\s+(?:in|on|at|near)\s+(?:the\s+|my\s+|our\s+)?[\w']+)?"
    r"(?:\s+(?:alarms?|is|are|was|were|has|have|had|keeps?|kept|just|been|still|now|again|all|constantly|suddenly|"
    r"started|starts|(?:won'?t|will not|doesn'?t|does not|can'?t|cannot) stop))*\s+")
_HZ_ALARM_VERBS = (r"going off|went off|goes off|gone off|go off|sounding|sounded|alarming|blaring|screaming|ringing|"
                   r"beeping|triggered|activated|wailing|shrieking")
_HZ_ALARM_TAIL = _HZ_ALARM_PRE + r"(?:" + _HZ_ALARM_VERBS + r")\b"
_HZ_ALARM_TAIL_VI = (r"(?: (?:đang|cứ|bị|liên tục|tự|lại|vẫn|hay|suốt|nó|thì|tự nhiên|đột nhiên|bỗng))* "
                     r"(?:kêu|hú|reo|réo|báo động)(?! (?:thợ|người|nhân viên|bên|anh|chị|em|ai)\b)")
_HZ_EXCLUDE = re.compile(
    r"\bsmok(?:e|ing)[- ]?(?:alarms?|detectors?|sensors?)\b(?!" + _HZ_ALARM_TAIL + r")"
    r"|\bsmok(?:e|ing)[- ]?(?:seals?|dampers?|tests?|testing|vents?|extract\w*|exhaust\w*|"
    r"control\w*|curtains?|doors?|machines?|signals?|shops?|free|stacks?|screens?|evacuation|management|spill|"
    r"baffles?|barriers?|stains?|stained|damaged?|residue|marks?|areas?|rooms?|zones?|signs?|policy|shelters?)\b"
    r"|\bsmoke ?(?:and|&|/) ?(?:heat|co2?|carbon monoxide) (?:alarms?|detectors?|sensors?)\b(?!" + _HZ_ALARM_TAIL + r")"
    r"|\b(?:no|non)[- ]smoking\b|\bsmoked (?:salmon|meat|fish|glass|ham)\b|\bsmoke ?bombs?\b|\bfogging\b"
    r"|\bfire (?:in|inside) (?:the |my |our |a )?(?:fireplace|fire ?pit|wood (?:heater|stove|burner)|pot ?belly(?: stove)?|"
    r"hearth|firebox|log burner|pizza oven)s?\b"
    r"|\b(?:shower|drain|waste|sink|basin|bath|toilet|tap|storm ?water|storm|air|vent|hose|pipe|pump|floor|overflow|sewer|"
    r"gutter|pool) outlets?\b"
    r"|\bfire[- ]?alarms?\b(?!" + _HZ_ALARM_TAIL + r")"
    r"|\bfire[- ]?(?:extinguishers?|doors?|safety|sprinklers?|blankets?|exits?|rated|rating|places?|pits?|wood|"
    r"hydrants?|hoses?|inspections?|drills?|escapes?|systems?|panels?|proof\w*|walls?|stops?|separation|resist\w*|retard\w*|"
    r"works|crackers?|starters?|hazards?|risks?|insurance|compliance|certificates?)\b|\bfireplaces?\b|\bfirewood\b"
    r"|\bflood ?lights?\b|\bfloodlight\w*|\bflood[- ](?:damage|restoration|insurance|zones?|plains?|barriers?|gates?|proof\w*|"
    r"mitigation|clean-?up|risks?)\b|\bspark[- ]?plugs?\b|\bspark (?:broadband|modem|router|wi-?fi|fibre|fiber|nz|mobile|"
    r"account|bill|plan|internet|phone|sim)\b|\bgas[- ](?:leak[- ])?(?:tests?|testing|checks?|inspections?|detection|"
    r"compliance|certificates?|safety checks?)\b|\bgas[- ](?:leak[- ])?detectors?\b(?!" + _HZ_ALARM_TAIL + r")"
    r"|\bbefore,? (?:during,? )?(?:or|and) after\b|\bbefore (?:or|and) after\b|trước (?:và|hay|hoặc) sau"
    r"|máy hút mùi|hút mùi|máy hút khói|hút khói|ống khói|khói bếp|khói (?:\w+ )?bám|bám khói|ám khói|khói thuốc(?: lá)?|"
    r"khói nhang|khói hương|khói xe|khói bụi|khói nướng|khói dầu|khói nấu|máy tạo khói|"
    r"(?:đầu |chuông |thiết bị |hệ thống |máy )?báo khói(?!" + _HZ_ALARM_TAIL_VI + r")|cảm biến khói(?!" + _HZ_ALARM_TAIL_VI
    + r")|(?:đầu |chuông |hệ thống |thiết bị )?báo cháy(?!" + _HZ_ALARM_TAIL_VI + r")|"
    r"bình chữa cháy|chữa cháy|chống cháy|phòng cháy|bóng(?: đèn)? (?:bị )?(?:cháy|nổ)|cháy bóng|"
    r"(?:cầu chì|chì) (?:bị )?(?:cháy|nổ|đứt)|(?:cháy|nổ) cầu chì|chập chờn|\bchap chon\b|thuốc lá|xì gà|phun khói|"
    r"xông khói")
# Thành ngữ NÓNG (thời tiết / nước nóng): "it's burning hot in here", "burning up in the house", "scorching weather",
# "the water is scorching", "smoking hot day" -> không phải nguy hiểm, TRỪ KHI 4 chữ ngay trước là đồ điện ("the plug is
# burning hot", "the outlet is scorching" vẫn là NGUY HIỂM) — xem _hz_mask_heat.
_HZ_HEAT = re.compile(r"\b(?:burning|scorching|boiling|smoking|baking|roasting|blazing|sweltering|stinking) hot\b"
                      r"|\bburning up\b|\bscorch(?:ing|er)\b")
_HZ_HEAT_ELEC = re.compile(
    r"\b(?:outlets?|sockets?|plugs?|power ?points?|gpos?|switch(?:es|board|boards)?|fuse ?box(?:es)?|breakers?|panels?|"
    r"wires?|wiring|cables?|cords?|leads?|power ?boards?|adapt[eo]rs?|chargers?|motors?|batter(?:y|ies)|lights?|lamps?|"
    r"bulbs?|transformers?|inverters?|meter ?box(?:es)?|ổ cắm|ổ điện|phích|công tắc|dây|tủ điện|cầu dao)\b")
# Nơi phát ra khói là THIẾT BỊ / đồ điện / kết cấu nhà: cụm "khói nấu ăn" ngay trước những chỗ này KHÔNG được bỏ ("cooking
# smoke coming out of the outlet", "khói khi nấu bốc ra từ ổ cắm").
_HZ_SRC_WORDS = (
    r"(?:outlets?|sockets?|power ?points?|gpos?|plugs?|switch(?:es|board|boards)?|fuse ?box(?:es)?|breakers?|panels?|"
    r"meter ?box(?:es)?|wires?|wiring|cables?|cords?|lights?|downlights?|lamps?|bulbs?|motors?|compressors?|air ?con\w*|"
    r"aircon\w*|heaters?|fridges?|freezers?|dryers?|washers?|washing machines?|dishwashers?|tvs?|chargers?|batter(?:y|ies)|"
    r"appliances?|microwaves?|kettles?|ovens?|stoves?|cooktops?|hobs?|toasters?|fryers?|air fryers?|(?:range |cooker )?hoods?|"
    r"exhaust(?: fans?)?|extractors?(?: fans?)?|fans?|vents?|walls?|ceilings?|floor(?:boards?)?|roof(?: ?space)?|attic|"
    r"electrics?|electrical|units?|ổ cắm|ổ điện|phích cắm|công tắc|cầu dao|aptomat|tủ điện|bảng điện|dây điện|dây|đèn|"
    r"bóng đèn|mô tơ|motor|động cơ|máy|quạt|tường|trần|sàn|bếp từ|bếp điện|lò)\b")
_HZ_NOT_FROM_SRC = (r"(?!(?:\s+\S+){0,4}?\s+(?:from|out of|behind|inside|in|under|underneath|near|around|through|"
                    r"từ|ra từ|trong|sau|ở|dưới|quanh)\s+(?:the\s+|a\s+|my\s+|our\s+|this\s+|cái\s+|các\s+)?(?:\S+\s+)?"
                    + _HZ_SRC_WORDS + r")")
# Khói NẤU ĂN / BBQ / thuốc lá / nhang nến, máy hút mùi / quạt hút KHÔNG HÚT HẾT khói: không phải nguy hiểm. Thiết bị TỰ
# bốc khói ("the range hood is smoking", "smoke coming out of the exhaust fan", "máy hút mùi bốc khói", "the toaster is
# smoking") không nằm trong danh sách này -> vẫn là NGUY HIỂM; "we weren't cooking" cũng không bỏ khói.
_HZ_COOK_SMOKE = re.compile(
    r"(?:\b(?:cooking|bbq|barbecue|grill|grilling|frying|stir[- ]?fry|wok|toast|burnt toast|cigarettes?|cigars?|tobacco|"
    r"vape|vaping|incense|candles?|fireplace|wood ?(?:fire|heater|stove)|chimney|campfire|bonfire|neighbou?rs?'?|"
    r"neighbou?r's) smok(?:e|y)\b"
    r"|\bsmok(?:e|y)\b(?:\s+(?!(?:from|out|of|behind|inside|in|under|underneath|near|through|alarms?|detectors?|"
    r"sensors?)\b)\w+){0,3}?\s+"
    r"(?:from|when|while|whenever|every ?time|each time|during|after|because of)\s+"
    r"(?:we\s+|i\s+|you\s+|they\s+|someone\s+|the\s+|our\s+|my\s+|a\s+)?(?:\w+\s+)?(?:cook(?:ing|s|ed)?|fr(?:y|ying|ied|ies)|"
    r"grill(?:ing|ed|s)?|bbq(?:ing|s)?|barbecu\w*|toast(?:ing|ed|s)?|bak(?:e|es|ed|ing)|sear(?:ing|ed)?|roast(?:ing|ed)?|"
    r"cigarettes?|cigars?|candles?|incense|fireplace|wood ?(?:fire|heater)s?|chimney|neighbou?rs?'?)\b"
    r"|(?:\bnot|n't|\bnever|\bfails? to|\bunable to|\bbarely|\bweak(?:ly)?|\bpoorly)\s+(?:\w+\s+){0,2}?(?:pull|pulling|clear|"
    r"clearing|extract|extracting|remove|removing|suck|sucking|draw|drawing|vent|venting|get(?:ting)? rid of|take|taking)\s+"
    r"(?:out\s+|away\s+|up\s+)?(?:the\s+|all\s+(?:the\s+)?|any\s+|much\s+|enough\s+|of\s+the\s+)?(?:cooking\s+)?smok(?:e|y)\b"
    r"(?:\s+out)?"
    r"|(?<!bốc )(?<!xì )(?<!tỏa )(?<!toả )(?<!phun )(?<!báo )(?<!biến )khói (?:\S+ ){0,2}(?:khi|lúc|mỗi khi|mỗi lần|trong lúc) (?:\S+ )?"
    r"(?:nấu|chiên|xào|nướng|rán|hút thuốc|đốt)"
    r"|(?:nấu|(?<!nồi )chiên|xào|(?<!lò )(?<!máy )nướng|rán)(?: \S+){0,2}? (?:bị |ra |có |thì |tỏa |bốc )?"
    r"(?:nhiều |rất nhiều |toàn |hơi )?khói"
    r"|(?:không|ko|chẳng|chả|hông|k|chưa) hút (?:\S+ ){0,2}khói|hút (?:không|ko|chẳng|chả|hông) (?:\S+ )?khói)"
    + _HZ_NOT_FROM_SRC)
# Chỉ khi tin nhắn nói về ống khói / lò sưởi (khói tạt ngược vào nhà: "chimney needs cleaning, smoke comes back in") hay
# máy hút mùi / quạt hút YẾU, hỏng, cần thay ("Máy hút mùi yếu, bếp nhiều khói"). "bếp ĐẦY khói" thì vẫn là nguy hiểm.
_HZ_VENT_CTX = re.compile(
    r"\b(?:chimneys?|flues?|fireplaces?|wood ?(?:heater|fire|stove)s?)\b|ống khói|lò sưởi"
    r"|(?:máy hút mùi|hút mùi|máy hút khói|hút khói|quạt hút)(?: \S+){0,2}? (?:yếu|kém|không hút|hút không|hút yếu|hư|hỏng)"
    r"|(?:thay|lắp|mua) (?:máy hút mùi|máy hút khói|quạt hút)")
_HZ_VENT_SMOKE = re.compile(
    r"(?:\bsmoke (?:comes?|coming|blows?|blowing|goes?|going|pours?|pouring|gets?|getting|is coming|keeps coming) back "
    r"(?:in|into|down)\b|(?:nhà bếp|phòng bếp|căn bếp|bếp) (?:\S+ )?(?:nhiều|hay có|có nhiều|bị ám|ám) khói)"
    + _HZ_NOT_FROM_SRC)
# Nước tràn CHỈ do bồn cầu / máy rửa chén / máy giặt / bồn tắm / bồn rửa mà tin nhắn không nhắc đồ điện / nguồn điện: việc
# ống nước thường. Vỡ ống / bể bình (_HZ_WATER_HARD) và nước gần ổ cắm, tủ điện, đèn vẫn là NGUY HIỂM.
_HZ_PLUMB_SRC = re.compile(r"\b(?:toilets?|loo|cisterns?|dishwashers?|washing machines?|bath ?tubs?|baths?|showers?|"
                           r"basins?|sinks?|drains?|floor wastes?|gutters?|downpipes?|sewers?|taps?|pipes?)\b|bồn cầu|bồn vệ sinh|toilet|máy giặt|máy rửa (?:chén|bát)|bồn tắm|bồn rửa|"
                           r"chậu rửa|lavabo|vòi sen|\b(?:bon cau|bon ve sinh|may giat|may rua (?:chen|bat)|bon tam|"
                           r"bon rua|chau rua|voi sen)\b")
_HZ_PLUMB_ELEC = re.compile(
    r"\b(?:outlets?|sockets?|power|gpos?|plugs?|switch(?:es|board|boards)?|fuse ?box(?:es)?|breakers?|panels?|"
    r"meter ?box(?:es)?|wires?|wiring|cables?|cords?|leads?|lights?|downlights?|light ?fittings?|lamps?|electric\w*|"
    r"rcds?|tripp\w*|trips?|sparks?\w*|shocks?\w*|plugged)\b|ổ cắm|ổ điện|phích|công tắc|tủ điện|cầu dao|aptomat|dây điện|"
    r"bảng điện|đèn|điện|\b(?:o cam|o dien|phich|cong tac|tu dien|cau dao|day dien|bang dien|bong den|dien)\b")
# "drain / shower / tap outlet" là lỗ thoát nước, không phải ổ điện (cho phép "chỉ nước tràn" vẫn là việc ống nước)
_HZ_PLUMB_OUTLET = re.compile(r"\b(?:shower|drain|waste|sink|basin|bath|toilet|tap|storm ?water|storm|air|vent|hose|pipe|"
                              r"pump|floor|overflow|sewer|gutter|pool) outlets?\b")
# Đồ điện mà nước chạm / chảy vào là NGUY HIỂM (dùng trong nhóm 'water' của _HZ).
_HZ_WET_ELEC = (r"(?:light fittings?|lights?|downlights?|outlets?|sockets?|power ?points?|power ?boards?|extension leads?|"
                r"gpos?|switch(?:es|board|boards)?|fuse ?box(?:es)?|electrical panel|panel|meter ?box|electrics|wiring|"
                r"wires|plugs?|extension cords?|power ?cords?|electrical)")
_HZ_WATER_HARD = re.compile(r"burst|vỡ|bể|bục|nổ ống|\bvo ong|\bbe ong")
# Từ khoá theo loại. Tiếng Việt CÓ DẤU cho chữ dễ nhầm ("đang chạy" / "đang cháy", "ra khỏi" / "ra khói", "khởi động"),
# không dấu chỉ cho cụm không nhầm được ("mui gas", "chap dien", "tia lua"). Lỗi gõ hay gặp: "smel gas", "gass", "burnig".
_HZ = re.compile(
    r"(?P<co>\b(?:co2?|carbon monoxide|gas(?: leak)?|lpg|propane)[- ](?:alarms?|detectors?|sensors?|monitors?)"
    + _HZ_ALARM_PRE + r"(?:" + _HZ_ALARM_VERBS + r"|chirping)\b|\bcarbon monoxide\b(?! (?:alarms?|detectors?|sensors?|"
    r"monitors?|tests?|testing|checks?)\b)|ngộ độc khí|ngộ độc co\b|\bkhí co\b|(?:báo động|báo|cảm biến|chuông báo|máy báo|"
    r"thiết bị báo|đầu báo)(?: khí)? (?:co|gas|ga)\b(?: (?:đang|bị|cứ|liên tục|tự|lại|vẫn))* (?:kêu|hú|reo|réo|báo động|báo)"
    r"|\b(?:bao dong|bao|cam bien|chuong bao|may bao|dau bao|thiet bi bao) (?:khi co|gas|ga)\b"
    r"(?: (?:dang|bi|cu|lien tuc|tu|lai|van))* (?:keu|hu|reo|bao dong)\b)"
    r"|(?P<alarm>\b(?:smoke|fire|heat|smoke ?(?:and|&|/) ?(?:heat|co2?|carbon monoxide))[- ]?(?:alarms?|detectors?|sensors?)"
    + _HZ_ALARM_TAIL + r"|(?:đầu |chuông |thiết bị |hệ thống |máy )?(?:báo|cảm biến) (?:khói|cháy)" + _HZ_ALARM_TAIL_VI
    + r"|\b(?:dau |chuong |thiet bi |he thong |may )?(?:bao|cam bien) (?:khoi|chay)(?: (?:dang|cu|bi|lien tuc|tu|lai|van|"
    r"hay|suot|tu nhien|dot nhien))* (?:keu|hu|reo|bao dong)\b(?! (?:tho|nguoi|nhan vien|ben|anh|chi|em|ai)\b))"
    r"|(?P<gas>\b(?:gas{1,2}|gaz)(?:es)? (?:leak|leek|leack|leik)\w*|\bleak\w* (?:of )?(?:natural |lpg |propane )?(?:gas{1,2}|gaz)\b"
    r"(?! (?:heaters?|stoves?|bills?|cooktops?|ovens?|hot water|meters?|bottles?|fireplaces?|appliances?))|"
    r"\b(?:gas{1,2}|gaz) (?:is |was |has been )?leak\w*|\b(?:lpg|propane) leak\w*|\b(?:sme+l+(?:s|t|ed|led|ling|ing|in)?|"
    r"odou?rs?|stench|stink\w*) (?:(?:might|could|may|must|is|was|seems?|appears?) (?:to )?)?(?:be |of |like )?"
    r"(?:a |some |the )?(?:natural |lpg |propane )?(?:gas{1,2}|gaz)\b"
    r"(?! (?:heaters?|stoves?|bills?|cooktops?|ovens?|hot water|meters?|bottles?|fireplaces?|appliances?))|"
    r"\b(?:gas{1,2}|gaz) (?:sme+l+\w*|"
    r"odou?rs?|stench)|\bsme+l+\w* (?:a bit |kind of |kinda |really |very |a little |slightly |quite )?gassy\b|"
    r"\bgassy (?:smell|odou?r)|\brotten[- ]eggs?\b|\b(?:gas{1,2}|gaz) (?:is )?hiss\w*|"
    r"\bhiss\w* (?:sound |noise )?(?:coming |that'?s coming )?(?:from|at|near|in|out of) "
    r"(?:the )?(?:gas{1,2}|gaz)\b|\b(?:gas{1,2}|gaz|lpg|propane) fumes\b|\b(?:lpg|propane|gas{1,2}|gaz) (?:bottle|cylinder|"
    r"tank|line|pipe|hose|valve|regulator|meter|fitting|connection)s? (?:is |are |has been |keeps )?(?:leak\w*|hiss\w*)|"
    r"mùi (?:khí )?(?:gas|ga|gaz)\b|mùi (?:\S+ ){0,2}(?:như|giống)(?: mùi)? (?:gas|ga|gaz)\b|hơi (?:gas|ga)\b|"
    r"(?:rò rỉ|rò|xì|hở|xì hơi) (?:khí )?(?:gas|ga|gaz)\b|(?:bình|bếp|van|ống|dây|bồn) (?:gas|ga) (?:bị )?(?:xì|rò rỉ|rò|"
    r"hở)|\b(?:gas|ga) (?:bị )?(?:xì|rò rỉ|rò|hở)\b|\b(?:mui|ro ri|ro|xi|ho) (?:gas|gaz)\b|\b(?:mui|ro ri) ga\b|"
    r"\bbinh ga (?:bi )?(?:xi|ro)\b|\b(?:bep|van|ong|day|bon) (?:gas|ga) (?:bi )?(?:xi|ro ri|ro|ho)\b|"
    r"\b(?:gas|ga) bi (?:xi|ro ri|ro|ho)\b|tiếng xì(?: xì)? (?:ở|từ|chỗ|trong) (?:\S+ )?(?:bình|bếp|van|ống|dây|bồn) (?:gas|ga)\b)"
    r"|(?P<sparks>\bspark(?:s|ing|in|ed)?\b(?![- ](?:plugs?|arrest\w*|gaps?)\b)|\bspak(?:s|ing|in|ed)\b|"
    r"\bspark(?:es|ng|ign|inng|kin|kng)\b|\bsprak(?:s|ing|in|ed)?\b|\barc(?:ing|ed)\b|"
    r"\belectrical arcs?\b|\b(?:blue |bright |big |a |small )?flash(?:es)? (?:of light )?(?:from|in|at|inside|behind|out of) "
    r"(?:the |my |our )?(?:switchboard|fuse ?box|panel|meter ?box|outlets?|sockets?|power ?points?|breakers?|switch(?:es)?|"
    r"plugs?|wall)\b|"
    r"\b(?:(?:crackl(?:e|es|ed|ing)|sizzl(?:e|es|ed|ing)|fizz(?:es|ed|ing)?) |popping (?=sounds?\b|noises?\b))"
    r"(?:\w+ ){0,3}?(?:from|in|at|inside|"
    r"behind|out of) (?:the |my |our |a )?(?:\S+ )?(?:outlets?|sockets?|power ?points?|gpos?|switch(?:es|board|boards)?|"
    r"fuse ?box(?:es)?|panel|meter ?box|plugs?|wires?|wiring|power ?boards?)\b|"
    r"\b(?:outlets?|sockets?|power ?points?|gpos?|switch(?:es|board|boards)?|fuse ?box(?:es)?|meter ?box|plugs?|wires?|"
    r"wiring|power ?boards?)(?: \w+){0,2}? (?:is |are |keeps? |kept |started )?(?:crackl(?:e|es|ed|ing)|"
    r"sizzl(?:e|es|ed|ing)|fizz(?:es|ed|ing)?)\b|"
    r"tia lửa|tóe lửa|toé lửa|tóe điện|toé điện|xẹt điện|xẹt lửa|chập điện|chập mạch|chập cháy|bị chập\b|đoản mạch|"
    r"nháy lửa|(?:ổ cắm|ổ điện|phích cắm|công tắc|cầu dao|aptomat|tủ điện|dây điện|bảng điện)(?: \S+){0,2}? (?:bị )?"
    r"(?:nổ|kêu) (?:lách tách|tách|lép bép|tạch|tanh tách|tí tách|bụp|lụp bụp|lẹt đẹt)|"
    r"\b(?:tia lua|chap dien|chap mach|toe lua|xet dien|chap chay)\b|\bbi chap\b(?! chon))"
    r"|(?P<burning>\b(?:burn\w{0,4}|burin\w{0,4}|scorch\w*|melting|electrical|electric) (?:plastic |rubber |wire |"
    r"wiring )?(?:sme+l+\w*|odou?rs?|stench)|\b(?:burn\w{0,4}|toxic|electrical|acrid|chemical) fumes\b|"
    r"\bsme+l+(?:s|t|ed|led|ling|ing|in)? (?:of |like )?(?:(?:something|it'?s|its|"
    r"plastic|wires?|wiring|rubber|electrical) )?(?:burn\w{0,4}|burin\w{0,4}|melting|scorch\w*)|"
    r"\bsme+l+(?:s|t|ed|ing|in)? (?:really |very |so |a bit |kind of |kinda |quite |a little )?(?:hot|electrical)\b|"
    r"\bscorched\b|\bscorch ?marks?\b|\bscorching\b|"
    r"\b(?:something|it|outlets?|switch\w*|wires?|wiring|cables?|plugs?|panel|sockets?|cords?|leads?|chargers?|"
    r"power ?boards?|power ?points?|adapt[eo]rs?|batter(?:y|ies)|motors?|fuse ?box(?:es)?|appliances?)(?:'s| is| are)? "
    r"(?:burning|smouldering|smoldering|melting)\b|"
    r"\bmelt(?:ed|ing) (?:outlets?|sockets?|plugs?|wires?|wiring|cables?|switch\w*|power ?points?)\b|"
    r"\b(?:outlets?|sockets?|plugs?|power ?points?|gpos?|wires?|wiring|cables?|cords?|leads?|switch(?:es)?|power ?boards?|"
    r"adapt[eo]rs?)(?: \w+){0,2}? (?:is |are |was |were |has |have |got |looks? |has been |have been )?(?:melted|melting|"
    r"charred|blackened|burnt|burned|scorched|singed)\b(?! out)|"
    r"\b(?:outlets?|sockets?|plugs?|power ?points?|gpos?|switch(?:es|board|boards)?|fuse ?box(?:es)?|breakers?|"
    r"wires?|wiring|cables?|cords?|leads?|extension leads?|power ?boards?|chargers?|adapt[eo]rs?|batter(?:y|ies)|"
    r"transformers?|meter ?box(?:es)?|power ?packs?)(?: \w+){0,2}? (?:is|are|was|were|gets?|getting|got|"
    r"feels?|felt|went|becomes?|running) (?:(?:still|always|getting|really|very|extremely|super|too|so|quite|burning|"
    r"scorching|red) )*hot\b|"
    r"(?:ổ cắm|ổ điện|phích cắm|dây điện|công tắc|cầu dao|aptomat|dây)(?: \S+){0,3}? (?:bị )?(?:chảy nhựa|nóng chảy|"
    r"cháy đen|cháy xém|xém)|"
    r"cháy xém|mùi khét|"
    r"khét(?! tiếng)|mùi (?:như )?(?:nhựa |dây |điện |đồ |dây điện )?cháy|cháy khét|mùi nhựa (?:cháy|chảy)|"
    r"mùi (?:như |giống )?burn\w*|\bmui khet\b|\bkhet\b|\b(?:o cam|o dien|phich cam|day dien|cong tac|cau dao|aptomat)"
    r"(?: \S+){0,3}? (?:bi )?(?:chay nhua|nong chay|chay den|chay xem)\b)"
    r"|(?P<smoke>\bsmok(?:e|es|ed|ing|in|y|ey|eing|ng)\b|\bsmoak\w*|\bsomke\b|\bsmoek\b|\bsmoulder\w*|\bsmolder\w*|khói|"
    r"\b(?:boc|xi|toa|co) khoi\b(?! (?:dong|"
    r"dau|nghia|phat|tao|xuong|cong))|\bkhoi den\b)"
    r"|(?P<shock>\bele\w{0,4}ic(?:al)? shoc?ks?\b|\belec\w{0,5}cut\w*|\bshoc?k(?:ed|s|ing)? (?:me|him|her|us|them|my \w+|someone|"
    r"somebody|the kids?|the child|people|anyone)\b|\b(?:got|get|gets|getting|(?:give|gives|gave|giving) (?:me|him|her|"
    r"us|them|my \w+|someone|people)|received|receiving|had|having|felt|feel|feeling) (?:a |an |some )?(?:small |mild |"
    r"big |nasty |little |slight |bad |huge |strong )?(?:ele\w{0,4}ic(?:al)? )?shoc?ks?\b|"
    r"\b(?:got|get|gets|getting|keeps? getting) (?:a )?(?:bit |little |slightly |badly )?shocked\b|"
    r"\b(?:was|were|been|being) shocked (?:by|from|when|while|touching|through) (?:the |a |my |our )?(?:\w+ )?(?:switch\w*|"
    r"outlets?|sockets?|power ?points?|taps?|ovens?|stoves?|fridges?|washing machines?|washers?|dryers?|appliances?|wires?|"
    r"cables?|plugs?|lights?|heaters?|kettles?|showers?|metal|doors?|handles?|cords?|leads?|toasters?|microwaves?|"
    r"dishwashers?|sinks?)\b|\bzapp(?:ed|ing)\b|"
    r"\bzaps? (?:me|him|her|us|them)\b|\btingl(?:e|es|ed|ing|y)\b|điện giật|giật điện|giật tê|tê tay|tê người|tê chân|"
    r"shock điện|sốc điện|rò điện|rò rỉ điện|dò điện|hở điện|lọt điện|điện (?:bị )?rò|(?:vỏ|thân) (?:máy|tủ|bình)(?: \w+){0,2} "
    r"(?:có|bị) (?:điện|giật)|có điện ở vỏ|(?:chạm|sờ|đụng|cầm)(?: vào| phải)?(?: \w+){0,3}(?: là| thì| bị)* "
    r"(?:giật|tê)\b|\b(?:dien giat|giat dien|ro dien|ro ri dien|ho dien)\b)"
    r"|(?P<water>\bflood(?:s|ed|ing)?\b|\bburst (?:hot )?(?:water )?(?:pipes?|mains?|tanks?|cylinders?)\b|"
    r"\b(?:pipes?|(?:hot )?water (?:tanks?|cylinders?|heaters?|systems?|mains?)|tanks?|cylinders?|hws) (?:has |have |just )?"
    r"burst\b|\bwater everywhere\b|\bwater (?:is |was )?(?:pouring|gushing|spraying|flooding)\b|"
    r"\b(?:laundry|kitchen|house|home|floor|room|bathroom|garage|basement|downstairs|carpets?|unit|flat|apartment|place)s? "
    r"(?:is |are |was |were |got |has been )?(?:completely |totally |all |half )?under ?water\b|"
    r"\b(?:water|rain(?: ?water)?|moisture)(?! (?:heaters?|systems?|tanks?|cylinders?|pressure|filters?|bills?|meters?|"
    r"softeners?|coolers?|jugs?|bottles?|features?|pumps?|units?|lines?|purifiers?|dispensers?|mains?|services?|"
    r"restrictions?|stains?|stained|marks?|damage\w*|spots?|rings?)\b)(?: \S+){0,5}? (?:in|into|inside|out of|through|"
    r"from|onto|on|near|around|behind|over|under|next to|"
    r"close to|touching|reaching|towards?|up to|at) (?:the |a |my |our |an )?(?:\S+ )?" + _HZ_WET_ELEC + r"\b"
    r"|\b(?:leak(?:s|ed|ing)?|drip(?:s|ped|ping)?|pour(?:s|ed|ing)?|seep(?:s|ed|ing)?|spill(?:s|ed|ing)?|"
    r"overflow(?:s|ed|ing)?|gush(?:es|ed|ing)?) (?:\S+ ){0,3}?(?:in|into|onto|on|through|near|over|behind|around|under|"
    r"out of|from) (?:the |a |my |our |an )?(?:\S+ )?" + _HZ_WET_ELEC + r"\b|\b(?:wet|soaked|flooded|"
    r"water[- ]?logged) (?:switchboard|fuse ?box|electrical panel|panel|outlets?|sockets?|power ?points?|wiring|plugs?)\b|"
    r"\b(?:switchboard|fuse ?box|electrical panel|meter ?box|outlets?|sockets?|power ?points?|power ?boards?|wiring)"
    r"(?:(?: \S+){1,3}? (?:is|are|was|were|got|gets|getting|has got|have got|has gotten)| (?:is|are|got|gets|has got|have got))?"
    r" (?:all |completely |totally |soaking )?(?:wet|soaked|flooded|under water)\b|\b(?:ceiling )?(?:light fittings?|lights?|downlights?|outlets?|sockets?|"
    r"power ?points?|switch(?:es)?) (?:is |are )?(?:full of|filled with|filling (?:up )?with) water\b|"
    r"\b(?:ceiling |down)?(?:light fittings?|lights?|downlights?|light switch(?:es)?|power ?points?|sockets?|gpos?|"
    r"switchboards?|fuse ?box(?:es)?|meter ?box(?:es)?|power ?boards?) (?:is |are |keeps? |has been |was )?(?:dripping|"
    r"leaking|pouring|spraying|gushing)(?: (?:water|rain))?\b|ngập nước|nước ngập|bị ngập|"
    r"đang ngập|ngập sàn|ngập nhà|ngập bếp|ngập phòng|ngập tầng|ngập hầm|vỡ ống|bể ống|bục ống|nổ ống|ống nước (?:bị )?"
    r"(?:vỡ|bể|bục)|(?<!máy )(?<!bình )(?<!hồ )nước (?:\S+ ){0,5}?(?:vào|vô|từ|qua|xuống|trúng|gần|tới|đến|lên|dính|sát|"
    r"cạnh|quanh|chỗ) (?:cái |các |chỗ |cả )?(?:ổ cắm|ổ điện|tủ điện|cầu dao|"
    r"công tắc|bóng đèn|đèn|dây điện|bảng điện|đồng hồ điện|aptomat)|(?:ổ cắm|ổ điện|tủ điện|cầu dao|công tắc|bảng điện|"
    r"dây điện|aptomat|bóng đèn|đèn)(?: \S+)? "
    r"(?:bị )?(?:ướt|ngấm nước|vô nước|vào nước|dính nước|ngập|chảy nước|rỉ nước|nhỏ nước|dột)|\b(?:ngap nuoc|nuoc ngap|"
    r"vo ong nuoc|be ong nuoc|bi ngap|dang ngap)\b|\bngap (?:nha|san|bep|phong)\b"
    r"|\bnuoc (?:\S+ ){0,5}?(?:vao|vo|xuong|trung|gan|toi|len|dinh|tu|sat|canh) (?:o cam|o dien|tu dien|cau dao|cong tac|"
    r"bong den|day dien|bang dien|aptomat)\b|\b(?:o cam|o dien|tu dien|cau dao|cong tac|bang dien|day dien|aptomat|bong den)"
    r"(?: \S+)? (?:bi )?(?:uot|ngam nuoc|vo nuoc|vao nuoc|dinh nuoc|ngap|chay nuoc|ri nuoc|nho nuoc|dot)\b)"
    r"|(?P<fire>\bon fire\b|\bcaught fire\b|\bcatch(?:es|ing)? (?:on )?fire\b|\bfire (?:in|inside|at|from|started|"
    r"broke out|is spreading|spreading|behind|under|on)\b|\b(?:a|small|electrical|big|kitchen|house|grease|oil|pan|stove|"
    r"stovetop|oven|cooktop|garage|roof|attic|ceiling|bin|car) fires?\b|\bflames? (?:is |"
    r"are )?(?:coming|shooting|pouring|leaping|bursting|everywhere|out|from|inside|behind)\b|\bin flames\b|"
    r"\bexplo(?:ded|des|ding|sion|sions)\b|\bblew up\b|\bblown up\b|"
    r"\b(?:loud |big |huge )?(?:bang|boom|explosion|pop)s? (?:came |coming )?(?:from|in|at|inside|behind|near|out of) "
    r"(?:the |my |our )?(?:switchboard|fuse ?box|panel|meter ?box|outlets?|sockets?|power ?points?|breakers?|switch(?:es)?|"
    r"plugs?)\b|đang cháy|bốc cháy|bùng cháy|cháy bùng|cháy nổ|"
    r"cháy lan|hỏa hoạn|hoả hoạn|phát hỏa|phát hoả|bén lửa|lửa (?:bùng|bốc|lan|phụt|tóe|toé)|phát nổ|bị nổ|nổ tung|"
    r"tiếng nổ|nổ lớn|nổ to|nổ bùm|nổ lụp bụp|(?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|bảng điện|cầu dao|phích cắm|"
    r"aptomat) (?:bị )?cháy|cháy (?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|bảng điện|phích cắm|nhà|bếp)|"
    r"(?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|bảng điện|cầu dao|phích cắm|aptomat|bình nóng lạnh|máy nước nóng|bình gas|"
    r"bình ga)(?: \S+)? (?:bị )?nổ\b|"
    r"(?:nhà|phòng) (?:bị |đang )?cháy|(?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|cầu dao|phích cắm|aptomat|máy) (?:có|bốc|"
    r"phát|phụt) lửa|"
    r"\b(?:boc chay|phat no|hoa hoan|chay no)\b)")
# Báo khói / báo CO kêu bíp vì PIN yếu / hết / cần thay. "CO alarm beeping, the battery is new" hay "replaced the battery,
# still beeping" thì vẫn là chuông ĐANG kêu (NGUY HIỂM).
_HZ_BATTERY = re.compile(
    r"\b(?:low|flat|dead|weak|old|dying|drained|needs? (?:a )?(?:new|replac\w*)|replace|change|changing|replacing|swap)\s+"
    r"(?:the\s+|a\s+|its\s+|new\s+)?batter(?:y|ies)\b|\bbatter(?:y|ies)\s+(?:is\s+|are\s+|'s\s+)?(?:low|flat|dead|weak|"
    r"dying|needs?|warning|chirp\w*|beep\w*|running (?:out|low)|going)\b|\blow[- ]batter(?:y|ies)\b"
    r"|hết pin|yếu pin|pin yếu|thay pin|đổi pin|pin (?:sắp |đã |bị )?hết|\b(?:het pin|yeu pin|pin yeu|thay pin|doi pin)\b")
# Tách câu: dấu câu + liên từ đổi ý; trước "không biết / not sure" (câu lấp lửng đứng riêng).
_HZ_BREAK = re.compile(
    r"([.!?;,:|\n()\[\]]|\s[-–—]+\s|\s[-–—]+$|^[-–—]+\s)"
    r"|\b(?:but|however|although|though|whereas|yet|and|then|plus|also|nhưng mà|nhưng|tuy nhiên|mà|và|với lại|"
    r"nhung ma|nhung|tuy nhien|ma|va|voi lai)\b|(?<=rồi)\s+(?=lại\b)|(?<=\broi)\s+(?=lai\b)"
    r"|(?=\b(?:không biết|ko biết|k biết|kh biết|chả biết|chẳng biết|hông biết|not sure|unsure|don'?t know|dont know|"
    r"no idea|wonder\w*|khong biet|ko biet|k biet|cha biet|chang biet|hong biet)\b)")
_HZ_PIVOT = re.compile(r"\b(?:bây giờ|hôm nay|giờ|now|today|bay gio|hom nay|gio)\b")
_HZ_PIVOT_GUARD = frozenset((
    'until', 'till', 'til', 'by', 'from', 'for', 'right', 'just', 'up', 'as', 'of', 'since', 'bao', 'trước', 'đến', 'tới',
    'cho', 'mấy', 'mỗi', 'vài', 'nửa', 'lúc', 'tiếng', 'số', 'bây', 'từ', 'hôm', 'den', 'toi', 'một', 'hai', 'ba', 'bốn',
    'năm', 'sáu', 'bảy', 'tám', 'chín', 'mười', 'may', 'moi', 'vai', 'nua', 'luc', 'tieng', 'so', 'tu', 'truoc', 'mot',
    'bon', 'nam', 'tam', 'chin', 'muoi'))
_HZ_TRIVIAL = frozenset(('now', 'today', 'giờ', 'bây', 'hôm', 'nay', 'right', 'just', 'thì', 'rồi', 'ạ', 'á', 'à', 'nhé',
                         'nha', 'đó', 'đấy', 'luôn', 'already', 'too', 'also', 'ơi', 'gio', 'bay', 'hom', 'thi', 'roi',
                         'nhe', 'luon'))
# Danh sách chỉ gồm từ khoá ("\x00" = 1 từ khoá) nối bằng dấu phẩy, đóng bằng "or / hay" (hay "and / và" ngay trước hết câu
# / điều kiện), hoặc đứng trước ":" / "?" (câu hỏi sàng lọc "gas smell, sparks, smoke: none"): dấu phẩy và "and" trong đó
# thành "\x01" (= "or") để phủ định đầu danh sách / câu trả lời phủ cả danh sách.
_HZ_KW_LIST = re.compile(
    r"\x00+(?:[ \t]*,[ \t]*\x00+)*(?:[ \t]*,)?[ \t]+(?:or|nor|hay|hoặc|hoac)[ \t]+\x00+"
    r"|\x00+(?:[ \t]*,[ \t]*\x00+)+(?=[ \t]*[:?]|[ \t]+[-–—][ \t])"
    r"|\x00+(?:[ \t]*,[ \t]*\x00+)*(?:[ \t]*,)?[ \t]+(?:and|và|va)[ \t]+\x00+(?=[ \t]*(?:[.;!?,\n)]|$|when\b|if\b|"
    r"while\b|khi\b|nếu\b|lúc\b|at all\b|gì\b|nào\b))")
_HZ_WORD = re.compile(r"\x00|\x01|[^\W_]+(?:'[^\W_]+)?")
_HZ_NEG = frozenset((
    "no", "not", "never", "without", "none", "nothing", "nor", "neither", "isn't", "aren't", "wasn't", "weren't", "don't",
    "doesn't", "didn't", "haven't", "hasn't", "hadn't", "can't", "cannot", "couldn't", "won't", "isnt", "arent", "wasnt",
    "werent", "dont", "doesnt", "didnt", "havent", "hasnt", "hadnt", "cant", "couldnt", "wont", "zero", "stopped",
    "ceased", "quit", "không", "chẳng", "chả", "chưa", "hông", "khong", "ko", "k", "kh", "hok", "chua", "hết", "het",
    "đâu", "ngừng", "denies", "denied", "deny", "denying", "nothing's", "nobody", "noone"))
# Sau "nothing / none / neither / nobody (no one)" được thêm động từ to-be: "Nothing is sparking or smoking", "none are
# smoking", "nobody has smelled gas".
_HZ_NEG_SUBJ = frozenset(("nothing", "nothing's", "none", "neither", "nobody", "noone"))
_HZ_NEG_SUBJ_FILL = frozenset(("is", "are", "was", "were", "seems", "seem", "appears", "appear", "to", "be", "has", "been",
                               "currently"))
# Từ được phép đứng giữa từ phủ định và từ khoá. KHÔNG có đại từ / "there" / "is" / "seem" / "think" / "sure": "no i can
# smell gas", "no there is smoke", "I don't think it's a gas leak", "not sure if it's sparking" là báo NGUY HIỂM.
_HZ_FILLER = frozenset((
    "a", "an", "any", "sign", "signs", "evidence", "trace", "traces", "hint", "of", "be", "been", "have", "has", "had",
    "more", "longer", "visible", "even", "at", "all", "real", "obvious", "noticeable", "further", "other", "ever",
    "có", "bị", "thấy", "gì", "dấu", "hiệu", "hiện", "tượng", "nào", "hề", "còn", "cũng", "ngửi", "nghe", "là", "phải",
    "bất", "kỳ", "kì", "tí", "chút", "bao", "giờ", "để", "ý", "xảy", "ra", "phát", "cảm", "giác", "co", "bi", "thay",
    "gi", "dau", "hieu", "nao", "he", "con", "cung", "ngui", "từng", "tung"))
# Động từ giác quan / báo lại sau từ phủ định vẫn là phủ định ("I don't smell gas", "haven't seen any sparks", "didn't smell
# gas this morning", "the tenant hasn't reported any gas leak"); sau chúng "the / that / about / of" cũng được ("didn't see
# the sparks", "not aware of any gas smell"). "can't GET the smoke TO STOP / OUT" thì KHÔNG phải phủ định (_HZ_PERSIST).
_HZ_SENSE = frozenset(("see", "seen", "saw", "notice", "noticed", "smell", "smelled", "smelt", "detect", "detected",
                       "smelling", "seeing", "noticing", "hearing", "feeling", "detecting", "reporting", "having",
                       "feel", "felt", "hear", "heard", "spot", "spotted", "observe", "observed", "find", "found", "get",
                       "got", "experience", "experienced", "report", "reports", "reported", "mention", "mentions",
                       "mentioned", "complain", "complained", "aware"))
_HZ_SENSE_FILL = frozenset(("the", "that", "this", "those", "these", "about", "of"))
_HZ_PERSIST = re.compile(
    r"\b(?:can'?t|cannot|couldn'?t|unable to|not able to|won'?t)\s+(?:seem to\s+)?(?:get|make)\b.{0,40}?"
    r"\b(?:to (?:stop|go away|go out|clear|die down|turn off)|stop(?:ping)?|out\b|rid of|under control|away)")
_HZ_UNDO = frozenset(("sắp", "gần", "sap", "gan", "almost", "nearly", "vẫn", "van"))
_HZ_HET_OK = frozenset(("đã", "da", "cũng", "cung", "đều", "deu", "vừa", "vua", "mới", "moi", "hiện", "là", "la", "giờ",
                        "gio", "nay", "now", "rồi", "roi", "thì", "thi", "qua", "nãy", "sáng", "trưa", "chiều", "tối",
                        "đêm", "sau", "đó"))
_HZ_JOIN = frozenset(("or", "nor", "hay", "hoặc", "hoac", "\x01"))
# Phủ định cùng câu với "lúc trước / cho tới / trừ khi / như vầy / khi tắt máy" ngầm nói HIỆN CÓ: 'No smoke until I
# switched it on', 'never seen sparks like this', "no burning smell when it's off", 'lúc đầu không có mùi khét',
# 'không để ý mùi khét cho đến giờ'. "before or after" / "khi bật máy" / "when I checked" / "từ trước đến giờ không có"
# (= chưa bao giờ có) thì vẫn là phủ định.
_HZ_IMPLY = re.compile(
    r"\b(?:until|till|til|at first|at the start|in the beginning|initially|before|earlier|previously|unless|except|"
    r"(?<!anything )(?<!nothing )(?<!something )like (?:this|that)|this (?:bad|much|often|strong)|"
    r"that (?:bad|much|often|strong))\b"
    r"|\bwhen (?:it'?s |it is |its |they'?re |they are |the \w+ is |it was |i )?(?:turned |switched )?(?:off|unplugged|"
    r"idle|not (?:running|on|in use|plugged in))\b|\bwhile (?:it'?s |it is )?(?:off|unplugged|idle)\b"
    r"|lúc đầu|ban đầu|hồi đầu|mới đầu|lúc trước|trước đó|trước đây|trước giờ|hồi nãy|lúc nãy|ban nãy|cho đến|cho tới|"
    r"(?<!trước )(?:đến|tới) (?:bây )?giờ|(?<!gì )(?:như vầy|như vậy|như thế|như này)|thế này|trừ khi|ngoại trừ|"
    r"(?:khi|lúc) (?:tắt|không (?:bật|dùng|chạy|cắm)|rút (?:điện|phích|ra))")
# Chuyện ĐÃ LÂU (từ hôm qua trở về trước) mà câu không nói gì về hiện tại: 'past' -> 'uncertain' (GẤP + người thật kiểm
# tra), không phải khẩn cấp. "started / bắt đầu / still / worse / hasn't gone" trong cùng câu = đang tiếp diễn -> NGUY HIỂM.
_HZ_PAST = re.compile(
    r"\b(?:yesterday|last (?:night|week|weekend|month|year|time|summer|winter|spring|autumn|fall|monday|tuesday|"
    r"wednesday|thursday|friday|saturday|sunday)|(?:\d+|a|an|one|two|three|four|five|few|couple(?: of)?|several) "
    r"(?:days?|weeks?|months?|years?) ago|the other day|a while (?:ago|back)|in the past|previously|used to|once before)\b"
    r"|hôm qua|hôm kia|hôm trước|mấy hôm trước|bữa trước|mấy ngày trước|tuần trước|tháng trước|năm ngoái|năm trước|"
    r"năm rồi|tuần rồi|tháng rồi|đêm qua|tối qua|chiều qua|sáng qua|trưa qua|lần trước|đợt trước|trước đây|hồi trước|"
    r"dạo trước|lâu rồi|\b\d+ (?:ngày|tuần|tháng|năm) trước")
_HZ_NOW = re.compile(
    r"\b(?:now|currently|still|again|at the moment|today|tonight|keeps?|kept|constantly|continuously|every time|"
    r"whenever|since|ongoing|getting (?:worse|stronger)|this (?:morning|afternoon|evening)|"
    r"worse|stronger|(?:has|have)(?:n'?t| not) (?:gone|stopped|cleared)|not gone|won'?t (?:stop|go away))\b"
    r"|giờ|hiện|đang|vẫn|còn|\blại\b|liên tục|mỗi lần|mỗi khi|hôm nay|\bnay\b|nặng hơn|càng|từ (?:hôm qua|hôm kia|"
    r"hôm trước|tuần trước|tháng trước|tối qua|đêm qua|sáng qua|mấy hôm)")
# "Gas smell started yesterday", "started sparking last week", "Hôm qua bắt đầu có mùi khét": BẮT ĐẦU từ hôm qua = vẫn đang có
# (chỉ khi "started / bắt đầu" gắn với chính từ khoá — "sparked when the aircon started last week" vẫn là chuyện đã qua).
_HZ_STARTED_AFTER = re.compile(r"^\s+(?:has |have |had |just |only )*(?:start(?:ed|s|ing)?|began|begun|begin(?:s|ning)?)\b")
_HZ_STARTED_BEFORE = re.compile(r"\b(?:start(?:ed|s|ing)?|began|begun|begin(?:s|ning)?)\s+(?:to\s+)?(?:\w+\s+)?$"
                                r"|bắt đầu(?: (?:có|bị|thấy|ngửi thấy|nghe thấy|xuất hiện|nghe))?\s+$")
# Câu hỏi có / không ("Is there a gas leak?", "Could it be sparking?", "Có khói không?") và câu GIẢ ĐỊNH ("what should I do
# if I smell gas", "is it dangerous if there is smoke", "nếu có khói thì sao", "có khói thì có nguy hiểm không"): không
# ép khẩn cấp. Câu hỏi về 1 nguy hiểm ĐÃ NÓI là có ("Is the smoke dangerous?", "smoke is coming out, is it normal?",
# "ổ cắm bốc khói có nguy hiểm không") vẫn là NGUY HIỂM.
_HZ_Q_START = re.compile(
    r"^\s*(?:(?:so|and|but|also|ok|okay|hi|hello|hey|please|um|uh|well|sorry)\W+)*(?:(?:is|are|was|were|could|can|should|"
    r"would|will|do|does|did|has|have|might|may|must|shall)\s+(?:it|this|there|i|we|smoke|gas)\b|"
    r"how (?:dangerous|bad|serious|risky|safe)\b)")
# Câu hỏi mà nguy hiểm đã được nói là CÓ: "is this smoke dangerous", "is it normal that sparks come out", "is it ok to
# come today because there are sparks", "is it safe with sparks coming out".
_HZ_Q_DET = re.compile(r"\b(?:the|my|our|this|these|those|your)\s+$")
_HZ_Q_PRESUPPOSE = re.compile(r"\b(?:that|because|cause|coz|since|with|vì|bởi)\b")
_HZ_Q_VI = re.compile(
    r"^\s*(?:(?:vậy|thế|dạ|cho (?:em|anh|chị|mình|tôi) hỏi|anh ơi|chị ơi|em ơi|shop ơi|ad ơi)\s+)*(?:có phải(?: là)?|"
    r"liệu(?: có)?|có bị|có)\b.*\b(?:không|ko|k|hông|hok|chưa|chăng|hả|hở)(?:\s+(?:ạ|ah|à|vậy|nhỉ|nhé|vậy ạ))?\s*$")
_HZ_Q_VI_FRAME = re.compile(
    r"\b(?:có (?:nguy hiểm|sao|an toàn|bị sao|bị gì|làm sao|ảnh hưởng|hại|độc|nên)(?: gì)?|nguy hiểm|an toàn|có sao|được|"
    r"nên|cần)\s+(?:không|ko|k|hông|hok|chứ|ạ)\b|\bphải làm (?:sao|gì)|\blàm (?:sao|gì) (?:bây giờ|giờ|đây)|\bthì sao\b|"
    r"\bcó nên\b|\bliệu\b")
# Giả định / lo sợ ("if there is smoke", "nếu có khói", "không dám bật vì sợ chập điện", "afraid of a gas leak"): không
# phải đang có -> 'hypothetical' (= 'uncertain', không phải việc thường).
_HZ_HYPO = frozenset(('if', 'nếu', 'lỡ', 'nhỡ', 'suppose', 'supposing', 'giả', 'neu', 'sợ', 'afraid', 'fear', 'scared'))
_HZ_HYPO_FILL = frozenset((
    'there', 'is', 'are', "there's", "it's", 'its', 'it', 'i', 'we', 'you', 'they', 'he', 'she', 'someone', 'anyone', 'a',
    'an', 'any', 'some', 'the', 'ever', 'still', 'again', 'be', 'been', 'was', 'were', 'smell', 'smells', 'see', 'sees',
    'notice', 'get', 'gets', 'start', 'starts', 'happen', 'happens', 'to', 'my', 'our', 'your', 'this', 'that', 'more',
    'even', 'có', 'bị', 'thấy', 'ngửi', 'nghe', 'mà', 'như', 'xảy', 'ra', 'lại', 'còn', 'vẫn', 'phát', 'hiện', 'nhà',
    'mình', 'em', 'anh', 'chị', 'sử', 'co', 'bi', 'thay', 'of', 'about', 'might', 'could', 'may', 'will', 'would')) | _HZ_NEG
_HZ_FEAR = frozenset(('sợ', 'afraid', 'fear', 'scared'))
_HZ_UNSURE = frozenset(('sure', 'unsure', 'know', 'knows', 'wonder', 'wondering', 'idea', 'tell', 'check', 'checking',
                        'see', 'ask', 'asking', 'clear', 'certain', 'determine', 'out', 'biết', 'biet'))
# Ngay sau từ khoá: "gas smell is gone", "the sparks stopped", "mùi gas hết rồi", "khói tan rồi" = đã HẾT.
_HZ_GONE_AFTER = re.compile(
    r"^(?:\s+(?:smell|odou?r|is|has|have|had|was|were|been|now|already|completely|all|totally|finally|since|then))*\s+"
    r"(?:gone|stopped|cleared|went away|gone away|disappeared|subsided|dissipated|faded|died down|no longer there|"
    r"ruled out|not present|not detected|absent)\b")
_HZ_GONE_AFTER_VI = re.compile(r"^(?:\s+(?:đã|cũng|thì|giờ|bây giờ|nay|đều|da|cung|thi|gio|bay gio|deu))*\s+"
                               r"(?:hết(?: hẳn)? rồi|hết hẳn|đã hết|tan(?: hết)?(?: rồi)?|không còn(?: nữa)?|"
                               r"het(?: han)? roi|het han|da het|khong con(?: nua)?)\b")
# Câu KHÔNG có từ khoá kết thúc / lật lại nguy hiểm của câu trước. Câu trả lời 1 chữ ("no" / "yes" / "không" / "có") chỉ
# tính khi câu trước là câu hỏi sàng lọc ("Gas smell? No", "Sparks: yes").
_HZ_GONE = re.compile(
    r"^(?:(?:so|now|today|tonight|giờ|bây giờ|hôm nay|nay|thì|đã|cũng|sau đó)\s+)*"
    r"(?:(?:(?:it|they|that|the (?:smell|smoke|sparks?|sparking|odou?r|fumes|water|flooding|fire|flames?)|smell|smoke|"
    r"sparks?)(?:'s|'re| is| are| has| have| had| was| were)?\s+)?(?:(?:all|completely|finally|now|already)\s+)*"
    r"(?:gone|stopped|cleared(?: up)?|went away|gone away|disappeared|subsided|dissipated|faded(?: away)?|died down|"
    r"not there|no longer there|out)(?:\s+(?:now|already|completely|since|away|today))*"
    r"|(?:not|no)\s+(?:any ?more|longer|now|today|since)|none (?:now|today|anymore|any more)"
    r"|(?:it|they|there)(?:'s| is| are| does| do)(?:n't| not)(?:\s+(?:any ?more|now|today))*"
    r"|(?:it|they|there) (?:isn't|isnt|aren't|arent|doesn't|doesnt|don't|dont)(?:\s+(?:any ?more|now|today))*"
    r"|(?:(?:đã|cũng|thì)\s+)*(?:hết(?: hẳn)?(?:\s+(?:mùi|khói|tia lửa|chập|giật|ngập|nước|smell|smoke|sparks?))?|tan|"
    r"khói tan|mùi tan|nước rút|(?:không|ko|k|hông) còn(?:\s+(?:mùi|khói|tia lửa|thấy|bị|ngửi thấy|nữa))?|"
    r"(?:không|ko) (?:bị|thấy|có) nữa)(?:\s+(?:rồi|nữa|ạ|á|à|luôn|hẳn|hết|đâu))*)$"
    r"|^(?:giờ|bây giờ|hôm nay|nay)(?:\s+(?:thì|lại|đã|cũng|đều))*\s+(?:không|ko|hông|k)(?:\s+(?:có|bị|thấy|còn|nữa|rồi|"
    r"ạ|á|à|gì))*$"
    r"|^(?:(?:so|and)\s+)?(?:(?:still|again|now|today|so far)\s+)+(?:nothing|none|no signs?(?: of (?:it|them|any))?|"
    r"not (?:there|present|happening))(?:\s+(?:now|today|so far|yet|since))*$"
    r"|^(?:nothing|none|no signs?(?: of (?:it|them|any))?)\s+(?:now|today|since|so far|yet|still|again)"
    r"(?:\s+(?:now|today|yet))*$"
    r"|^(?:(?:and|so|but)\s+)?(?:(?:it|they|that)\s+)?(?:(?:has|have|had|did|does|do)(?:n'?t| not)|never)\s+"
    r"(?:come back|came back|returned?|happen(?:ed)? again|start(?:ed)? again|been back|recurr?(?:ed)?)"
    r"(?:\s+(?:since|yet|now|today|again))*$"
    r"|^(?:(?:đã|cũng|thì|giờ|nay|vẫn)\s+)*(?:chưa|không|ko|hông) (?:bị|có|thấy) lại(?:\s+(?:nữa|rồi|ạ|á|à|luôn|lần nào))*$"
    r"|^(?:vẫn|giờ vẫn|nay vẫn)(?:\s+(?:thì|là))?\s+(?:không|chưa|ko|hông)\s+(?:có|bị|thấy)(?:\s+(?:gì|nữa|ạ|á|à|cả))*$"
    r"|^(?:(?:gio|bay gio|hom nay|nay|thi|da|cung|van)\s+)*(?:het(?: han)?(?:\s+(?:mui|khoi|tia lua|chap|giat|ngap|nuoc))?|"
    r"khong con(?:\s+(?:mui|khoi|tia lua|thay|bi|nua))?|(?:khong|ko|chua) (?:bi|thay|co) (?:nua|lai))(?:\s+(?:roi|nua|a|"
    r"luon|han|het|dau))*$"
    r"|^(?:gio|bay gio|hom nay|nay|van)(?:\s+(?:thi|lai|da|cung|deu))*\s+(?:khong|ko|hong|k|chua)\s+(?:co|bi|thay|con)"
    r"(?:\s+(?:nua|roi|a|gi))*$")
_HZ_BACK = re.compile(
    r"^(?:(?:so\s+)?(?:(?:now|today|tonight|this (?:morning|afternoon|evening))\s+)?"
    r"(?:(?:i|we|you)\s+(?:do|can|did|could)(?:\s+(?:still|now|again|really|definitely|actually|clearly|also))?"
    r"(?:\s+(?:smell|see|notice|hear|feel)(?:\s+(?:it|them|some|one))?)?"
    r"|(?:i|we|you)\s+(?:(?:still|now|again|also)\s+)?(?:smell|see|notice|hear|feel)\s+(?:it|them|some|one)"
    r"|there(?:'s|'re| is| are)(?:\s+(?:some|one|a lot|more))?"
    r"|(?:it|they)(?:'s|'re| is| are| does| do| has| have| did)(?:\s+(?:back|returned|started again|come back))?"
    r"|(?:it|they|the (?:smell|smoke|sparks?|sparking))\s+(?:came back|come back|is back|are back|returned|"
    r"started again|happened again)|(?:came|comes|come|is|are|it'?s) back|back again|started again|returned)"
    r"(?:\s+(?:now|today|tonight|again|too|as well|back|there))*"
    r"|(?:now|today|tonight)(?:\s+(?:again|too|as well))+|again(?:\s+(?:now|today|tonight))?"
    r"|found (?:it|them|some|one|a few|lots|plenty)"
    r"|(?:(?:it|they)(?:'s|'re| is| are)\s+)?still(?:\s+(?:happening|there|going(?: on)?|on|going|now|today))*"
    r"|(?:vẫn còn|vẫn|còn)(?:\s+(?:bị|có|thấy))?(?:\s+(?:rồi|nữa|ạ|á|à|luôn|lắm|nhiều))*"
    r"|(?:thì\s+)*(?:giờ|bây giờ|hôm nay|nay|tối nay|sáng nay|lại|sau đó)(?:\s+(?:thì|lại|đã|mới|cũng))*\s+"
    r"(?:có|bị|thấy|ngửi thấy|nghe thấy|xuất hiện|lại)(?:\s+(?:rồi|lại|nữa|ạ|á|à|luôn|nhiều|mùi|lắm|rất nhiều))*"
    r"|(?:có lại|bị lại|lại có|lại bị|lại thấy|thấy lại)(?:\s+(?:rồi|nữa|ạ|á|à|luôn))*"
    r"|(?:thi\s+)*(?:gio|bay gio|hom nay|nay|toi nay|sang nay|lai|sau do)(?:\s+(?:thi|lai|da|moi|cung))*\s+"
    r"(?:co|bi|thay|ngui thay|nghe thay|xuat hien|lai)(?:\s+(?:roi|lai|nua|a|luon|nhieu|mui|lam))*"
    r"|(?:co lai|bi lai|lai co|lai bi|lai thay|thay lai|van con|van bi|van co)(?:\s+(?:roi|nua|a|luon|lam|nhieu))*)$")
_HZ_REPORT = (r"(?:(?:the )?(?:customer|client|caller|tenant|owner|they|he|she|khách(?: hàng)?|anh ấy|chị ấy)\s+"
              r"(?:says?|said|confirms?|confirmed|answered|reports?|reported|nói|bảo|trả lời|xác nhận)\s+(?:là\s+)?)?")
_HZ_YES = re.compile(r"^" + _HZ_REPORT + r"(?:yes|yeah|yep|yup|có|có ạ|dạ có|vâng có|có á|có luôn|đúng rồi|still)$")
_HZ_NO = re.compile(r"^" + _HZ_REPORT + r"(?:no|nope|none|nil|n/a|nothing|không|ko|k|hông|không có|ko có|không ạ|"
                    r"dạ không|not that (?:i|we)(?:'m|'re|'ve| am| are| have)? (?:know|knew|aware|seen|noticed|can tell|"
                    r"could tell|remember)(?: of)?|(?:not|none|nothing) (?:seen|noticed|detected|observed|found|present)|"
                    r"nil seen|no signs?(?: of (?:it|any))?|không thấy|chưa thấy|không thấy gì)$")
# Câu KHÔNG có từ khoá đến SAU 1 phủ định / chuyện đã qua mà NHẮC LẠI nguy hiểm (bản phân tích cũ chỉ khớp nguyên câu
# _HZ_BACK nên sót "today it is stronger", "again this morning", "still smells a bit", "hasn't gone", "sáng nay vẫn còn",
# "sáng nay lại chập"):
#   _HZ_AGAIN       luôn là nhắc lại (kể cả câu có "không / won't"): came back, won't stop, hasn't gone, getting worse,
#                   stronger, can't get it to stop, vẫn còn, chưa hết, lại có / lại bị / lại chập, càng, nặng hơn...
#   _HZ_AGAIN_SOFT  still / again / keeps / vẫn / lại ... — trừ khi câu tự phủ định ("heater still not working") hay chỉ là
#                   chuyện đặt lịch ("still waiting for a quote", "vẫn cần thợ qua").
#   _HZ_LATER       now / today / tonight / giờ / nay ... — chỉ lật 1 PHỦ ĐỊNH thành 'uncertain', trừ khi câu tự phủ định,
#                   là chuyện đặt lịch ("can you come today?") hay nói đã ổn ("it's fine now").
# Chuyện đã qua / câu hỏi + _HZ_AGAIN / _HZ_AGAIN_SOFT -> NGUY HIỂM; phủ định + bất kỳ loại nào -> 'uncertain'.
_HZ_AGAIN = re.compile(
    r"\b(?:came back|comes? back|coming back|is back|are back|returned|started again|happening again|"
    r"(?<!anything )(?<!nothing )stronger|(?<!anything )(?<!nothing )worse|worsening|won'?t (?:stop|go away|clear)|"
    r"(?:not|isn'?t|aren'?t) stopping|non ?stop|again and again|on and off|recurr\w*|can'?t (?:stop|get (?:it|them|rid))|"
    r"cannot (?:stop|get)|"
    r"doesn'?t (?:stop|go away)|hasn'?t (?:stopped|gone|cleared|gone away)|haven'?t (?:stopped|gone|cleared)|not gone|"
    r"never (?:stops|went away|goes away)|getting (?:bigger|more)|more and more|can'?t get .{0,30}?(?:to stop|out|rid))\b"
    r"|vẫn (?:còn|bị|có|thấy|chưa (?:hết|tan|ngừng|dứt)|không (?:hết|tan|ngừng|dứt)|ngửi|nghe|nồng|nặng|chập|xì|bốc|khét)"
    r"|\blại (?:bị|có|thấy|chập|xì|rò|bốc|nổ|khét|ngửi|nghe|xuất hiện|nặng|nồng)|(?:bị|có|thấy|chập|xì|bốc|khét|nổ) lại\b"
    r"|càng|nặng hơn|nồng hơn|mạnh hơn|tái lại|(?:không|chưa|ko) (?:hết|tan|ngừng|dứt)|(?:không|ko|chả|chẳng) (?:tắt|dập|"
    r"ngắt|làm) (?:\S+ )?(?:được|nổi)"
    r"|\bvan (?:con|bi|co|thay|chua (?:het|tan|ngung|dut)|khong (?:het|tan|ngung|dut)|ngui|nong|nang|chap|xi|boc|khet)\b"
    r"|\blai (?:bi|co|thay|chap|xi|ro|boc|no|khet|ngui|nghe|xuat hien|nang|nong)\b|\b(?:bi|co|thay|chap|xi|boc|khet|no) lai\b"
    r"|\bcang\b|\b(?:nang|nong|manh) hon\b|\btai lai\b|\b(?:khong|chua|ko) (?:het|tan|ngung|dut)\b")
_HZ_AGAIN_SOFT = re.compile(r"\b(?:still|again|keeps|kept|constantly)\b|vẫn|\blại\s*$|\blại (?:rồi|nữa)|\blai\s*$|"
                            r"\blai (?:roi|nua)\b|\bvan\s*$")
_HZ_LATER = re.compile(r"\b(?:now|today|tonight|this (?:morning|afternoon|evening)|right now)\b|bây giờ|^giờ\b|"
                       r"\bgiờ (?:thì|lại|vẫn|có|bị|đã|thấy|còn)\b|hôm nay|(?:sáng|trưa|chiều|tối|đêm) nay|^nay\b"
                       r"|\bbay gio\b|^gio\b|\bgio (?:thi|lai|van|co|bi|da|thay|con)\b|\bhom nay\b|"
                       r"\b(?:sang|trua|chieu|toi|dem) nay\b|^nay\b")
# Câu CHỈ gồm mốc thời gian hiện tại ("... last night and this morning", "hôm qua có mùi gas, sáng nay nữa"): nguy hiểm
# vẫn đang có -> nhắc lại MẠNH.
_HZ_TIME_ONLY = re.compile(
    r"^(?:(?:and|also|even|again|plus|cả|và|lại|cũng|ca|va|lai|cung)\s+)*(?:now|today|tonight|this (?:morning|afternoon|"
    r"evening)|right now|just now|hôm nay|sáng nay|trưa nay|chiều nay|tối nay|đêm nay|bây giờ|giờ|hom nay|sang nay|"
    r"trua nay|chieu nay|toi nay|dem nay|bay gio)(?:\s+(?:too|also|again|as well|nữa|cũng vậy|cũng thế|cũng có|cũng bị|"
    r"luôn|nua|cung vay|cung the|cung co|cung bi|luon))*$")
_HZ_ANY_NEG = re.compile(r"\b(?:no|not|never|none|nothing|without|cannot|(?:is|are|was|were|do|does|did|have|has|had|ca|"
                         r"could|would|wo|should)n'?t)\b|\b(?:không|chưa|chẳng|chả|ko|hông|khong|chua|chang|cha|hong)\b")
_HZ_SCHEDULE = re.compile(
    r"\b(?:come|coming over|visit|book\w*|available|availability|appointment|schedule\w*|slot|quote|fix|fixed|repair\w*|"
    r"send|technician|tech|electrician|plumber|sparky|tradie|inspect\w*|wait\w*|need|needs|want|wants|please|asap|"
    r"call|price|cost|free|work(?:ing|s)?|fine|ok|okay|normal|good|thanks?|thank you|cheers|warranty)\b"
    r"|\b(?:qua|ghé|sửa|báo giá|đặt lịch|hẹn|thợ|được không|cũng được|giá|chờ|đợi|cần|muốn|bình thường|ổn|cảm ơn|"
    r"bảo hành|giờ nào|lúc nào|mấy giờ|giờ hành chính|lịch)\b"
    r"|\b(?:sua|bao gia|dat lich|tho|duoc khong|binh thuong|cam on|bao hanh|muon|ghe)\b")
# Câu nhắc lại "still / again / vẫn" mà có tên THIẾT BỊ khác ("the aircon still makes noise") có thể nói về thiết bị đó:
# chỉ tính là nhắc lại yếu (phủ định -> 'uncertain'; chuyện đã qua giữ 'uncertain', không nâng lên khẩn cấp).
_HZ_DEVICE = re.compile(r"\b" + _HZ_SRC_WORDS)
# Chuông báo khói / báo cháy kêu MỖI KHI nấu ăn / tắm (hơi nước), hay nói rõ nguyên nhân là nấu ăn: không phải nguy hiểm.
# "is going off while cooking" / "đang kêu khi nấu" (ĐANG kêu, chưa rõ vì sao) vẫn là NGUY HIỂM.
_HZ_ALARM_NUISANCE = re.compile(
    r"(?<!\bnot )(?<!n't )(?<!\bnever )(?<!\bno )\b(?:whenever|every ?time|each time|because of|due to|caused by|"
    r"set off by|triggered by|from)\s+(?:i\s+|we\s+|you\s+|"
    r"someone\s+|they\s+|the\s+|my\s+|our\s+)?(?:\w+\s+)?(?:cook(?:ing|s|ed)?|fr(?:y|ying|ied)|toast(?:ing|ed)?|"
    r"shower(?:ing|s)?|steam\w*|bak(?:e|ing)|grill(?:ing)?|bbq|vap(?:e|ing)|burnt toast)\b"
    r"|\bwhen\s+(?:i|we|you|someone|they)(?:'re|'m)?\s+(?:(?:was|were|am|are|is)\s+)?(?:cook(?:ing)?|fry(?:ing)?|"
    r"toast(?:ing)?|shower(?:ing)?|bak(?:e|ing)|grill(?:ing)?|vap(?:e|ing))\b"
    r"|\b(?:cooking|toast|steam|shower|vaping)(?: smoke)?\s+(?:sets?|setting|triggers?|triggering|triggered)\b"
    r"|(?<!phải )(?<!không )(?:mỗi khi|mỗi lần|hễ|cứ|do|vì|tại)\s+(?:\S+\s+)?(?:nấu|chiên|xào|nướng|rán|tắm|hơi nước)"
    r"|(?<!phai )(?<!khong )\b(?:moi khi|moi lan|he|do|vi|tai)\s+(?:\S+\s+)?(?:nau|chien|xao|nuong|ran|tam|hoi nuoc)\b")
# Yêu cầu KIỂM TRA xem có nguy hiểm không ("can you check for a gas leak?", "please test for any sparks", "kiểm tra giúp
# xem có rò rỉ gas không"): chưa ai nói là CÓ -> 'question' (= 'uncertain', người thật gọi hỏi). "check the gas leak" /
# "come fix the gas leak" (đã nói là có) vẫn là NGUY HIỂM.
_HZ_CHECK_FOR = re.compile(
    r"\b(?:check|test|inspect|look|screen|scan|assess)(?:s|ed|ing)?\s+(?:(?:it|them|everything|things|the place|the house|"
    r"again)\s+)?(?:for|if there(?:'s| is| are)?|whether there(?:'s| is| are)?|if (?:it'?s|it is|its))\s+"
    r"(?:(?:a|an|any|some|possible|potential|signs? of|evidence of|traces? of)\s+)*$"
    r"|(?:kiểm tra|kiem tra|xem giúp|xem giùm|xem dùm)(?:\s+(?:giúp|giùm|dùm|lại|giup|gium|dum|lai))*\s+"
    r"(?:xem\s+)?(?:có|co)\s+(?:(?:bị|bi)\s+)?$")
# Câu SÀNG LỌC do AI / nhân viên ghi ("Asked about gas smell", "checked for sparks", "hỏi khách về mùi gas"): là câu hỏi,
# câu trả lời ngay sau ("none", "customer says no", "khách nói không" / "yes", "có") quyết định.
_HZ_SCREEN = re.compile(
    r"^\s*(?:(?:i|we|staff|ai)\s+)?(?:(?:asked|checked|screened)\s+(?:(?:the\s+)?(?:customer|client|caller|them)\s+)?"
    r"(?:about|for|if|whether|re)|(?:đã\s+)?(?:hỏi|kiểm tra)(?:\s+(?:khách|khách hàng|lại|anh|chị))?(?:\s+(?:về|xem))?)"
    r"(?:\s+(?:there|there's|is|are|any|a|an|some|the|có|bị))*\s*$")
_HZ_NOUNS = (('gas', re.compile(r"\bgas|\bmùi|\bsmell|\bodou?r")), ('burning', re.compile(r"\bmùi|\bsmell|\bodou?r")),
             ('smoke', re.compile(r"\bsmok|khói")), ('sparks', re.compile(r"\bspark|tia lửa|chập")),
             ('shock', re.compile(r"\bshock|giật")), ('water', re.compile(r"\bwater|\bflood|ngập|nước")),
             ('fire', re.compile(r"\bfire|\bflame|lửa|cháy")), ('co', re.compile(r"\balarm|báo")),
             ('alarm', re.compile(r"\balarm|\bdetector|báo")))


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('technical_request_job',
        "Create a REAL job request on the business's dispatch board (status: waiting to be assigned). Collect first: the "
        "customer's name and phone number, the full service address, what is wrong, the preferred day and part of day, and "
        "how urgent it is. The team calls back to confirm a time — it is NOT scheduled. Never promise an arrival time or "
        "price. Use urgency 'emergency' for danger happening now (gas smell, sparks, smoke from an appliance, fan or "
        "anything electrical — a range hood, exhaust fan or oven that is itself smoking or sparking counts — water near "
        "power, electric shock, a smoke / CO / gas alarm going off) — not for a range hood that doesn't clear cooking "
        "smoke, a chimney or smoke alarm battery job, a leak or flood from a toilet, sink or appliance with no power "
        "nearby, hot weather ('burning hot', 'scorching'), or a danger the customer clearly rules out. A danger that is "
        "mentioned but not clearly ruled out (it happened before, they are unsure, they only ask, or they said it was gone "
        "but then 'now', 'still', 'again', 'worse') is 'urgent' at least: the team is alerted to call and check.",
        {'customer_name': {'type': 'string', 'description': "Customer's name."},
         'phone': {'type': 'string', 'description': "Customer's phone number."},
         'address': {'type': 'string', 'description': 'Full service address: street number + street, suburb/district, city.'},
         'problem': {'type': 'string', 'description': "What's wrong, in the customer's words (device, symptoms, since when)."},
         'preferred_date': {'type': 'string', 'description': 'Preferred day YYYY-MM-DD (business local date), if the customer has one.'},
         'preferred_window': {'type': 'string', 'enum': list(WINDOWS), 'description': 'Preferred part of the day.'},
         'urgency': {'type': 'string', 'enum': list(URGENCY), 'description': "normal, urgent (needs it soon) or emergency (danger now)."},
         'service_id': {'type': 'integer', 'description': 'Optional service_id from the SERVICE PRICE LIST if one clearly matches.'}},
        ['address', 'problem']),
    _fn('technical_job_status',
        "Check the status of THIS customer's own job requests (made in this chat, or under their verified phone number): "
        "waiting, assigned, on the way (with a live tracking link), or completed. If it fails with not_verified, say "
        "nothing about any job and pass on the message.",
        {'job_id': {'type': 'integer', 'description': 'Optional job number the customer mentions.'}}),
]
MANAGE_TOOLS = {'technical_job_status'}

PROMPT_RULES = {
    'en': ("FIELD SERVICE RULES: You take job requests; the team decides who goes and when. Before technical_request_job get "
           "the customer's name, phone number, full address (street number, street, suburb/city), what's wrong, preferred "
           "day + morning/afternoon/evening, and how urgent. Never promise an arrival time, a price for the repair, a "
           "specific person or that the job is booked — say the team will call to confirm. Don't diagnose faults or give "
           "repair instructions. DANGER happening now (gas smell, sparks, smoke from an appliance, fan or anything "
           "electrical — even a range hood or exhaust fan that is itself smoking — water near power, electric shock, a "
           "smoke / CO / gas alarm going off): first tell them to get to a safe place and "
           "call the emergency number in the facts, then create the request with urgency 'emergency'. A danger that is "
           "mentioned but not clearly ruled out — it happened before, they are unsure, or they only ask whether something "
           "is dangerous — is not an emergency but never a normal job: use urgency 'urgent' (a person from the team checks "
           "it) and tell them that if they smell gas or see sparks or smoke right now they should leave and call the "
           "emergency number. If they ruled a danger out and then say 'now', 'still', 'again', 'worse' or 'came back', "
           "treat it as not ruled out. A range hood that doesn't clear cooking smoke, a chimney or smoke alarm battery job, "
           "a toilet / sink / appliance leak with no power nearby, hot weather ('burning hot', 'scorching'), or a danger "
           "the customer clearly rules out, is a normal job."),
    'vi': ("LUẬT DỊCH VỤ KỸ THUẬT: Em chỉ NHẬN yêu cầu; đội kỹ thuật quyết định ai đi và lúc nào. Trước khi gọi "
           "technical_request_job cần: tên + SĐT khách, địa chỉ đầy đủ (số nhà, đường, phường/quận, thành phố), hỏng gì, ngày "
           "+ buổi mong muốn, mức độ gấp. Không hứa giờ tới, giá sửa, người làm hay \"đã đặt lịch\" — nói đội sẽ gọi xác nhận. "
           "Không chẩn đoán hay hướng dẫn tự sửa. NGUY HIỂM đang xảy ra (mùi gas, tia lửa, khói từ thiết bị / quạt / đồ "
           "điện — kể cả máy hút mùi, quạt hút TỰ bốc khói — nước gần điện, điện giật, báo khói / báo gas / báo CO đang "
           "kêu): trước hết bảo khách ra chỗ an toàn và gọi số khẩn cấp "
           "trong dữ kiện, rồi tạo yêu cầu với urgency 'emergency'. Có nhắc nguy hiểm mà KHÔNG loại trừ rõ (đã từng bị, "
           "khách không chắc, hay chỉ hỏi có nguy hiểm không): không phải khẩn cấp nhưng cũng KHÔNG phải việc thường — dùng "
           "urgency 'urgent' (nhân viên gọi kiểm tra) và dặn: nếu ngay lúc này ngửi thấy gas, thấy tia lửa hay khói thì ra "
           "chỗ an toàn và gọi số khẩn cấp. Khách nói đã hết / không có rồi lại nói \"giờ\", \"vẫn\", \"lại\", \"nặng hơn\" "
           "thì coi như CHƯA loại trừ. Máy hút mùi không hút hết khói bếp, ống khói, pin báo khói, bồn cầu / máy giặt tràn "
           "nước không gần điện, trời nóng (\"nóng như đốt\", \"burning hot\") hay nguy hiểm khách nói rõ là KHÔNG có là "
           "việc thường."),
}


def _err(msg):
    return ai_packs.PackError(msg)


def _hz_norm(text):
    return unicodedata.normalize('NFC', str(text or '')).replace('\u2019', "'").replace('\u2018', "'").lower()


def _hz_statements(t):
    """[(câu, dấu kết thúc)] — tách ở dấu câu / liên từ, rồi TRƯỚC now / today / giờ / hôm nay (câu chỉ còn "now" / "rồi"
    do tách TRƯỚC now / giờ gộp lại câu trước: "I smell gas now", "No smoke now" vẫn là 1 câu). Sau dấu câu / liên từ thì
    "now / today / giờ" đứng riêng là 1 câu NHẮC LẠI ("No gas smell, but now", "Không có mùi gas, giờ")."""
    out, pieces, pos = [], [], 0
    for m in _HZ_BREAK.finditer(t):
        pieces.append((t[pos:m.start()], (m.group(1) or '').strip()))
        pos = m.end()
    pieces.append((t[pos:], ''))
    for j, (text, delim) in enumerate(pieces):
        subs, last = [], 0
        for m in _HZ_PIVOT.finditer(text):
            prev = (re.findall(r"[^\W_]+", text[:m.start()]) or [''])[-1]   # chữ ngay trước: "until now", "2 giờ"
            if not prev or prev in _HZ_PIVOT_GUARD or prev.isdigit():
                continue
            if m.group() == 'giờ' and re.match(r"\s*giấc", text[m.end():]):
                continue
            subs.append(text[last:m.start()])
            last = m.start()
        subs.append(text[last:])
        for i, s in enumerate(subs):
            words = re.findall(r"[^\W_]+", s)
            d = delim if i == len(subs) - 1 else ''
            if out and words and all(w in _HZ_TRIVIAL for w in words) and (i > 0 or j == 0):
                out[-1] = (out[-1][0] + ' ' + s.strip(), d or out[-1][1])
            elif words:
                out.append((s.strip(), d))
            elif d and out:
                out[-1] = (out[-1][0], d)
    return out


def _hz_negated(st, start):
    """Từ khoá bắt đầu ở st[start] bị PHỦ ĐỊNH rõ trong câu ('no gas smell', "I don't smell gas", 'không có mùi khét',
    'hết mùi gas', 'No burning smell or sparks', 'Nothing is sparking or smoking'). Không chắc -> False (= có)."""
    toks = _HZ_WORD.findall(_HZ.sub(' \x00 ', st[:start]))
    for i in range(len(toks) - 1, 0, -1):   # "no one / no-one has smelled gas", "không ai bị điện giật" = "nobody ..."
        if (toks[i] == 'one' and toks[i - 1] == 'no') or (toks[i] == 'ai' and toks[i - 1] in ('không', 'chưa', 'chẳng',
                                                                                             'ko', 'khong', 'chua')):
            toks[i - 1:i + 1] = ['nobody']
    neg = max((i for i, t in enumerate(toks) if t in _HZ_NEG), default=-1)
    if neg < 0 or sum(t != '\x00' and t not in _HZ_JOIN for t in toks[neg + 1:]) > 5:
        return False
    prev = [t for t in toks[:neg] if t not in ('phải', 'phai', 'là', 'la')][-1:]
    if prev and (prev[0] in _HZ_NEG or prev[0] in _HZ_UNDO):
        return False   # phủ định kép / "gần như": "không phải không có khói", "vẫn chưa hết mùi gas", "almost no smoke"
    if toks[neg] in ('hết', 'het') and neg > 0 and toks[neg - 1] not in _HZ_HET_OK:
        return False   # 'hết' sau động từ = "toàn bộ": "nước tràn hết ngập nhà"
    joined, sensed = False, False
    for t in toks[neg + 1:]:
        if t == '\x00':
            joined = True
        elif t in _HZ_JOIN:   # "No burning smell or sparks", "Not sparking, smoking, or flooding" (dấu phẩy Oxford)
            joined = False
        elif joined:
            return False
        elif t in _HZ_SENSE:
            sensed = True
        elif not (t in _HZ_FILLER or (sensed and t in _HZ_SENSE_FILL)
                  or (toks[neg] in _HZ_NEG_SUBJ and t in _HZ_NEG_SUBJ_FILL)):
            return False
    return not joined


def _hz_hypothetical(st, start, end, question):
    """Từ khoá nằm trong vế GIẢ ĐỊNH / LO SỢ ("if there is smoke", "nếu có khói", "có khói thì ... không?", "vì sợ chập
    điện", "what do I do if the outlet starts sparking again?") — không phải đang có."""
    toks = _HZ_WORD.findall(st[:start])
    idx = max((i for i, t in enumerate(toks) if t in _HZ_HYPO or (t == 'case' and i and toks[i - 1] == 'in')), default=-1)
    if idx >= 0 and not (toks[idx] == 'if' and idx and toks[idx - 1] in _HZ_UNSURE):
        rest = toks[idx + 1:]
        if (toks[idx] in _HZ_FEAR and rest[:1] in (['there'], ["there's"])
                and not any(t in ('might', 'may', 'could', 'will', 'would') for t in rest)):
            return False   # "I'm scared there's smoke coming out of the wall" = khách báo ĐANG có
        if len(rest) <= 6 and all(t in _HZ_HYPO_FILL or t == '\x00' for t in rest):
            return True   # "if there is smoke", "nếu có khói", "in case I smell gas" (không phải "not sure if it's sparking")
        if question and len(rest) <= 8 and not any(t in _HZ_NEG for t in rest):
            return True   # câu HỎI: "what do I do if the outlet starts sparking again?" (câu kể "if I flip the switch
            #               there are sparks" vẫn là đang có)
    return bool(question and re.search(r"\bthì\b", st[end:]))   # "có khói thì có nguy hiểm không?"


def _hz_state(st, m, delim, screen=False):
    """present | negated | past | question | hypothetical cho 1 từ khoá (m) trong câu st (screen: câu hỏi sàng lọc)."""
    start, end = m.start(), m.end()
    if screen:
        return 'question'
    qstart = _HZ_Q_START.match(st)
    # "Có khói không?" là hỏi; "có tia lửa ở ổ cắm có sao không" là báo CÓ tia lửa rồi hỏi có sao không
    vi_q = bool(_HZ_Q_VI.match(st)) and not _HZ_Q_VI_FRAME.search(st[end:])
    question = delim == '?' or bool(qstart) or vi_q or bool(_HZ_Q_VI_FRAME.search(st))
    if _hz_hypothetical(st, start, end, question):
        return 'hypothetical'
    if (qstart and start >= qstart.end() and not _HZ_Q_DET.search(st[:start])
            and not _HZ_Q_PRESUPPOSE.search(st[qstart.end():start])) or vi_q:
        return 'question'
    if _HZ_CHECK_FOR.search(st[:start]):
        return 'question'   # "can you check for a gas leak?", "kiểm tra xem có rò rỉ gas không"
    if _hz_negated(st, start):
        # "can't get the smoke to stop", "I can't get the sparking to stop" = VẪN đang có
        if _HZ_IMPLY.search(st) or _HZ_PERSIST.search(st):
            return 'present'
        return 'uncertain' if _HZ_AGAIN.search(st[end:]) else 'negated'
    cat = m.lastgroup
    gone = _HZ_GONE_AFTER.match(st[end:]) or (cat in ('gas', 'burning', 'smoke', 'sparks', 'co')
                                              and _HZ_GONE_AFTER_VI.match(st[end:]))
    if gone:
        return 'uncertain' if _HZ_AGAIN.search(st[end + gone.end():]) else 'negated'
    if (_HZ_PAST.search(st) and not _HZ_NOW.search(st) and not _HZ_STARTED_AFTER.match(st[end:])
            and not _HZ_STARTED_BEFORE.search(st[:start])):
        return 'past'
    return 'present'


# 'uncertain' chỉ sinh ra khi 1 câu sau NHẮC LẠI nguy hiểm đã phủ định (xem hazard_check).
_HZ_RANK = {'present': 5, 'uncertain': 4, 'question': 3, 'hypothetical': 3, 'past': 2, 'negated': 1}


def _hz_mask_heat(t):
    """Bỏ thành ngữ NÓNG ("burning hot", "scorching weather") — trừ khi 4 chữ ngay trước là đồ điện ("the plug is burning
    hot", "the outlet is scorching")."""
    def sub(m):
        before = ' '.join(re.findall(r"[^\W_]+(?:'[^\W_]+)?", t[max(0, m.start() - 60):m.start()])[-4:])
        return m.group() if _HZ_HEAT_ELEC.search(before) else ' zzx '
    return _HZ_HEAT.sub(sub, t)


def _hz_reassert(bare):
    """Câu không có từ khoá có NHẮC LẠI nguy hiểm trước đó không: 'strong' | 'weak' | None (xem _HZ_AGAIN).
    'weak' = có từ nhắc lại (still / again / keeps / now / today / vẫn / lại / giờ / nay ...) nhưng câu có thể nói chuyện
    khác ("heater still not working", "still waiting for a quote", "can you come today?", "the aircon still makes noise"):
    đủ để 1 PHỦ ĐỊNH trước đó thành 'uncertain' (hợp đồng: còn nghi ngờ -> GẤP), chưa đủ nâng chuyện đã qua lên khẩn cấp."""
    if _HZ_AGAIN.search(bare) or _HZ_TIME_ONLY.match(bare):
        return 'strong'
    soft = bool(_HZ_AGAIN_SOFT.search(bare))
    if soft and not (_HZ_ANY_NEG.search(bare) or _HZ_SCHEDULE.search(bare) or _HZ_DEVICE.search(bare)):
        return 'strong'
    return 'weak' if soft or _HZ_LATER.search(bare) else None


def hazard_check(text):
    """(kết luận, {loại nguy hiểm: trạng thái câu cuối}) — xem classify_hazard."""
    t = _hz_norm(text)
    battery = bool(_HZ_BATTERY.search(t))
    # nước tràn chỉ do bồn cầu / máy giặt / máy rửa chén... mà không nhắc đồ điện: việc ống nước thường
    plumbing_only = bool(_HZ_PLUMB_SRC.search(t)) and not _HZ_PLUMB_ELEC.search(_HZ_PLUMB_OUTLET.sub(' ', t))
    vent = bool(_HZ_VENT_CTX.search(t))
    t = _HZ_EXCLUDE.sub(' zzx ', t)
    t = _HZ_COOK_SMOKE.sub(' zzx ', _hz_mask_heat(t))
    if vent:
        t = _HZ_VENT_SMOKE.sub(' zzx ', t)
    mask = _HZ.sub(lambda m: '\x00' * len(m.group()), t)   # cùng độ dài: vị trí giữ nguyên
    for run in reversed(list(_HZ_KW_LIST.finditer(mask))):
        seg = re.sub(r"\b(?:and|và|va)\b", '\x01', t[run.start():run.end()].replace(',', ' \x01 '))
        t = t[:run.start()] + seg + t[run.end():]
    states, last, last_delim, adjacent = {}, [], '', False
    for st, delim in _hz_statements(t):
        cur = {}
        first = _HZ.search(st)
        screen = bool(first and _HZ_SCREEN.match(st[:first.start()]))
        for m in _HZ.finditer(st):
            cat = m.lastgroup
            if cat in ('co', 'alarm') and battery and re.search(r"beep|chirp|kêu|keu|bíp|\bbip", m.group()):
                continue   # báo CO / báo khói kêu bíp vì hết pin
            if cat == 'alarm' and _HZ_ALARM_NUISANCE.search(st):
                continue   # báo khói kêu mỗi khi nấu ăn / tắm (hơi nước): đã rõ nguyên nhân
            if cat == 'water' and plumbing_only and not _HZ_WATER_HARD.search(m.group()):
                continue   # "the toilet overflowed and flooded the bathroom", "máy giặt rò nước ngập sàn"
            s = _hz_state(st, m, delim, screen)
            if _HZ_RANK[s] > _HZ_RANK.get(cur.get(cat), 0):
                cur[cat] = s
        if cur:
            states.update(cur)
            last, last_delim, adjacent = list(cur), delim, True
            continue
        if not last:
            continue
        bare = st.strip(" .!?'\"")
        # trả lời 1 chữ chỉ cho câu hỏi sàng lọc NGAY trước: "Gas smell? No"; "Sparks: yes | gas: no" thì "no" là của "gas"
        asked, adjacent = adjacent and last_delim[:1] in ('?', ':', '-', '–', '—'), False
        if _HZ_GONE.match(bare) or (asked and _HZ_NO.match(bare)):
            targets = [c for c, rx in _HZ_NOUNS if c in states and rx.search(bare)] or last
            states.update({c: 'negated' for c in targets})
        elif _HZ_BACK.match(bare) or (asked and _HZ_YES.match(bare)):
            states.update({c: 'present' for c in last})
        else:
            again = _hz_reassert(bare)
            for c, s in list(states.items()):
                if again == 'strong' and c in last and s in ('past', 'question', 'hypothetical'):
                    states[c] = 'present'   # "gas smell yesterday, today it is stronger", "Hôm qua có mùi gas, sáng nay vẫn còn"
                elif again and s == 'negated':
                    states[c] = 'uncertain'   # "no sparks ... it keeps happening" / "... now": không còn chắc là đã hết
    vals = set(states.values())
    if 'present' in vals:
        return 'danger', states
    if not vals:
        return 'none', states
    return ('negated' if vals == {'negated'} else 'uncertain'), states


def classify_hazard(text):
    """'danger' | 'uncertain' | 'negated' | 'none' cho 1 tin nhắn / mô tả việc (xem khối chú thích ở trên)."""
    return hazard_check(text)[0]


def is_emergency(text):
    """True khi có nguy hiểm ĐANG xảy ra (classify_hazard == 'danger')."""
    return classify_hazard(text) == 'danger'


def safety_tip(num, vi):
    """Câu dặn an toàn CÓ ĐIỀU KIỆN ("nếu ngay lúc này...") khi khách có NHẮC nguy hiểm mà không phải đang xảy ra: đã loại
    trừ rõ / đã hết (safety_tip riêng), hay chưa loại trừ rõ (nằm trong tell_customer của việc GẤP)."""
    if vi:
        return (f"Nếu ngay lúc này mình ngửi thấy mùi gas, thấy tia lửa hay khói từ đồ điện, hoặc có người bị điện giật, mọi "
                f"người ra chỗ an toàn và gọi {num or 'số khẩn cấp'} ngay.")
    return (f"If you smell gas, see sparks or smoke from anything electrical, or anyone gets a shock right now, leave the "
            f"area and call {num or 'emergency services'}.")


def _clean(v, n):
    return re.sub(r'\s+', ' ', str(v or '')).strip()[:n]


def _geocode(business_id, address):
    """Toạ độ cho bản đồ điều phối — đúng hàm app._geocode_address (Nominatim + cache) mà POST /api/tasks dùng.
    Chỉ khi app đã nạp (gói chạy trong request của app); không thì để bản đồ điều phối tự ghim như việc tạo tay."""
    fn = getattr(sys.modules.get('app'), '_geocode_address', None)
    if not callable(fn):
        return None
    try:
        return fn(business_id, address)
    except Exception as e:
        print(f"[ai_packs.technical] geocode: {e}")
        return None


def _track_url(business_id, task_id):
    jt = sys.modules.get('job_tracking')   # job_tracking import app -> chỉ dùng khi app đã nạp (không tự import)
    if jt is None or not hasattr(jt, 'track_token'):
        return None
    base = (os.environ.get('PUBLIC_BASE_URL') or 'https://www.bitpawsoftware.com').rstrip('/')
    return f"{base}/track/{business_id}/{task_id}/{jt.track_token(business_id, task_id)}"


def _parse_day(v, today):
    if v in (None, ''):
        return None
    try:
        d = datetime.strptime(str(v).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise _err(f"preferred_date '{str(v)[:20]}' must be YYYY-MM-DD. Nothing was created.")
    if d < today:
        raise _err(f"{d.isoformat()} is in the past (today is {today.isoformat()} at the business). Ask for another day. Nothing was created.")
    if d > today + timedelta(days=MAX_DAYS_AHEAD):
        raise _err(f"That day is more than {MAX_DAYS_AHEAD} days ahead — ask for a nearer day. Nothing was created.")
    return d


def _flag_urgent(ctx, job_id, problem, check=False):
    """Khẩn cấp (hoặc nguy hiểm CHƯA loại trừ rõ — check): chuyển cuộc chat cho người thật (cùng các trường
    handoff_to_staff ghi) để /ai_bot hiện đỏ + AI vào chế độ chờ."""
    cid = ctx.get('customer_id')
    if not cid:
        return
    now = datetime.now().isoformat()
    reason = (f"POSSIBLE HAZARD (urgent, call to check) — job request #{job_id}: {problem[:200]}" if check else
              f"EMERGENCY job request #{job_id}: {problem[:200]}")
    try:
        db.bot_customers.update_one({'id': cid}, {'$set': {
            'ai_paused': True, 'needs_human': True, 'handoff_reason': reason,
            'handoff_at': now, 'handoff_urgent': True, 'handoff_by_ai': True, 'hold_notice_at': now}})
    except Exception as e:
        print(f"[ai_packs.technical] flag urgent: {e}")


def _escalate(business_id, job, problem, svi, level='emergency'):
    """Việc đã có (cùng khách + địa chỉ + ngày) mà giờ khách báo NGUY HIỂM -> urgency 'emergency' (nguy hiểm chưa loại
    trừ rõ -> 'urgent'; chỉ NÂNG, nguyên tử: chỉ 1 lệnh nâng) + ghi vào noi_dung (Bảng điều phối / app nhân viên đọc
    trường này). True nếu lệnh này vừa nâng."""
    now = datetime.now().isoformat()
    emergency = level == 'emergency'
    flt = {'business_id': business_id, 'id': job.get('id'), 'urgency': {'$ne': 'emergency'}}
    if not emergency:   # 'urgent' vì nguy hiểm chưa rõ: 1 lần / việc (kể cả việc 'urgent' AI tự chọn trước đó)
        flt['possible_hazard_problem'] = {'$exists': False}
    before = db.tasks.find_one_and_update(
        flt, {'$set': {'urgency': level, 'emergency_problem' if emergency else 'possible_hazard_problem': problem,
                       'escalated_at': now, 'escalated_by': 'ai_bot'}})
    if not before:
        return False
    body = before.get('noi_dung') or ''
    old = URGENCY.get(before.get('urgency') or 'normal', URGENCY['normal'])
    new = (body.replace(f"| Mức độ: {old[0]}", f"| Mức độ: {URGENCY[level][0]}", 1)
               .replace(f"| Urgency: {old[1]}", f"| Urgency: {URGENCY[level][1]}", 1)
           + ((f"\n--- KHẨN CẤP, khách báo thêm qua chat AI: {problem}" if svi else
               f"\n--- EMERGENCY, the customer added in the AI chat: {problem}") if emergency else
              (f"\n--- GẤP, khách nhắc tới nguy hiểm chưa rõ qua chat AI (gọi khách kiểm tra): {problem}" if svi else
               f"\n--- URGENT, the customer mentioned a possible hazard in the AI chat (call to check): {problem}")))
    try:   # có điều kiện: không đè nếu nhân viên vừa sửa nội dung việc (urgency + báo chủ vẫn đã có)
        db.tasks.update_one({'business_id': business_id, 'id': job.get('id'), 'noi_dung': before.get('noi_dung')},
                            {'$set': {'noi_dung': new}})
    except Exception as e:
        print(f"[ai_packs.technical] escalate: {e}")
    return True


def _reply_expectation(business_id, vi):
    try:
        import ai_function_tools as aft
        return ' ' + aft.reply_expectation(business_id, vi)
    except Exception:
        return ''


def request_job(args, ctx):
    bid = _c._bid(ctx)
    address = _clean(args.get('address'), 200)
    problem = _clean(args.get('problem'), 600)
    if len(address) < 6 or not re.search(r'[^\W\d_]', address):
        raise _err('Ask for the full service address (street number and street, suburb/district, city). Nothing was created.')
    if len(problem) < 4:
        raise _err("Ask the customer to describe what's wrong (which device, what it does). Nothing was created.")
    window = str(args.get('preferred_window') or 'any').strip().lower()
    if window not in WINDOWS:
        raise _err(f"preferred_window must be one of {', '.join(WINDOWS)}. Nothing was created.")
    urgency = str(args.get('urgency') or 'normal').strip().lower()
    if urgency not in URGENCY:
        raise _err(f"urgency must be one of {', '.join(URGENCY)}. Nothing was created.")
    shop = _c._shop(bid)
    name, phone, pkey = _c._contact(args, ctx, 'creating the job request', shop)
    now = _c._now(ctx)
    day = _parse_day(args.get('preferred_date'), now.date())
    hazard, hazards = hazard_check(problem)
    if hazard == 'danger':   # chỉ NÂNG lên khẩn cấp; không bao giờ hạ mức 'emergency' AI đã chọn từ cả cuộc chat
        urgency = 'emergency'
    elif hazard == 'uncertain' and urgency == 'normal':   # có nhắc nguy hiểm mà chưa loại trừ rõ: ít nhất GẤP
        urgency = 'urgent'
    emergency = urgency == 'emergency'
    check = hazard == 'uncertain' and not emergency   # nguy hiểm chưa rõ: GẤP + người thật gọi kiểm tra + báo chủ
    alarm = emergency or check
    svc = None
    if args.get('service_id') not in (None, ''):
        svc = db.dichvu.find_one({'id': _c._int(args.get('service_id'), 'service_id'), 'business_id': bid},
                                 {'_id': 0, 'id': 1, 'ten_dich_vu': 1, 'gia_dich_vu': 1})
        if not svc:
            raise _err('That service_id is not in this business\'s service list — leave it out. Nothing was created.')
    svi, cur = _c.shop_vi(shop), _c.currency_of(bid, shop)
    vi = _c._vi(ctx)
    cid = ctx.get('customer_id')
    key = _c.request_key(ctx, phone, address, now.date().isoformat())

    when_vi = (f"{_c.VI_DOW[day.weekday()]} {day:%d/%m}" if day else 'chưa chọn ngày') + f", {WINDOWS[window][0]}"
    when_en = (day.strftime('%a %d %b') if day else 'no day given') + f", {WINDOWS[window][1]}"
    svc_line = (f"[DỊCH VỤ] {svc.get('ten_dich_vu')} [Giá Thu]: {_c.money(svc.get('gia_dich_vu'), cur)}\n--- " if svc else '')
    body = (f"{svc_line}[AI chat] {problem}\n--- Khách muốn: {when_vi} | Mức độ: {URGENCY[urgency][0]}" if svi else
            f"{svc_line}[AI chat] {problem}\n--- Preferred: {when_en} | Urgency: {URGENCY[urgency][1]}")
    job_id = next_mongo_id('tasks')
    doc = {'id': job_id, 'ten_khach': name, 'sdt': phone, 'dia_chi': address, 'noi_dung': body, 'trang_thai': WAITING,
           'nguoi_nhan': '', 'problem': problem, 'preferred_date': day.isoformat() if day else None,
           'preferred_window': window, 'urgency': urgency, 'service_id': svc and svc.get('id'), 'phone_key': pkey,
           'source': 'ai_bot', 'ai_conversation_id': cid, 'chat_token_hash': ctx.get('chat_token_hash') or None,
           'channel': ctx.get('channel') or 'web', 'created_at': datetime.now().isoformat(),
           'created_at_local': now.strftime('%Y-%m-%dT%H:%M')}
    if check:
        doc['possible_hazard_problem'] = problem
    pt = _geocode(bid, address)
    if pt:
        doc['lat'], doc['lng'] = pt
    # Tạo nguyên tử theo khoá (cùng khách + cùng địa chỉ + cùng ngày): khách nói "gửi giúp em" 2 lần -> vẫn 1 việc trên bảng
    saved, created = _c.insert_once(db.tasks, bid, key, doc, key_field='ai_dedupe_key')
    ekey = key + ':emergency'
    for _ in range(10):
        if created or not alarm or (saved or {}).get('trang_thai') != DONE:
            break
        # việc cũ cùng địa chỉ hôm nay đã XONG (kể cả việc khẩn cấp trước đó): nguy hiểm là việc MỚI trên bảng + báo chủ.
        # Khoá nối theo việc đã xong: khách báo lại vẫn chỉ 1 việc đang mở, không bao giờ trả về việc đã Hoàn Thành.
        saved, created = _c.insert_once(db.tasks, bid, ekey, doc, key_field='ai_dedupe_key')
        ekey = f"{key}:emergency:{(saved or {}).get('id')}"
    escalated = False
    num = EMERGENCY_NUMBER.get(str(shop.get('country') or '').upper(), '')
    tip = safety_tip(num, vi) if hazards and not alarm else None   # nguy hiểm đã loại trừ rõ / đã hết: chỉ dặn an toàn
    # Việc đã có (cùng khoá) chỉ được nêu mã / trạng thái khi chat CHỨNG MINH là chủ: id hội thoại web '<tiệm>:<SĐT gõ>'
    # trình duyệt khác gõ cùng SĐT cũng có -> trả lời chung như fnb / karaoke / hotel, không lộ mã việc của người khác
    mine = created or _c.owns_request(saved, ctx, phone, 'sdt')
    if not created:
        old_id = (saved or {}).get('id')
        if not alarm or old_id is None:
            if not mine:
                extra = {'urgency': urgency, 'safety_tip': tip} if tip else {'urgency': urgency}
                return _c.passed_to_team(
                    ctx, shop,
                    f"Chat AI xin gửi yêu cầu sửa chữa cho {name} {phone}, {address} — trùng việc #{old_id} đã có hôm nay "
                    "(cùng SĐT, cùng địa chỉ) nên AI KHÔNG tạo thêm (chat chưa xác minh là chủ việc đó). Đội liên hệ khách "
                    f"để xác nhận. Khách tả: {problem[:200]}",
                    f"The AI chat asked for a job for {name} {phone}, {address} — it matches job #{old_id} already on the "
                    "board today (same phone and address), so nothing new was created (the chat isn't verified as that "
                    f"job's owner). Please confirm with the customer. They wrote: {problem[:200]}",
                    'Em đã chuyển yêu cầu cho đội kỹ thuật — đội sẽ gọi lại số điện thoại của mình để xác nhận. Hiện CHƯA '
                    'có lịch cho tới khi đội xác nhận.',
                    "I've passed your request to the team — they'll call you on your phone number to confirm. Nothing is "
                    'scheduled until they confirm.', **extra)
            out = {'success': True, 'already_requested': True, 'job_id': old_id, 'status': 'pending',
                   'note': f"A job request for this address was already sent today (job #{old_id}) — do not create "
                           "another. If this is a different problem, use ask_team to add it."}
            if tip:
                out['safety_tip'] = tip
            return out
        # KHẨN CẤP (hay nguy hiểm chưa rõ) không bao giờ bị chống trùng nuốt mất: việc đang có được nâng lên khẩn cấp / GẤP
        # (báo chủ 1 lần), cuộc chat vẫn chuyển người thật và khách vẫn được dặn an toàn
        job_id = old_id
        escalated = _escalate(bid, saved, problem, svi, urgency)
    if alarm:
        _flag_urgent(ctx, job_id, problem, check)
    if escalated and check:
        _c._notify(ctx, shop,
                   f"GẤP — việc #{job_id} (đã có trên Bảng điều phối): khách nhắc tới NGUY HIỂM chưa rõ qua chat AI — gọi "
                   f"khách kiểm tra ngay: {name} {phone}, {address}. {problem[:200]}"
                   + ('' if mine else ' (chat chưa xác minh là chủ việc này — gọi số trên việc để xác nhận)'),
                   f"URGENT — job #{job_id} (already on the dispatch board): the customer mentioned a POSSIBLE HAZARD in the "
                   f"AI chat — call them to check now: {name} {phone}, {address}. {problem[:200]}"
                   + ('' if mine else " (this chat isn't verified as the job's owner — call the number on the job)"),
                   f"URGENT — Job request #{job_id} needs a safety check call (the customer mentioned a possible hazard in "
                   f"the AI chat): {name} {phone}, {address}. Problem: {problem[:300]}. It is on the dispatch board — please "
                   "call the customer now.", 'technical_hazard_check', phone)
    elif escalated:
        _c._notify(ctx, shop,
                   f"KHẨN CẤP — việc #{job_id} (đã có trên Bảng điều phối) giờ khách báo NGUY HIỂM qua chat AI: "
                   f"{name} {phone}, {address}. {problem[:200]}"
                   + ('' if mine else ' (chat chưa xác minh là chủ việc này — gọi số trên việc để xác nhận)'),
                   f"EMERGENCY — job #{job_id} (already on the dispatch board): the customer now reports DANGER in the AI "
                   f"chat: {name} {phone}, {address}. {problem[:200]}"
                   + ('' if mine else " (this chat isn't verified as the job's owner — call the number on the job)"),
                   f"URGENT — Job request #{job_id} is now an EMERGENCY (the customer reported danger in the AI chat): "
                   f"{name} {phone}, {address}. Problem: {problem[:300]}. It is on the dispatch board — please call the "
                   "customer now.", 'technical_emergency', phone)
    elif created:
        pre_vi, pre_en, pre_mail, kind = (
            ('KHẨN CẤP — ', 'EMERGENCY — ', 'URGENT — ', 'technical_emergency') if emergency else
            ('GẤP — CÓ THỂ NGUY HIỂM, gọi khách kiểm tra — ', 'URGENT — POSSIBLE HAZARD, call to check — ',
             'URGENT (possible hazard, call the customer to check) — ', 'technical_hazard_check') if check else
            ('', '', '', 'technical_job'))
        _c._notify(ctx, shop,
                   f"{pre_vi}Việc mới #{job_id} từ chat AI (đang Chờ Nhận trên Bảng điều phối): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_vi})",
                   f"{pre_en}New job #{job_id} from the AI chat (waiting on the dispatch board): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_en})",
                   f"{pre_mail}New job request #{job_id} from the AI chat: {name} {phone}, {address}. "
                   f"Problem: {problem[:300]}. Preferred: {when_en}. It is waiting on the dispatch board — please call the customer.",
                   kind, phone)
    ref_vi, ref_en = (f" (việc #{job_id})", f" (job #{job_id})") if mine else ('', '')
    if emergency:
        tell = ((f"Nếu có nguy hiểm (mùi gas, tia lửa, khói, nước ngập gần ổ điện), mọi người ra chỗ an toàn và gọi {num or 'cấp cứu'} ngay. "
                 f"Em đã báo đội kỹ thuật yêu cầu KHẨN{ref_vi}; em không hứa được giờ tới, đội sẽ gọi lại cho mình.") if vi else
                (f"If anyone is in danger (gas smell, sparks, smoke, water near power), get everyone somewhere safe and call "
                 f"{num or 'emergency services'} now. I've sent your request to the team as URGENT{ref_en}; I can't promise "
                 "an arrival time — the team will call you.")) + _reply_expectation(bid, vi)
    elif check:   # nguy hiểm chưa loại trừ rõ: câu dặn CÓ ĐIỀU KIỆN ("nếu ngay lúc này..."), không bảo sơ tán ngay
        tell = ((f"Em đã gửi yêu cầu cho đội kỹ thuật ở mức GẤP{ref_vi} và nhờ nhân viên gọi lại kiểm tra cho an toàn. "
                 f"{safety_tip(num, True)} Em không hứa được giờ tới, đội sẽ gọi lại cho mình.") if vi else
                (f"I've sent your request to the team marked URGENT{ref_en} and asked a person to call you to check it's "
                 f"safe. {safety_tip(num, False)} I can't promise an arrival time — the team will call you.")
                ) + _reply_expectation(bid, vi)
    else:
        tell = (f"Em đã gửi yêu cầu (việc #{job_id}) cho đội kỹ thuật. Đội sẽ gọi lại để chốt giờ ({when_vi}) — hiện CHƯA có lịch "
                "cho tới khi đội xác nhận." if vi else
                f"Your job request #{job_id} is in. The team will call you to confirm a time ({when_en}) — nothing is "
                "scheduled until they confirm.")
    out = {'success': True, 'job_id': job_id, 'status': 'pending', 'board_status': 'waiting_for_assignment',
           'urgency': urgency, 'preferred': when_en, 'located_on_map': bool(pt), 'tell_customer': tell,
           'note': 'Never promise an arrival time, a price or who will come. The job is not scheduled yet.'}
    if tip:
        out['safety_tip'] = tip
        out['note'] += (' The customer clearly ruled out the danger they mentioned (or said it is gone): this is not an '
                        'emergency — do not tell them to evacuate, but pass on safety_tip.')
    if check:
        out['possible_hazard'] = True
        out['note'] += (' The customer mentioned a danger that is not clearly ruled out (in the past, unsure or only '
                        'asked about): the job is marked URGENT and a person from the team takes over this chat to call '
                        'and check. Pass on tell_customer — it already has the safety line (if it is happening right now, '
                        'leave and call the emergency number). Do not tell them to evacuate unless they say the danger is '
                        'happening now.')
    if not created and not mine:   # khẩn cấp trên việc của 1 chat khác: báo đội + dặn an toàn, KHÔNG lộ mã / trạng thái việc
        return {'success': True, 'request_sent_to_team': True, 'confirmed': False, 'status': 'pending',
                'urgency': urgency, 'tell_customer': tell,
                'note': 'Passed to the team as URGENT; they call the customer. Give no job number and never promise an '
                        'arrival time, a price or who will come.'}
    if not created:   # khẩn cấp / nguy hiểm chưa rõ trên việc đã có từ trước hôm nay
        # mức THẬT trên bảng: vừa nâng -> urgency; không nâng (đã khẩn cấp / đã GẤP vì nguy hiểm chưa rõ) -> mức đang lưu
        board = urgency if escalated else ((saved or {}).get('urgency') or urgency)
        out.update({'already_requested': True, 'escalated': escalated, 'urgency': board,
                    'board_status': {WAITING: 'waiting_for_assignment', TAKEN: 'assigned', DONE: 'completed'}.get(saved.get('trang_thai'), 'in_progress'),
                    'located_on_map': saved.get('lat') is not None,
                    'note': f"Job #{job_id} for this address was already on the dispatch board today — it is now marked "
                            + ("EMERGENCY" if board == 'emergency' else "URGENT (possible hazard, a person calls to check)"
                               if board == 'urgent' else "flagged as a possible hazard (a person calls to check)")
                            + " and the team has been alerted. Do not create another. Never promise an arrival "
                            "time, a price or who will come."})
    return out


def _job_view(t, business_id, shop):
    st = t.get('trang_thai')
    if st == DONE:
        state, meaning = 'completed', 'the job is marked completed'
    elif st == TAKEN and t.get('on_way_at'):
        state, meaning = 'on_the_way', 'someone from the team is on the way'
    elif st == TAKEN:
        state, meaning = 'assigned', 'assigned to a team member; the team confirms the visit time'
    elif st == WAITING:
        state, meaning = 'waiting', 'received — waiting to be assigned to a team member'
    else:
        state, meaning = 'in_progress', 'being handled by the team'
    out = {'job_id': t.get('id'), 'state': state, 'meaning': meaning, 'address': t.get('dia_chi') or ''}
    if t.get('source') == 'ai_bot':   # việc tạo tay: noi_dung có thể chứa hoa hồng nội bộ -> không trả
        out['problem'] = t.get('problem')
        if t.get('preferred_date') or t.get('preferred_window'):
            out['preferred'] = ' '.join(x for x in (t.get('preferred_date'), WINDOWS.get(t.get('preferred_window') or '', ('', ''))[1]) if x)
    if state in ('assigned', 'on_the_way') and t.get('nguoi_nhan'):
        parts = str(t['nguoi_nhan']).split()   # chỉ TÊN gọi (tên Việt là chữ cuối), như trang theo dõi công khai
        out['assigned_to'] = parts[-1 if str(shop.get('country') or '').upper() == 'VN' else 0] if parts else None
    if state == 'on_the_way':
        url = _track_url(business_id, t.get('id'))
        if url:
            out['live_tracking_link'] = url
    return out


def job_status(args, ctx):
    bid = _c._bid(ctx)
    ors = []
    k = _c.phone_key(ctx.get('phone'), _c._country(ctx))
    if k:  # SĐT đã xác minh: cả việc nhân viên tạo tay (sdt gõ tay dạng bất kỳ, so ĐỦ số) lẫn việc AI tạo
        ors.append({'phone_key': k})
        rx = _c.phone_regex(k)
        if rx:
            ors.append({'sdt': {'$regex': rx}})
    own = _c.owner_filter(ctx)
    for c in (own or {}).get('$or', []):
        if c not in ors:
            ors.append(c)
    if not ors:
        raise _c._not_verified(ctx, 'yêu cầu sửa chữa', 'job requests')
    flt = {'business_id': bid, '$or': ors}
    if args.get('job_id') not in (None, ''):
        flt['id'] = _c._int(args.get('job_id'), 'job_id')
    rows = list(db.tasks.find(flt, {'_id': 0, 'id': 1, 'trang_thai': 1, 'dia_chi': 1, 'nguoi_nhan': 1, 'on_way_at': 1,
                                    'source': 1, 'problem': 1, 'preferred_date': 1, 'preferred_window': 1}).sort('id', -1).limit(5))
    shop = _c._shop(bid) if rows else {}
    res = {'success': True, 'jobs': [_job_view(t, bid, shop) for t in rows]}
    if not rows:
        res['note'] = ('No job found for this chat' + (' or phone number.' if k else '.') +
                       ' Jobs booked another way may not show here — the customer can call the business.')
    return res


def facts(business_id, lang, now_local):
    """Dữ kiện riêng của gói (giờ mở cửa + thông tin tiệm + kho câu hỏi do customer_context.facts thêm cho mọi gói)."""
    lines = []
    shop = _c._shop(business_id)
    cur = _c.currency_of(business_id, shop)
    try:
        svcs = list(db.dichvu.find({'business_id': business_id}, {'_id': 0, 'id': 1, 'ten_dich_vu': 1, 'gia_dich_vu': 1})
                    .sort('id', 1).limit(40))
    except Exception:
        svcs = []
    if svcs:  # chỉ tên + giá thu của tiệm; KHÔNG bao giờ đưa tien_tua (hoa hồng thợ)
        lines.append("SERVICE PRICE LIST (the business's own list prices; parts and anything found on site are extra and "
                     "confirmed by the team):\n" + '\n'.join(f"- service_id {s.get('id')}: {s.get('ten_dich_vu')} — "
                                                            f"{_c.money(s.get('gia_dich_vu'), cur)}" for s in svcs))
    num = EMERGENCY_NUMBER.get(str(shop.get('country') or '').upper())
    lines.append("JOB REQUESTS: you can't see the team's schedule. technical_request_job puts the job on the dispatch board as "
                 "waiting; the team calls the customer to confirm the time. Service area is confirmed by the team."
                 + (f" EMERGENCY NUMBER in this country: {num}." if num else ''))
    return '\n'.join(lines)


_HANDLERS = {'technical_request_job': request_job, 'technical_job_status': job_status}


def execute(name, args, ctx):
    fn = _HANDLERS.get(name)
    if fn is None:
        raise _err(f"Unknown field-service tool '{name}'.")
    return fn(args if isinstance(args, dict) else {}, ctx or {})
