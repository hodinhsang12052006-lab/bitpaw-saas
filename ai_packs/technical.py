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
chỗ an toàn và gọi số khẩn cấp, không hẹn giờ. Máy hút mùi / ống khói / pin báo khói, nguy hiểm khách nói là KHÔNG có hay
đã hết, câu chỉ HỎI có nguy hiểm không: việc thường + câu dặn an toàn (safety_tip).
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
# Phát hiện NGUY HIỂM trong mô tả việc / tin nhắn của khách: classify_hazard(text) -> 'danger' | 'negated' | 'none'.
#   'danger'  có ít nhất 1 nguy hiểm mà câu CUỐI nói về nó khẳng định nó đang / vừa xảy ra -> việc 'emergency', chuyển
#             người thật + dặn gọi số khẩn cấp ("I can smell gas", "ổ cắm bốc khói", "didn't smell gas this morning, but
#             I do now", "hôm qua không có khói, hôm nay có").
#   'negated' mọi nguy hiểm được nhắc đều bị phủ định rõ hoặc đã HẾT ("no sparks or burning smell when switching on",
#             "không có mùi khét khi bật máy", "smelled gas earlier, it's gone now", "lúc nãy có mùi gas, giờ hết mùi rồi")
#             -> việc thường + câu dặn an toàn.
#   'none'    không nhắc nguy hiểm nào (máy hút mùi / ống khói / khói bếp, smoke alarm battery, gas bill, "no power"...)
#             hoặc chỉ HỎI / GIẢ ĐỊNH ("is it dangerous if there is smoke?", "nếu có khói thì sao") hay chuyện ĐÃ LÂU
#             ("the outlet sparked last week") -> việc thường (+ câu dặn an toàn nếu có nhắc nguy hiểm).
# Các bước (hazard_check):
#   1. Bỏ cụm KHÔNG phải nguy hiểm (_HZ_EXCLUDE). Khói chỉ tính khi tin nhắn không nói chuyện nấu nướng / hút mùi /
#      thuốc lá (_HZ_SMOKE_CTX), hoặc có nói nguồn điện / thiết bị trong cùng câu (_HZ_SMOKE_SRC: ổ cắm, tủ điện...).
#   2. Tách câu ở . ! ? ; , : - ( ) và but / however / and / then / nhưng / mà / và, cùng TRƯỚC now / today / giờ /
#      bây giờ / hôm nay. Danh sách chỉ gồm từ khoá ("No gas smell, sparks or smoke") giữ trong 1 câu: phủ định đầu danh
#      sách phủ cả danh sách.
#   3. Mỗi câu: mỗi từ khoá (_HZ, theo loại gas / sparks / burning / smoke / shock / water / co / fire) được xếp
#      present | negated | past | question | hypothetical (_hz_state). Câu KHÔNG có từ khoá vẫn có thể LẬT LẠI ("but I
#      do now", "today there is", "hôm nay có", "giờ thì có rồi") hoặc KẾT THÚC ("it's gone now", "hết mùi rồi")
#      nguy hiểm của câu trước.
#   4. Câu CUỐI nói về mỗi loại quyết định. Lấp lửng ("not sure if it's sparking", "I don't think it's a gas leak",
#      "không biết có rò rỉ gas không") vẫn là NGUY HIỂM: bỏ sót là chết người, báo nhầm chỉ phiền.
_HZ_EXCLUDE = re.compile(
    r"\bsmok(?:e|ing)[- ]?(?:alarms?|detectors?|sensors?|seals?|dampers?|tests?|testing|vents?|extract\w*|exhaust\w*|"
    r"control\w*|curtains?|doors?|machines?|signals?|shops?|free|stacks?|screens?|evacuation|management|spill|"
    r"baffles?|barriers?|stains?|stained|damaged?|residue|marks?|areas?|rooms?|zones?|signs?|policy|shelters?)\b"
    r"|\bsmoke ?(?:and|&|/) ?(?:heat|co2?|carbon monoxide) (?:alarms?|detectors?|sensors?)\b(?! (?:is |are |keeps? |"
    r"kept |has |have )?(?:been )?(?:going off|went off|goes off|gone off|sounding|alarming|triggered))"
    r"|\b(?:no|non)[- ]smoking\b|\bsmoked (?:salmon|meat|fish|glass|ham)\b|\bsmoke ?bombs?\b|\bfogging\b"
    r"|\bfire[- ]?(?:alarms?|extinguishers?|doors?|safety|sprinklers?|blankets?|exits?|rated|rating|places?|pits?|wood|"
    r"hydrants?|hoses?|inspections?|drills?|escapes?|systems?|panels?|proof\w*|walls?|stops?|separation|resist\w*|retard\w*|"
    r"works|crackers?|starters?|hazards?|risks?|insurance|compliance|certificates?)\b|\bfireplaces?\b|\bfirewood\b"
    r"|\bflood ?lights?\b|\bfloodlight\w*|\bflood[- ](?:damage|restoration|insurance|zones?|plains?|barriers?|gates?|proof\w*|"
    r"mitigation|clean-?up|risks?)\b|\bspark[- ]?plugs?\b|\bspark (?:broadband|modem|router|wi-?fi|fibre|fiber|nz|mobile|"
    r"account|bill|plan|internet|phone|sim)\b|\bgas[- ](?:leak[- ])?(?:tests?|testing|checks?|inspections?|detection|"
    r"detectors?|compliance|certificates?|safety checks?)\b"
    r"|\bbefore,? (?:during,? )?(?:or|and) after\b|\bbefore (?:or|and) after\b|trước (?:và|hay|hoặc) sau"
    r"|máy hút mùi|hút mùi|máy hút khói|hút khói|ống khói|khói bếp|khói (?:\w+ )?bám|bám khói|ám khói|khói thuốc(?: lá)?|"
    r"khói nhang|khói hương|khói xe|khói bụi|khói nướng|khói dầu|khói nấu|máy tạo khói|"
    r"(?:đầu |chuông |thiết bị |hệ thống |máy )?báo khói|cảm biến khói|(?:đầu |chuông |hệ thống |thiết bị )?báo cháy|"
    r"bình chữa cháy|chữa cháy|chống cháy|phòng cháy|bóng(?: đèn)? (?:bị )?(?:cháy|nổ)|cháy bóng|"
    r"(?:cầu chì|chì) (?:bị )?(?:cháy|nổ|đứt)|(?:cháy|nổ) cầu chì|chập chờn|thuốc lá|xì gà|phun khói|xông khói")
# Tin nhắn nói chuyện nấu nướng / hút mùi / ống khói / thuốc lá: "khói" trong đó là khói bếp, không phải nguy hiểm —
# trừ khi cùng câu nói rõ khói từ đồ điện (_HZ_SMOKE_SRC).
_HZ_SMOKE_CTX = re.compile(
    r"\b(?:range ?hoods?|cooker ?hoods?|kitchen ?hoods?|stove ?hoods?|hoods?|exhaust\w*|extractor\w*|chimneys?|flues?|"
    r"cook\w*|bbq|barbecues?|grill\w*|fry\w*|toast\w*|cigarettes?|cigars?|tobacco|vap(?:e|es|ing)|incense|candles?|"
    r"fireplaces?|wood ?(?:stove|heater|fire)s?|smokers?)\b"
    r"|hút mùi|hút khói|ống khói|khói bếp|khói thuốc|thuốc lá|nấu|chiên|xào|nướng|quạt hút|quạt thông gió|thông gió|"
    r"nhang|khói hương|lò sưởi|bếp than|than hoa|bếp củi|xì gà|hút thuốc")
_HZ_SMOKE_SRC = re.compile(
    r"\b(?:outlets?|sockets?|power ?points?|gpos?|plugs?|switch(?:es|board|boards)?|fuse ?box(?:es)?|breakers?|panels?|"
    r"meter ?box(?:es)?|wires?|wiring|cables?|cords?|light ?fittings?|lights?|downlights?|lamps?|bulbs?|motors?|"
    r"compressors?|air ?con\w*|aircon\w*|a/?c|heaters?|heat ?pumps?|fridges?|freezers?|dryers?|washers?|washing machines?|"
    r"dishwashers?|tvs?|televisions?|chargers?|batter(?:y|ies)|appliances?|inverters?|microwaves?|kettles?|computers?|"
    r"laptops?|printers?|routers?|modems?|transformers?|generators?|pumps?|boilers?|furnaces?|dehumidifiers?|"
    r"power ?boards?|adapt[eo]rs?|extension (?:leads?|cords?)|electrics?|electrical)\b"
    r"|\b(?:from|out of|behind|inside|in) (?:the )?(?:walls?|ceiling)\b"
    r"|ổ cắm|ổ điện|phích cắm|công tắc|cầu dao|aptomat|tủ điện|bảng điện|đồng hồ điện|công tơ|dây điện|mô tơ|motor|"
    r"động cơ|máy nén|cục nóng|cục lạnh|dàn nóng|dàn lạnh|máy lạnh|điều hòa|điều hoà|tủ lạnh|tủ đông|máy giặt|máy sấy|"
    r"bình nóng lạnh|máy nước nóng|tivi|ti vi|cục sạc|\bsạc\b|bo mạch|bếp từ|bếp điện|lò vi sóng|nồi cơm|ấm siêu tốc|"
    r"máy tính|máy in|bóng đèn|\bđèn\b|ổn áp|máy bơm|máy phát|biến tần|\bmáy\b|\bpin\b|\bdây\b|(?:từ|trong) (?:\w+ )?(?:tường|trần)")
# Từ khoá theo loại. Tiếng Việt CÓ DẤU cho chữ dễ nhầm ("đang chạy" / "đang cháy", "ra khỏi" / "ra khói", "khởi động"),
# không dấu chỉ cho cụm không nhầm được ("mui gas", "chap dien", "tia lua"). Lỗi gõ hay gặp: "smel gas", "gass", "burnig".
_HZ = re.compile(
    r"(?P<co>\b(?:co2?|carbon monoxide|gas) (?:alarms?|detectors?|sensors?|monitors?) (?:is |are |was |were |has |have |"
    r"keeps? |kept )?(?:been |just |now |still )?(?:going off|went off|goes off|gone off|sounding|alarming|beeping|blaring|"
    r"triggered|screaming|ringing|chirping)\b|\bcarbon monoxide\b(?! (?:alarms?|detectors?|sensors?|monitors?|tests?|"
    r"testing|checks?)\b)|ngộ độc khí|ngộ độc co\b|\bkhí co\b|(?:báo|cảm biến) (?:khí )?(?:co|gas) (?:đang |bị )?(?:kêu|hú|"
    r"báo động|báo))"
    r"|(?P<gas>\b(?:gas{1,2}|gaz)(?:es)? leak\w*|\bleak\w* (?:of )?(?:natural |lpg |propane )?(?:gas{1,2}|gaz)\b"
    r"(?! (?:heaters?|stoves?|bills?|cooktops?|ovens?|hot water|meters?|bottles?|fireplaces?|appliances?))|"
    r"\b(?:gas{1,2}|gaz) (?:is |was |has been )?leak\w*|\b(?:lpg|propane) leak\w*|\b(?:smel+(?:s|t|ed|led|ling|ing|in)?|"
    r"odou?rs?|stench|stink\w*) (?:of |like )?(?:a |some |the )?(?:natural |lpg |propane )?(?:gas{1,2}|gaz)\b"
    r"(?! (?:heaters?|stoves?|bills?|cooktops?|ovens?|hot water|meters?|bottles?|fireplaces?|appliances?))|"
    r"\b(?:gas{1,2}|gaz) (?:smel+\w*|"
    r"odou?rs?|stench)|\brotten[- ]eggs?\b|\b(?:gas{1,2}|gaz) (?:is )?hiss\w*|\bhiss\w* (?:sound |noise )?(?:from|at|near|in) "
    r"(?:the )?(?:gas{1,2}|gaz)\b|\b(?:gas{1,2}|gaz|lpg|propane) fumes\b|\b(?:lpg|propane|gas{1,2}|gaz) (?:bottle|cylinder|"
    r"tank|line|pipe|hose|valve|regulator|meter|fitting|connection)s? (?:is |are |has been |keeps )?(?:leak\w*|hiss\w*)|"
    r"mùi (?:khí )?(?:gas|ga|gaz)\b|hơi (?:gas|ga)\b|"
    r"(?:rò rỉ|rò|xì|hở|xì hơi) (?:khí )?(?:gas|ga|gaz)\b|(?:bình|bếp|van|ống|dây|bồn) (?:gas|ga) (?:bị )?(?:xì|rò rỉ|rò|"
    r"hở)|\b(?:gas|ga) (?:bị )?(?:xì|rò rỉ|rò|hở)\b|\b(?:mui|ro ri|ro|xi|ho) (?:gas|gaz)\b)"
    r"|(?P<sparks>\bspark(?:s|ing|in|ed)?\b(?![- ](?:plugs?|arrest\w*|gaps?)\b)|\barc(?:ing|ed)\b|\belectrical arcs?\b|"
    r"tia lửa|tóe lửa|toé lửa|tóe điện|toé điện|xẹt điện|xẹt lửa|chập điện|chập mạch|chập cháy|bị chập\b|đoản mạch|"
    r"nháy lửa|\b(?:tia lua|chap dien|chap mach|toe lua|xet dien)\b)"
    r"|(?P<burning>\b(?:burn\w{0,3}|scorch\w*|melting|electrical|electric) (?:plastic |rubber |wire |"
    r"wiring )?(?:smel+\w*|odou?rs?|stench)|\b(?:burn\w{0,3}|toxic|electrical|acrid|chemical) fumes\b|"
    r"\bsmel+(?:s|t|ed|led|ling|ing|in)? (?:of |like )?(?:(?:something|it'?s|its|"
    r"plastic|wires?|wiring|rubber|electrical) )?(?:burn\w{0,3}|melting|scorch\w*)|\bscorch(?:ed|ing)?\b|"
    r"\b(?:something|it|outlets?|switch\w*|wires?|wiring|cables?|plugs?|panel|sockets?)(?:'s| is| are)? "
    r"(?:burning|smouldering|smoldering|melting)\b|"
    r"\bmelt(?:ed|ing) (?:outlets?|sockets?|plugs?|wires?|wiring|cables?|switch\w*|power ?points?)\b|"
    r"(?:ổ cắm|ổ điện|phích cắm|dây điện|công tắc|cầu dao|aptomat) (?:bị )?(?:chảy nhựa|nóng chảy|cháy đen|cháy xém|xém)|"
    r"cháy xém|mùi khét|"
    r"khét(?! tiếng)|mùi (?:như )?(?:nhựa |dây |điện |đồ |dây điện )?cháy|cháy khét|mùi nhựa (?:cháy|chảy)|"
    r"\bmui khet\b|\bkhet\b)"
    r"|(?P<smoke>\bsmok(?:e|es|ed|ing|in|y)\b|\bsmoulder\w*|\bsmolder\w*|khói|\b(?:boc|xi|toa|co) khoi\b(?! (?:dong|"
    r"dau|nghia|phat|tao|xuong|cong))|\bkhoi den\b)"
    r"|(?P<shock>\belectric(?:al)? shoc?ks?\b|\belectrocut\w*|\bshoc?k(?:ed|s|ing)? (?:me|him|her|us|them|my \w+|someone|"
    r"somebody|the kids?|the child|people|anyone)\b|\b(?:got|get|gets|getting|(?:give|gives|gave|giving) (?:me|him|her|"
    r"us|them|my \w+|someone|people)|received|receiving|had|having|felt|feel|feeling) (?:a |an |some )?(?:small |mild |"
    r"big |nasty |little |slight |bad |huge |strong )?(?:electric(?:al)? )?shoc?ks?\b|\bzapp(?:ed|ing)\b|"
    r"\bzaps? (?:me|him|her|us|them)\b|\btingl(?:e|es|ed|ing|y)\b|điện giật|giật điện|giật tê|tê tay|tê người|tê chân|"
    r"rò điện|rò rỉ điện|dò điện|hở điện|lọt điện|điện (?:bị )?rò|(?:vỏ|thân) (?:máy|tủ|bình)(?: \w+){0,2} (?:có|bị) "
    r"(?:điện|giật)|có điện ở vỏ|(?:chạm|sờ|đụng|cầm)(?: vào| phải)?(?: \w+){0,3}(?: là| thì| bị)* "
    r"(?:giật|tê)\b|\b(?:dien giat|giat dien|ro dien|ro ri dien|ho dien)\b)"
    r"|(?P<water>\bflood(?:s|ed|ing)?\b|\bburst (?:water )?pipes?\b|\bpipes? (?:has |have |just )?burst\b|"
    r"\bwater everywhere\b|\bwater (?:is |was )?(?:pouring|gushing|spraying|flooding)\b|\bwater (?:is |was |has been |"
    r"keeps )?(?:coming|leaking|pouring|dripping|getting|running|seeping|got|gone|went|leaks|drips|pours) (?:in |out )?(?:in|into|"
    r"out of|through|from|onto|on|near|around|behind) (?:the |a |my |our |an )?(?:ceiling )?(?:light fittings?|lights?|"
    r"downlights?|outlets?|sockets?|power ?points?|gpos?|switch(?:es|board|boards)?|fuse ?box(?:es)?|electrical panel|"
    r"panel|meter ?box|electrics|wiring|wires|plugs?)\b|\b(?:wet|soaked|flooded|water[- ]?logged) (?:switchboard|"
    r"fuse ?box|electrical panel|panel|outlets?|sockets?|power ?points?|wiring|plugs?)\b|\b(?:switchboard|fuse ?box|"
    r"electrical panel|meter ?box|outlets?|sockets?|power ?points?|wiring) (?:is |are |got |gets |has got |have got )?"
    r"(?:wet|soaked|flooded|under water)\b|\b(?:ceiling )?(?:light fittings?|lights?|downlights?|outlets?|sockets?|"
    r"power ?points?|switch(?:es)?) (?:is |are )?(?:full of|filled with|filling (?:up )?with) water\b|ngập nước|nước ngập|bị ngập|"
    r"đang ngập|ngập sàn|ngập nhà|ngập bếp|ngập phòng|ngập tầng|ngập hầm|vỡ ống|bể ống|bục ống|nổ ống|ống nước (?:bị )?"
    r"(?:vỡ|bể|bục)|nước (?:\w+ ){0,2}(?:vào|vô|từ|qua) (?:ổ cắm|ổ điện|tủ điện|cầu dao|công tắc|bóng đèn|đèn|dây điện|"
    r"bảng điện|đồng hồ điện|aptomat)|(?:ổ cắm|ổ điện|tủ điện|cầu dao|công tắc|bảng điện|dây điện|aptomat|bóng đèn|đèn) "
    r"(?:bị )?(?:ướt|ngấm nước|vô nước|vào nước|dính nước|ngập|chảy nước|rỉ nước|nhỏ nước|dột)|\b(?:ngap nuoc|nuoc ngap|"
    r"vo ong nuoc|be ong nuoc)\b)"
    r"|(?P<fire>\bon fire\b|\bcaught fire\b|\bcatch(?:es|ing)? (?:on )?fire\b|\bfire (?:in|inside|at|from|started|"
    r"broke out|is spreading|spreading|behind|under)\b|\b(?:a|small|electrical|big|kitchen|house) fire\b|\bflames? (?:is |"
    r"are )?(?:coming|shooting|pouring|leaping|bursting|everywhere|out|from|inside|behind)\b|\bin flames\b|"
    r"\bexplo(?:ded|des|ding|sion|sions)\b|\bblew up\b|\bblown up\b|đang cháy|bốc cháy|bùng cháy|cháy bùng|cháy nổ|"
    r"cháy lan|hỏa hoạn|hoả hoạn|phát hỏa|phát hoả|bén lửa|lửa (?:bùng|bốc|lan|phụt|tóe|toé)|phát nổ|bị nổ|nổ tung|"
    r"tiếng nổ|nổ lớn|nổ to|nổ bùm|nổ lụp bụp|(?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|bảng điện|cầu dao|phích cắm|"
    r"aptomat) (?:bị )?cháy|cháy (?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|bảng điện|phích cắm|nhà|bếp)|"
    r"(?:nhà|phòng) (?:bị |đang )?cháy|(?:ổ cắm|ổ điện|tủ điện|dây điện|công tắc|cầu dao|phích cắm|aptomat|máy) (?:có|bốc|"
    r"phát|phụt) lửa|"
    r"\b(?:boc chay|phat no|hoa hoan|chay no)\b)")
_HZ_BATTERY = re.compile(r"\bbatter(?:y|ies)\b|\bpin\b")
# Tách câu: dấu câu + liên từ đổi ý; trước "không biết / not sure" (câu lấp lửng đứng riêng).
_HZ_BREAK = re.compile(
    r"([.!?;,:|\n()\[\]]|\s[-–—]+\s|\s[-–—]+$|^[-–—]+\s)"
    r"|\b(?:but|however|although|though|whereas|yet|and|then|plus|also|nhưng mà|nhưng|tuy nhiên|mà|và|với lại)\b"
    r"|(?=\b(?:không biết|ko biết|k biết|kh biết|chả biết|chẳng biết|hông biết|not sure|unsure|don'?t know|dont know|"
    r"no idea|wonder\w*)\b)")
_HZ_PIVOT = re.compile(r"\b(?:bây giờ|hôm nay|giờ|now|today)\b")
_HZ_PIVOT_GUARD = frozenset((
    'until', 'till', 'til', 'by', 'from', 'for', 'right', 'just', 'up', 'as', 'of', 'since', 'bao', 'trước', 'đến', 'tới',
    'cho', 'mấy', 'mỗi', 'vài', 'nửa', 'lúc', 'tiếng', 'số', 'bây', 'từ', 'hôm', 'den', 'toi', 'một', 'hai', 'ba', 'bốn',
    'năm', 'sáu', 'bảy', 'tám', 'chín', 'mười'))
_HZ_TRIVIAL = frozenset(('now', 'today', 'giờ', 'bây', 'hôm', 'nay', 'right', 'just', 'thì', 'rồi', 'ạ', 'á', 'à', 'nhé',
                         'nha', 'đó', 'đấy', 'luôn', 'already', 'too', 'also', 'ơi'))
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
    "đâu", "ngừng"))
# Từ được phép đứng giữa từ phủ định và từ khoá. KHÔNG có đại từ / "there" / "is" / "seem" / "think" / "sure": "no i can
# smell gas", "no there is smoke", "I don't think it's a gas leak", "not sure if it's sparking" là báo NGUY HIỂM.
_HZ_FILLER = frozenset((
    "a", "an", "any", "sign", "signs", "evidence", "trace", "traces", "hint", "of", "be", "been", "have", "has", "had",
    "more", "longer", "visible", "even", "at", "all", "real", "obvious", "noticeable", "further", "other", "ever",
    "có", "bị", "thấy", "gì", "dấu", "hiệu", "hiện", "tượng", "nào", "hề", "còn", "cũng", "ngửi", "nghe", "là", "phải",
    "bất", "kỳ", "kì", "tí", "chút", "bao", "giờ", "để", "ý", "xảy", "ra", "phát", "cảm", "giác", "co", "bi", "thay",
    "gi", "dau", "hieu", "nao", "he", "con", "cung", "ngui"))
# Động từ giác quan sau từ phủ định vẫn là phủ định ("I don't smell gas", "haven't seen any sparks", "didn't smell gas this
# morning"); sau chúng "the / that" cũng được ("didn't see the sparks").
_HZ_SENSE = frozenset(("see", "seen", "saw", "notice", "noticed", "smell", "smelled", "smelt", "detect", "detected",
                       "feel", "felt", "hear", "heard", "spot", "spotted", "observe", "observed", "find", "found", "get",
                       "got", "experience", "experienced"))
_HZ_UNDO = frozenset(("sắp", "gần", "sap", "gan", "almost", "nearly", "vẫn", "van"))
_HZ_HET_OK = frozenset(("đã", "da", "cũng", "cung", "đều", "deu", "vừa", "vua", "mới", "moi", "hiện", "là", "la", "giờ",
                        "gio", "nay", "now", "rồi", "roi", "thì", "thi", "qua", "nãy", "sáng", "trưa", "chiều", "tối",
                        "đêm", "sau", "đó"))
_HZ_JOIN = frozenset(("or", "nor", "hay", "hoặc", "hoac", "\x01"))
# Phủ định cùng câu với "lúc trước / cho tới / trừ khi / như vầy / khi tắt máy" ngầm nói HIỆN CÓ: 'No smoke until I
# switched it on', 'never seen sparks like this', "no burning smell when it's off", 'lúc đầu không có mùi khét',
# 'không để ý mùi khét cho đến giờ'. "before or after" / "khi bật máy" / "when I checked" thì vẫn là phủ định.
_HZ_IMPLY = re.compile(
    r"\b(?:until|till|til|at first|at the start|in the beginning|initially|before|earlier|previously|unless|except|"
    r"(?<!anything )(?<!nothing )(?<!something )like (?:this|that)|this (?:bad|much|often|strong)|"
    r"that (?:bad|much|often|strong))\b"
    r"|\bwhen (?:it'?s |it is |its |they'?re |they are |the \w+ is |it was |i )?(?:turned |switched )?(?:off|unplugged|"
    r"idle|not (?:running|on|in use|plugged in))\b|\bwhile (?:it'?s |it is )?(?:off|unplugged|idle)\b"
    r"|lúc đầu|ban đầu|hồi đầu|mới đầu|lúc trước|trước đó|trước đây|trước giờ|hồi nãy|lúc nãy|ban nãy|cho đến|cho tới|"
    r"đến giờ|tới giờ|đến bây giờ|tới bây giờ|(?<!gì )(?:như vầy|như vậy|như thế|như này)|thế này|trừ khi|ngoại trừ|"
    r"(?:khi|lúc) (?:tắt|không (?:bật|dùng|chạy|cắm)|rút (?:điện|phích|ra))")
# Chuyện ĐÃ LÂU (từ hôm qua trở về trước) mà câu không nói gì về hiện tại: không ép khẩn cấp (vẫn dặn an toàn).
_HZ_PAST = re.compile(
    r"\b(?:yesterday|last (?:night|week|weekend|month|year|time|summer|winter|spring|autumn|fall|monday|tuesday|"
    r"wednesday|thursday|friday|saturday|sunday)|(?:\d+|a|an|one|two|three|four|five|few|couple(?: of)?|several) "
    r"(?:days?|weeks?|months?|years?) ago|the other day|a while (?:ago|back)|in the past|previously|used to|once before)\b"
    r"|hôm qua|hôm kia|hôm trước|mấy hôm trước|bữa trước|mấy ngày trước|tuần trước|tháng trước|năm ngoái|năm trước|"
    r"năm rồi|tuần rồi|tháng rồi|đêm qua|tối qua|chiều qua|sáng qua|trưa qua|lần trước|đợt trước|trước đây|hồi trước|"
    r"dạo trước|lâu rồi|\b\d+ (?:ngày|tuần|tháng|năm) trước")
_HZ_NOW = re.compile(
    r"\b(?:now|currently|still|again|at the moment|today|tonight|keeps?|kept|constantly|continuously|every time|"
    r"whenever|since|ongoing|getting (?:worse|stronger)|this (?:morning|afternoon|evening))\b"
    r"|giờ|hiện|đang|vẫn|còn|\blại\b|liên tục|mỗi lần|mỗi khi|hôm nay|\bnay\b|từ (?:hôm qua|hôm kia|hôm trước|tuần trước|"
    r"tháng trước|tối qua|đêm qua|sáng qua|mấy hôm)")
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
_HZ_HYPO = frozenset(('if', 'nếu', 'lỡ', 'nhỡ', 'suppose', 'supposing', 'giả', 'neu'))
_HZ_HYPO_FILL = frozenset((
    'there', 'is', 'are', "there's", "it's", 'its', 'it', 'i', 'we', 'you', 'they', 'he', 'she', 'someone', 'anyone', 'a',
    'an', 'any', 'some', 'the', 'ever', 'still', 'again', 'be', 'been', 'was', 'were', 'smell', 'smells', 'see', 'sees',
    'notice', 'get', 'gets', 'start', 'starts', 'happen', 'happens', 'to', 'my', 'our', 'your', 'this', 'that', 'more',
    'even', 'có', 'bị', 'thấy', 'ngửi', 'nghe', 'mà', 'như', 'xảy', 'ra', 'lại', 'còn', 'vẫn', 'phát', 'hiện', 'nhà',
    'mình', 'em', 'anh', 'chị', 'sử', 'co', 'bi', 'thay')) | _HZ_NEG
_HZ_UNSURE = frozenset(('sure', 'unsure', 'know', 'knows', 'wonder', 'wondering', 'idea', 'tell', 'check', 'checking',
                        'see', 'ask', 'asking', 'clear', 'certain', 'determine', 'out', 'biết', 'biet'))
# Ngay sau từ khoá: "gas smell is gone", "the sparks stopped", "mùi gas hết rồi", "khói tan rồi" = đã HẾT.
_HZ_GONE_AFTER = re.compile(
    r"^(?:\s+(?:smell|odou?r|is|has|have|had|was|were|now|already|completely|all|totally|finally|since|then))*\s+"
    r"(?:gone|stopped|cleared|went away|gone away|disappeared|subsided|dissipated|faded|died down|no longer there)\b")
_HZ_GONE_AFTER_VI = re.compile(r"^(?:\s+(?:đã|cũng|thì|giờ|bây giờ|nay|đều))*\s+(?:hết(?: hẳn)? rồi|hết hẳn|đã hết|"
                               r"tan(?: hết)?(?: rồi)?|không còn(?: nữa)?)\b")
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
    r"ạ|á|à|gì))*$")
_HZ_BACK = re.compile(
    r"^(?:(?:so\s+)?(?:(?:now|today|tonight|this (?:morning|afternoon|evening))\s+)?"
    r"(?:(?:i|we|you)\s+(?:do|can|did|could)(?:\s+(?:smell|see|notice|hear|feel)(?:\s+(?:it|them|some|one))?)?"
    r"|(?:i|we|you)\s+(?:smell|see|notice|hear|feel)\s+(?:it|them|some|one)"
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
    r"|(?:có lại|bị lại|lại có|lại bị|lại thấy|thấy lại)(?:\s+(?:rồi|nữa|ạ|á|à|luôn))*)$")
_HZ_REPORT = (r"(?:(?:the )?(?:customer|client|caller|tenant|owner|they|he|she|khách(?: hàng)?|anh ấy|chị ấy)\s+"
              r"(?:says?|said|confirms?|confirmed|answered|reports?|reported|nói|bảo|trả lời|xác nhận)\s+(?:là\s+)?)?")
_HZ_YES = re.compile(r"^" + _HZ_REPORT + r"(?:yes|yeah|yep|yup|có|có ạ|dạ có|vâng có|có á|có luôn|đúng rồi|still)$")
_HZ_NO = re.compile(r"^" + _HZ_REPORT + r"(?:no|nope|none|nil|n/a|nothing|không|ko|k|hông|không có|ko có|không ạ|"
                    r"dạ không)$")
# Câu SÀNG LỌC do AI / nhân viên ghi ("Asked about gas smell", "checked for sparks", "hỏi khách về mùi gas"): là câu hỏi,
# câu trả lời ngay sau ("none", "customer says no", "khách nói không" / "yes", "có") quyết định.
_HZ_SCREEN = re.compile(
    r"^\s*(?:(?:i|we|staff|ai)\s+)?(?:(?:asked|checked|screened)\s+(?:(?:the\s+)?(?:customer|client|caller|them)\s+)?"
    r"(?:about|for|if|whether|re)|(?:đã\s+)?(?:hỏi|kiểm tra)(?:\s+(?:khách|khách hàng|lại|anh|chị))?(?:\s+(?:về|xem))?)"
    r"(?:\s+(?:there|there's|is|are|any|a|an|some|the|có|bị))*\s*$")
_HZ_NOUNS = (('gas', re.compile(r"\bgas|\bmùi|\bsmell|\bodou?r")), ('burning', re.compile(r"\bmùi|\bsmell|\bodou?r")),
             ('smoke', re.compile(r"\bsmok|khói")), ('sparks', re.compile(r"\bspark|tia lửa|chập")),
             ('shock', re.compile(r"\bshock|giật")), ('water', re.compile(r"\bwater|\bflood|ngập|nước")),
             ('fire', re.compile(r"\bfire|\bflame|lửa|cháy")), ('co', re.compile(r"\balarm|báo")))


def _fn(name, desc, props, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': desc,
                                             'parameters': {'type': 'object', 'properties': props, 'required': list(required)}}}


TOOLS = [
    _fn('technical_request_job',
        "Create a REAL job request on the business's dispatch board (status: waiting to be assigned). Collect first: the "
        "customer's name and phone number, the full service address, what is wrong, the preferred day and part of day, and "
        "how urgent it is. The team calls back to confirm a time — it is NOT scheduled. Never promise an arrival time or "
        "price. Use urgency 'emergency' only for danger happening now (gas smell, flooding, sparks, smoke from something "
        "electrical, electric shock) — not for a range hood, chimney or smoke alarm job, or a danger the customer rules "
        "out.",
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
           "repair instructions. DANGER happening now (gas smell, flooding, sparks, smoke from something electrical, "
           "electric shock): first tell them to get to a safe place and call the emergency number in the facts, then "
           "create the request with urgency 'emergency'. A range hood, chimney or smoke alarm battery job, or a danger the "
           "customer rules out, is a normal job; if they only ask whether something is dangerous, give that safety "
           "advice without making it an emergency."),
    'vi': ("LUẬT DỊCH VỤ KỸ THUẬT: Em chỉ NHẬN yêu cầu; đội kỹ thuật quyết định ai đi và lúc nào. Trước khi gọi "
           "technical_request_job cần: tên + SĐT khách, địa chỉ đầy đủ (số nhà, đường, phường/quận, thành phố), hỏng gì, ngày "
           "+ buổi mong muốn, mức độ gấp. Không hứa giờ tới, giá sửa, người làm hay \"đã đặt lịch\" — nói đội sẽ gọi xác nhận. "
           "Không chẩn đoán hay hướng dẫn tự sửa. NGUY HIỂM đang xảy ra (mùi gas, ngập nước, tia lửa, khói từ đồ điện, "
           "điện giật): trước hết bảo khách ra chỗ an toàn và gọi số khẩn cấp trong dữ kiện, rồi tạo yêu cầu với urgency "
           "'emergency'. Máy hút mùi, ống khói, pin báo khói hay nguy hiểm khách nói là KHÔNG có là việc thường; khách chỉ "
           "hỏi có nguy hiểm không thì dặn an toàn, không coi là khẩn cấp."),
}


def _err(msg):
    return ai_packs.PackError(msg)


def _hz_norm(text):
    return unicodedata.normalize('NFC', str(text or '')).replace('\u2019', "'").replace('\u2018', "'").lower()


def _hz_statements(t):
    """[(câu, dấu kết thúc)] — tách ở dấu câu / liên từ, rồi TRƯỚC now / today / giờ / hôm nay (câu chỉ còn "now" / "rồi"
    gộp lại câu trước: "I smell gas now" vẫn là 1 câu)."""
    out, pieces, pos = [], [], 0
    for m in _HZ_BREAK.finditer(t):
        pieces.append((t[pos:m.start()], (m.group(1) or '').strip()))
        pos = m.end()
    pieces.append((t[pos:], ''))
    for text, delim in pieces:
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
            if out and words and all(w in _HZ_TRIVIAL for w in words):
                out[-1] = (out[-1][0] + ' ' + s.strip(), d or out[-1][1])
            elif words:
                out.append((s.strip(), d))
            elif d and out:
                out[-1] = (out[-1][0], d)
    return out


def _hz_negated(st, start):
    """Từ khoá bắt đầu ở st[start] bị PHỦ ĐỊNH rõ trong câu ('no gas smell', "I don't smell gas", 'không có mùi khét',
    'hết mùi gas', 'No burning smell or sparks'). Không chắc -> False (= có)."""
    toks = _HZ_WORD.findall(_HZ.sub(' \x00 ', st[:start]))
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
        elif not (t in _HZ_FILLER or (sensed and t in ('the', 'that', 'this', 'those', 'these'))):
            return False
    return not joined


def _hz_hypothetical(st, start, end, question):
    """Từ khoá nằm trong vế GIẢ ĐỊNH ("if there is smoke", "nếu có khói", "có khói thì ... không?") — không phải đang có."""
    toks = _HZ_WORD.findall(st[:start])
    idx = max((i for i, t in enumerate(toks) if t in _HZ_HYPO or (t == 'case' and i and toks[i - 1] == 'in')), default=-1)
    if idx >= 0 and not (toks[idx] == 'if' and idx and toks[idx - 1] in _HZ_UNSURE) and len(toks) - idx - 1 <= 6 \
            and all(t in _HZ_HYPO_FILL or t == '\x00' for t in toks[idx + 1:]):
        return True   # "if there is smoke", "nếu có khói", "in case I smell gas" (không phải "not sure if it's sparking")
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
    if _hz_negated(st, start):
        return 'present' if _HZ_IMPLY.search(st) else 'negated'
    cat = m.lastgroup
    if _HZ_GONE_AFTER.match(st[end:]) or (cat in ('gas', 'burning', 'smoke', 'sparks', 'co')
                                          and _HZ_GONE_AFTER_VI.match(st[end:])):
        return 'negated'
    if _HZ_PAST.search(st) and not _HZ_NOW.search(st):
        return 'past'
    return 'present'


_HZ_RANK = {'present': 4, 'question': 3, 'hypothetical': 3, 'past': 2, 'negated': 1}


def hazard_check(text):
    """(kết luận, {loại nguy hiểm: trạng thái câu cuối}) — xem classify_hazard."""
    t = _hz_norm(text)
    cooking = bool(_HZ_SMOKE_CTX.search(t))
    battery = bool(_HZ_BATTERY.search(t))
    t = _HZ_EXCLUDE.sub(' zzx ', t)
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
            if cat == 'smoke' and cooking and not _HZ_SMOKE_SRC.search(st):
                continue   # khói bếp / khói thuốc / máy hút mùi không hút hết khói
            if cat == 'co' and battery and re.search(r"beep|chirp", m.group()):
                continue   # báo CO kêu bíp vì hết pin
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
    vals = set(states.values())
    return ('danger' if 'present' in vals else 'negated' if 'negated' in vals else 'none'), states


def classify_hazard(text):
    """'danger' | 'negated' | 'none' cho 1 tin nhắn / mô tả việc (xem khối chú thích ở trên)."""
    return hazard_check(text)[0]


def is_emergency(text):
    """True khi có nguy hiểm ĐANG xảy ra (classify_hazard == 'danger')."""
    return classify_hazard(text) == 'danger'


def safety_tip(num, vi):
    """Câu dặn an toàn khi khách có NHẮC nguy hiểm mà không phải đang xảy ra (đã hết, phủ định, chỉ hỏi, chuyện đã lâu)."""
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


def _flag_urgent(ctx, job_id, problem):
    """Khẩn cấp: chuyển cuộc chat cho người thật (cùng các trường handoff_to_staff ghi) để /ai_bot hiện đỏ + AI vào chế độ chờ."""
    cid = ctx.get('customer_id')
    if not cid:
        return
    now = datetime.now().isoformat()
    try:
        db.bot_customers.update_one({'id': cid}, {'$set': {
            'ai_paused': True, 'needs_human': True, 'handoff_reason': f"EMERGENCY job request #{job_id}: {problem[:200]}",
            'handoff_at': now, 'handoff_urgent': True, 'handoff_by_ai': True, 'hold_notice_at': now}})
    except Exception as e:
        print(f"[ai_packs.technical] flag urgent: {e}")


def _escalate(business_id, job, problem, svi):
    """Việc đã có (cùng khách + địa chỉ + ngày) mà giờ khách báo NGUY HIỂM -> urgency 'emergency' (nguyên tử: chỉ 1 lệnh
    nâng) + ghi vào noi_dung (Bảng điều phối / app nhân viên đọc trường này). True nếu lệnh này vừa nâng."""
    now = datetime.now().isoformat()
    before = db.tasks.find_one_and_update(
        {'business_id': business_id, 'id': job.get('id'), 'urgency': {'$ne': 'emergency'}},
        {'$set': {'urgency': 'emergency', 'emergency_problem': problem, 'escalated_at': now, 'escalated_by': 'ai_bot'}})
    if not before:
        return False
    body = before.get('noi_dung') or ''
    old = URGENCY.get(before.get('urgency') or 'normal', URGENCY['normal'])
    new = (body.replace(f"| Mức độ: {old[0]}", f"| Mức độ: {URGENCY['emergency'][0]}", 1)
               .replace(f"| Urgency: {old[1]}", f"| Urgency: {URGENCY['emergency'][1]}", 1)
           + (f"\n--- KHẨN CẤP, khách báo thêm qua chat AI: {problem}" if svi else
              f"\n--- EMERGENCY, the customer added in the AI chat: {problem}"))
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
    pt = _geocode(bid, address)
    if pt:
        doc['lat'], doc['lng'] = pt
    # Tạo nguyên tử theo khoá (cùng khách + cùng địa chỉ + cùng ngày): khách nói "gửi giúp em" 2 lần -> vẫn 1 việc trên bảng
    saved, created = _c.insert_once(db.tasks, bid, key, doc, key_field='ai_dedupe_key')
    emergency = urgency == 'emergency'
    ekey = key + ':emergency'
    for _ in range(10):
        if created or not emergency or (saved or {}).get('trang_thai') != DONE:
            break
        # việc cũ cùng địa chỉ hôm nay đã XONG (kể cả việc khẩn cấp trước đó): nguy hiểm là việc MỚI trên bảng + báo chủ.
        # Khoá nối theo việc đã xong: khách báo lại vẫn chỉ 1 việc đang mở, không bao giờ trả về việc đã Hoàn Thành.
        saved, created = _c.insert_once(db.tasks, bid, ekey, doc, key_field='ai_dedupe_key')
        ekey = f"{key}:emergency:{(saved or {}).get('id')}"
    escalated = False
    num = EMERGENCY_NUMBER.get(str(shop.get('country') or '').upper(), '')
    tip = safety_tip(num, vi) if hazards and not emergency else None   # có nhắc nguy hiểm nhưng không phải đang xảy ra
    # Việc đã có (cùng khoá) chỉ được nêu mã / trạng thái khi chat CHỨNG MINH là chủ: id hội thoại web '<tiệm>:<SĐT gõ>'
    # trình duyệt khác gõ cùng SĐT cũng có -> trả lời chung như fnb / karaoke / hotel, không lộ mã việc của người khác
    mine = created or _c.owns_request(saved, ctx, phone, 'sdt')
    if not created:
        old_id = (saved or {}).get('id')
        if not emergency or old_id is None:
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
        # KHẨN CẤP không bao giờ bị chống trùng nuốt mất: việc đang có được nâng lên khẩn cấp (báo chủ 1 lần), cuộc chat
        # vẫn chuyển người thật và khách vẫn được dặn ra chỗ an toàn + gọi số khẩn cấp
        job_id = old_id
        escalated = _escalate(bid, saved, problem, svi)
    if emergency:
        _flag_urgent(ctx, job_id, problem)
    if escalated:
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
        _c._notify(ctx, shop,
                   f"{'KHẨN CẤP — ' if emergency else ''}Việc mới #{job_id} từ chat AI (đang Chờ Nhận trên Bảng điều phối): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_vi})",
                   f"{'EMERGENCY — ' if emergency else ''}New job #{job_id} from the AI chat (waiting on the dispatch board): "
                   f"{name} {phone}, {address}. {problem[:200]} ({when_en})",
                   f"{'URGENT — ' if emergency else ''}New job request #{job_id} from the AI chat: {name} {phone}, {address}. "
                   f"Problem: {problem[:300]}. Preferred: {when_en}. It is waiting on the dispatch board — please call the customer.",
                   'technical_emergency' if emergency else 'technical_job', phone)
    if emergency:
        ref_vi, ref_en = (f" (việc #{job_id})", f" (job #{job_id})") if mine else ('', '')
        tell = ((f"Nếu có nguy hiểm (mùi gas, tia lửa, khói, nước ngập gần ổ điện), mọi người ra chỗ an toàn và gọi {num or 'cấp cứu'} ngay. "
                 f"Em đã báo đội kỹ thuật yêu cầu KHẨN{ref_vi}; em không hứa được giờ tới, đội sẽ gọi lại cho mình.") if vi else
                (f"If anyone is in danger (gas smell, sparks, smoke, water near power), get everyone somewhere safe and call "
                 f"{num or 'emergency services'} now. I've sent your request to the team as URGENT{ref_en}; I can't promise "
                 "an arrival time — the team will call you.")) + _reply_expectation(bid, vi)
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
        out['note'] += (' The customer mentioned a danger that is not happening now (ruled out, already gone, in the '
                        'past or only asked about): this is not an emergency — do not tell them to evacuate, but pass on '
                        'safety_tip.')
    if not created and not mine:   # khẩn cấp trên việc của 1 chat khác: báo đội + dặn an toàn, KHÔNG lộ mã / trạng thái việc
        return {'success': True, 'request_sent_to_team': True, 'confirmed': False, 'status': 'pending',
                'urgency': urgency, 'tell_customer': tell,
                'note': 'Passed to the team as URGENT; they call the customer. Give no job number and never promise an '
                        'arrival time, a price or who will come.'}
    if not created:   # khẩn cấp trên việc đã có từ trước hôm nay
        out.update({'already_requested': True, 'escalated': escalated,
                    'board_status': {WAITING: 'waiting_for_assignment', TAKEN: 'assigned', DONE: 'completed'}.get(saved.get('trang_thai'), 'in_progress'),
                    'located_on_map': saved.get('lat') is not None,
                    'note': f"Job #{job_id} for this address was already on the dispatch board today — it is now marked "
                            "EMERGENCY and the team has been alerted. Do not create another. Never promise an arrival "
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
