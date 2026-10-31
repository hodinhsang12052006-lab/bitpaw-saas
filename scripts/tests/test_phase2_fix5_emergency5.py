# -*- coding: utf-8 -*-
"""Test OFFLINE — sửa lỗi Phase 2 vòng 5, khu "emergency5" (ai_packs/technical.py): phân loại NGUY HIỂM ưu tiên KHÔNG BỎ
SÓT, 4 mức danger / uncertain / negated / none (technical.classify_hazard / hazard_check) và việc tạo qua công cụ thật.

Hợp đồng được kiểm:
  - tin nhắn có nhắc nguy hiểm chỉ thành 'negated' / 'none' qua phủ định RÕ hoặc cụm không-nguy-hiểm có trong danh sách;
    còn nghi ngờ -> 'uncertain' = việc GẤP + chuyển người thật + báo chủ + câu dặn an toàn CÓ ĐIỀU KIỆN (không bảo sơ tán);
  - từ NHẮC LẠI sau 1 phủ định (now, today, again, still, stronger, worse, came back, keeps, won't stop, can't stop,
    can't get ... to stop / out, giờ, nay, lại, vẫn, càng, nặng hơn — có dấu hay không dấu) -> ít nhất 'uncertain';
  - chuyện đã qua + từ nhắc lại ("Gas smell yesterday, today it is stronger", "Hôm qua có mùi gas, sáng nay vẫn còn") ->
    'danger'; chuyện đã qua không nói gì về hiện tại -> 'uncertain';
  - thành ngữ NÓNG ("burning hot", "scorching", "smoking hot") = 'none', trừ khi chủ ngữ là đồ điện;
  - thiết bị TỰ bốc khói / tóe lửa = 'danger' kể cả máy hút mùi / quạt hút / lò nướng / nồi chiên;
  - chuông / đầu báo khói, gas, CO ĐANG kêu (không phải pin yếu, không phải do nấu ăn) = 'danger';
  - nước tràn chỉ do bồn cầu / máy giặt / máy rửa chén / ống thoát = 'none'; nước gần / chảy vào đồ điện = 'danger'.
Bảng: mọi câu trong báo cáo review (8 mục) + >= 150 câu MỚI (EN + VI, gõ sai, không dấu, trộn ngôn ngữ) + câu sinh tổ hợp.

Dùng lại DB giả + stub của test_phase2_request_packs.py (nạp TRƯỚC mọi gói): không import app.py thật, không MongoDB thật,
không gọi mạng. Chạy: python scripts/tests/test_phase2_fix5_emergency5.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_request_packs as base  # noqa: E402,F401  (cài mongo_client / app / ai_function_tools giả)

from test_phase2_request_packs import CALLS, DB, TECH, ctx, job, seed, technical  # noqa: E402

UNC = 'uncertain+'   # hợp đồng "ít nhất uncertain": 'uncertain' hoặc 'danger'

# ================================================================ báo cáo review (checker3) — 8 mục, đúng nguyên câu
BRIEF = (
    # 1. chuyện đã qua + câu sau nhắc lại -> KHẨN CẤP; đã qua không nói gì thêm -> GẤP
    ('Gas smell yesterday, today it is stronger', 'danger'), ('We smelled gas yesterday and again this morning', 'danger'),
    ('Smelled gas last night, still smells a bit', 'danger'), ('Smelled gas last night and it still smells', 'danger'),
    ("The gas smell started last night and hasn't gone", 'danger'), ('Gas smell started yesterday', 'danger'),
    ('Burning smell started two days ago and is still there', 'danger'),
    ("Had a burning smell yesterday and it's getting worse today", 'danger'),
    ('Hôm qua có mùi gas, sáng nay vẫn còn', 'danger'), ('Tối qua bị chập điện, sáng nay lại chập', 'danger'),
    ('Hôm qua bắt đầu có mùi khét', 'danger'), ('smelled gas last night', 'uncertain'),
    # 2. thiết bị TỰ bốc khói dù có chữ nấu ăn / máy hút mùi / quạt hút
    ('The range hood is smoking', 'danger'), ('The extractor fan is smoking', 'danger'),
    ('Smoke coming out of the bathroom exhaust fan', 'danger'), ('Kitchen exhaust fan smoking, smells electrical', 'danger'),
    ('The induction cooktop is smoking from underneath', 'danger'), ("Toaster is smoking and won't turn off", 'danger'),
    ('The air fryer is smoking from the back', 'danger'), ("Smoke in the hallway, we weren't cooking anything", 'danger'),
    ("There's smoke in the house and we're not cooking", 'danger'),
    ("Oven is smoking but there's nothing inside, we weren't cooking", 'danger'),
    ('I was cooking dinner and noticed smoke coming up from under the floorboards', 'danger'),
    ('máy hút mùi tự nhiên bốc khói', 'danger'), ('máy hút mùi đang chạy thì bốc khói đen', 'danger'),
    ('quạt hút nhà tắm bốc khói', 'danger'),
    # 3. "can't get the smoke to stop" là VẪN đang có, không phải phủ định
    ("Can't get the smoke to stop coming out of the outlet", 'danger'), ("I can't get the sparking to stop", 'danger'),
    ("we can't get the gas smell out of the house", 'danger'),
    # 4. đầu báo gas / CO đang kêu
    ('The gas detector is going off', 'danger'), ('Got a gas leak detector going off', 'danger'),
    ('gas leak detector alarm is sounding in the kitchen', 'danger'), ('Gas alarm going off', 'danger'),
    ('báo động CO đang kêu', 'danger'),
    # 5. thành ngữ nóng (máy lạnh / nước nóng mùa hè) không phải nguy hiểm
    ("It's burning hot in here and the aircon is broken", 'none'), ("It's burning up in the house, aircon not working", 'none'),
    ("It's burning hot", 'none'), ('Hot water is scorching, thermostat broken', 'none'), ('the water is scorching hot', 'none'),
    ('scorching weather, need aircon fixed asap', 'none'), ('Smoking hot day today and the aircon died', 'none'),
    # 6. phủ định rõ trước đây bị báo nhầm; lo sợ = GẤP chứ không phải khẩn cấp
    ('Customer denies any gas smell', 'negated'), ('Gas smell ruled out', 'negated'), ('Nothing is sparking or smoking', 'negated'),
    ("The tenant hasn't reported any gas leak", 'negated'), ('Sparks? not that I know of', 'negated'),
    ('Smoke: not seen', 'negated'), ("There's definitely no gas smell", 'negated'), ('chưa từng bị chập điện', 'negated'),
    ('Từ trước đến giờ không có mùi khét', 'negated'), ('không dám bật vì sợ chập điện', 'uncertain'),
    # 7. nước tràn chỉ do ống nước
    ('The toilet overflowed and flooded the bathroom floor', 'none'),
    ('Dishwasher flooded the kitchen floor, need a plumber', 'none'),
    ('Washing machine hose burst and flooded the laundry', 'none'), ('bồn cầu bị tắc, nước tràn ngập nhà vệ sinh', 'none'),
    ('máy giặt rò nước ngập sàn nhà tắm', 'none'),
    # 8. trước đây bỏ sót (EN, VI, trộn, gõ sai, không dấu); câu HỎI giả định = GẤP
    ('smells gassy in the laundry', 'danger'), ('Hissing noise coming from the gas pipe under the house', 'danger'),
    ('Saw a flash and a loud bang from the switchboard', 'danger'), ('The plug is melted and black', 'danger'),
    ('my son got shocked by the light switch', 'danger'), ('I got shocked touching the oven', 'danger'),
    ('Rain is getting into the fuse box', 'danger'), ('Hot water tank burst and the laundry is under water', 'danger'),
    ('grease fire on the stove', 'danger'), ('the switchboard is buzzing and smells hot', 'danger'),
    ('ổ điện nổ tách tách, có lửa', 'danger'), ('trần nhà dột nước xuống bóng đèn', 'danger'),
    ('máy lạnh chảy nước xuống ổ cắm', 'danger'), ('dây điện sau tủ lạnh bị nóng chảy vỏ', 'danger'),
    ('nhà em ngửi thấy mùi gì như gas, sợ quá', 'danger'), ('bị shock điện khi chạm máy giặt', 'danger'),
    ('aircon có mùi burning', 'danger'), ('smeel gas in kitchen', 'danger'), ('gas leek in the kitchen', 'danger'),
    ('spaking outlet', 'danger'), ('burining smell from the switch', 'danger'), ('smokeing from the plug', 'danger'),
    ('got a elecrtic shock from the tap', 'danger'), ('co mui ga trong bep', 'danger'), ('ro ri ga o binh', 'danger'),
    ('nha bi ngap', 'danger'), ('What do I do if the outlet starts sparking again?', 'uncertain'),
)

# ================================================================ câu MỚI (không trùng bảng cũ)
PAST_AGAIN_DANGER = (   # đã qua + nhắc lại / bắt đầu từ trước và còn -> KHẨN CẤP
    "Smelled gas yesterday and it's still there", 'gas smell last night, its worse today',
    'There was a burning smell last week, it came back today', 'sparked yesterday, keeps sparking',
    'The outlet sparked yesterday and again just now', 'Smelt gas last night and this morning',
    "We noticed a gas smell 2 days ago and it hasn't gone away", 'Burning smell since last night',
    "smoke from the outlet yesterday, it won't stop", 'Had sparks last week. They came back',
    "smelled gas last night, can't get it to go away", 'Burning smell yesterday and now again',
    'smelt gas last nite, still smells', 'Gas smell started last week and keeps getting stronger',
    'The sparking started a few days ago', "burning smell last night that won't go away",
    "We had sparks from the outlet last week and it's happening again", 'last week it sparked, today it smells burnt',
    'Hôm qua có mùi khét, giờ vẫn còn', 'Tối qua ngửi thấy mùi gas, sáng nay mùi nặng hơn',
    'Hôm kia bị chập điện, hôm nay lại bị', 'Tuần trước ổ cắm có tia lửa, giờ lại có',
    'Hôm qua có mùi gas, càng lúc càng nồng', 'Đêm qua có khói từ ổ cắm, sáng nay vẫn bốc khói',
    'Mùi khét từ hôm qua tới giờ', 'Hôm qua bắt đầu bị chập điện',
    'hom qua co mui gas, gio van con', 'hom qua bi chap dien, nay lai bi',
)
PAST_UNCERTAIN = (   # đã qua, không nói gì về hiện tại -> GẤP (người thật gọi hỏi còn không)
    'The outlet sparked yesterday', 'smelled burning plastic last week', 'Had a gas leak a few months ago',
    'Last night there was smoke from the heater', 'Got a shock from the oven last week', 'sparked once last month',
    'The switchboard sparked once last month, works fine since', 'There was a gas leak last year that was fixed',
    'Hôm qua có mùi khét', 'Tuần trước bị chập điện', 'tối qua ổ cắm bốc khói', 'Hồi trước có bị chập điện, đã sửa rồi',
)
NEG_THEN_AGAIN = (   # phủ định rồi NHẮC LẠI -> ít nhất GẤP
    'No burning smell before, now it\'s stronger', 'No gas smell. Still smells weird though',
    'Not sparking at the moment, but it keeps happening', 'No smoke right now but it came back twice',
    "I don't smell gas now, but it was worse this morning", "No gas smell, but it won't stop hissing",
    "The burning smell went away, now it's back", 'It stopped sparking, but it keeps tripping and sparking again',
    "No sparks, can't get it to stop buzzing", 'No smoke today. Again this afternoon', 'The gas smell is gone, it came back',
    "No gas smell, but now I'm not sure", "No sparks. Today it's not stopping",
    "No burning smell yesterday. Today it's really bad, please come asap", "No smoke this morning, it's back again",
    'No sparks, still happening though', "No gas smell, it's stronger in the morning", 'Not smoking, worse when the heater runs',
    'No sparks but it keeps doing it', "No smoke, won't stop beeping", "No burning smell, can't stop the breaker tripping",
    "No gas smell now, but I can't get it to stop hissing", 'No gas smell. Can you come today?',
    'no sparks, but it happened again', "The gas smell has gone but I'm worried it will come back",
    'Không có mùi khét, giờ thì nặng hơn', 'Không còn mùi gas, nhưng lại có rồi', 'Hết khói rồi mà vẫn còn mùi',
    'không có tia lửa nhưng vẫn bị', 'Không ngửi thấy mùi gas, nay lại thấy', 'Không thấy khói, càng lúc càng nặng mùi',
    'Không thấy tia lửa, vẫn bị nhảy cầu dao', 'Không có mùi gas nữa, càng ngày càng hôi', 'Không còn chập điện nhưng nặng hơn',
    'Không có mùi gas, giờ thì không chịu nổi', 'Không bị điện giật nữa, nhưng hôm nay lại bị',
    'hết mùi gas rồi nhưng vẫn còn hơi hơi', 'Không có tia lửa, nhưng nó cứ lại bị',
    'ko co mui khet, gio lai co', 'khong co mui gas nhung van con', 'het mui khet roi ma gio lai bi',
    'khong co mui gas, nay lai co', 'ko thay tia lua, van bi chap', 'het mui khet roi ma van con',
    'khong con mui khet, gio nang hon', 'khong co mui gas, cang luc cang nong',
)
GONE_THEN_BACK_DANGER = (   # đã hết rồi CÓ LẠI -> KHẨN CẤP
    'No gas smell earlier, but now there is', 'The sparks stopped but they came back', 'Hết mùi khét rồi lại có',
    'het mui gas roi lai co',
)
NEGATED_NEW = (   # phủ định / đã hết RÕ, không nhắc lại -> việc thường + câu dặn an toàn
    'No smell of gas at all', 'Absolutely no sparks', "There isn't any smoke", 'never smelled gas in the house',
    'Gas smell? none', "I can confirm there's no gas leak", 'Customer denied smelling gas',
    'The tenant has not noticed any burning smell', 'Nobody has smelled gas', 'No one has smelled gas',
    'No electric shock, just no power', 'No sparks or smoke at all, it just won\'t turn on',
    'No flooding near the switchboard', 'gas smell ruled out by the gas company', 'No gas smell, just a noisy heater',
    'No sparks, the breaker just trips', 'No smoke or sparks, just no power', 'No gas smell, still nothing',
    "No sparks since. It hasn't come back", 'No burning smell or anything worse', "The gas smell is gone and hasn't come back",
    'No sparks or burning smell since the breaker was replaced',
    'không hề có mùi gas', 'Không có hiện tượng chập điện', 'chưa bao giờ bị giật điện', 'không có khói hay mùi khét gì cả',
    'Không có mùi khét, chỉ không lạnh', 'Không có tia lửa, chưa bị lại', 'Đã hết mùi gas, không bị lại nữa',
    'Không có mùi gas. Giờ vẫn không có', 'Không ai bị điện giật', 'Chưa ai ngửi thấy mùi gas',
    'Không có mùi gas, cũng không có tia lửa', 'ko co mui gas', 'khong co mui khet, chi khong lanh', 'mui gas het roi',
)
HEAT_NONE = (   # thành ngữ nóng: việc máy lạnh / nước nóng thường
    'burning hot outside, aircon not cooling', "It's scorching today and the AC stopped",
    'boiling hot in the bedroom, split system not working', 'the house is baking hot, aircon broke',
    'Scorcher of a day, aircon died', 'the shower water is burning hot', 'Water coming out of the tap is scorching',
    "it's smoking hot in here, need AC", 'the aircon is blowing burning hot air', 'its burnin hot in the lounge, ac wont turn on',
    "It's burning hot outside and the AC won't cool", 'its scorching in the bedroom', "It's boiling hot, aircon stuffed",
    'burning hot tap water', 'The hot water is way too hot, burning hot from the tap', 'The heater is smoking hot',
    'Trời nóng như đốt, máy lạnh hư', 'trời nắng cháy da, máy lạnh không mát', 'nóng như thiêu, máy lạnh hỏng',
    'trời nóng cháy người, cần sửa máy lạnh gấp',
)
HOT_ELECTRICS_DANGER = (   # đồ ĐIỆN nóng bỏng / cháy -> KHẨN CẤP
    'The plug is burning hot', 'the outlet is scorching', 'power board is scorching hot', 'the charger gets burning hot and smells',
    'The extension cord is burning up', 'The heater smells like burning', 'The power point is burning hot',
    'the light switch is burning hot to touch', 'The fuse box feels scorching hot', 'charger is smoking hot',
    'The power board is smoking hot',
)
DEVICE_SMOKE_DANGER = (   # thiết bị TỰ bốc khói / tóe lửa
    'range hood sparking', 'The rangehood light is sparking', 'smoke coming from the range hood motor',
    'The exhaust fan in the bathroom is smoking and smells like burning', 'The oven is smoking even though nothing is in it',
    'Smoke from the toaster', 'The kettle is smoking', 'the microwave sparked and smoked',
    'Range hood is sparking and smoking while we cook', 'the exhaust fan started smoking', 'smoke pouring out of the extractor',
    'the rangehood is smoking', 'Exhaust fan making smoke', 'smoke from the exhaust fan when cooking',
    'the toaster oven is sparking', 'sparks from the range hood switch',
    'máy hút mùi bị chập, bốc khói', 'quạt hút bị cháy mô tơ, có khói', 'lò nướng bốc khói dù không nấu gì',
    'bếp từ bốc khói ở dưới', 'máy hút mùi có khói đen bốc ra', 'khói bốc ra từ máy hút mùi', 'quạt hút mùi bị cháy, có mùi khét',
    'lò vi sóng bốc khói', 'nồi chiên không dầu bốc khói', 'máy nướng bánh mì bốc khói', 'may hut mui boc khoi',
)
COOK_SMOKE_NONE = (   # khói NẤU ĂN / máy hút mùi không hút hết khói: việc thường
    'range hood not clearing smoke', "Rangehood doesn't suck out the cooking smoke",
    'Kitchen gets smoky when we fry, need a better hood', 'Need a new range hood, too much smoke when cooking',
    'Smoke from cooking lingers in the kitchen', 'khói bếp không thoát được, cần lắp máy hút mùi',
    'Bếp nhiều khói khi chiên, máy hút mùi yếu',
)
ALARM_DANGER = (   # chuông / đầu báo ĐANG kêu
    "Smoke alarm going off and won't stop", 'smoke detector is beeping non stop', 'CO detector went off',
    'carbon monoxide detector is sounding', 'Gas detector beeping', 'the gas leak alarm is going off',
    'heat detector activated in the kitchen', 'Fire alarm is going off in the building', 'the co alarm keeps going off',
    'smoke alarms all went off at once', 'smoke detector going off for no reason', 'The CO alarm is going off, battery is new',
    'Smoke alarm keeps going off, we replaced the battery', 'smoke alarm going off, battery was just replaced',
    'gas alarm sounding in the kitchen', 'Fire alarm going off', "Smoke alarm is going off and it's not from cooking",
    'smoke alarm keeps going off not from cooking', 'báo khói đang hú', 'chuông báo cháy reo liên tục', 'đầu báo gas kêu',
    'máy báo gas đang kêu', 'chuông báo khói kêu inh ỏi', 'báo cháy đang kêu, không phải do nấu ăn', 'bao khoi dang keu',
    'bao gas keu lien tuc', 'bao chay dang reo',
)
ALARM_NONE = (   # pin yếu / do nấu ăn / chỉ là tên thiết bị
    'Smoke alarm battery low, keeps beeping', 'smoke alarm beeps every 30 seconds, need new battery', 'CO alarm chirping, low battery',
    'Smoke alarm goes off whenever I cook', 'Smoke alarm goes off every time someone showers', 'Install a gas detector',
    'replace the CO detector', 'smoke detector chirps, battery needs replacing', 'CO detector beeping, needs a new battery',
    'Smoke alarm went off when I was cooking', "smoke alarm goes off when we're cooking", 'Smoke alarm chirping, needs a new battery',
    'báo khói kêu do hết pin', 'báo khói kêu mỗi khi nấu ăn', 'lắp đầu báo gas', 'báo khói kêu bíp bíp do hết pin',
    'thay pin bao khoi',
)
PLUMBING_NONE = (   # nước tràn chỉ do ống nước, không gần điện
    'Toilet overflowing, bathroom floor flooded', 'Kitchen sink overflowed and flooded the floor',
    'The bath overflowed, bathroom is flooded', 'shower drain blocked, bathroom flooding',
    'Dishwasher leaking and flooding the kitchen', 'Washing machine overflowed and the laundry is flooded',
    'Toilet cistern overflowing, floor is flooded, need plumber today', 'water coming out of the shower outlet',
    'Floor waste outlet blocked, bathroom flooded', 'Need a power point installed near the water heater', 'water heater leaking',
    'Aircon outlet dripping water', 'bồn rửa chén bị nghẹt, nước tràn ngập bếp', 'bồn cầu tràn nước ra sàn',
    'bon cau bi tac, nuoc ngap san', 'may giat ro nuoc ngap nha tam', 'may rua chen ro nuoc ngap bep',
)
WET_ELECTRICS_DANGER = (   # nước GẦN / chảy vào đồ điện
    'Toilet overflowed and water is near the power point',
    'Washing machine flooded the laundry and the power board is in the water',
    'Dishwasher leaked into the power point behind it', 'Water leaking from the ceiling onto the light',
    'The basement is flooded and the power is still on', 'Bathroom flooded from the shower, water near the heater power point',
    'water dripping out of the downlight', 'Water leaking into the switchboard',
    'Toilet overflowed, water running towards the power board', 'the laundry is flooded and the washing machine is plugged in',
    'Water coming through the downlights', 'Rain coming in around the meter box', 'Water in the switchboard',
    'water on the floor next to the power board', 'Hot water system leaking near the power point', 'HWS burst',
    'Water dripping from the light', 'Light fitting dripping water', 'the downlight is leaking',
    'nước tràn từ máy giặt vào ổ cắm', 'rò nước từ trần xuống bóng đèn', 'nước dột xuống công tắc', 'tủ điện bị ngấm nước',
    'nước tràn tới ổ cắm', 'nước ngập gần ổ điện', 'trần nhà dột, nước nhỏ xuống đèn', 'máy giặt rò nước, ổ cắm bị ướt',
    'nuoc chay vao o cam', 'o cam bi uot', 'nuoc tran vao o dien', 'nha bi ngap nuoc',
)
QUESTION_UNCERTAIN = (   # hỏi / nhờ kiểm tra / lo sợ: chưa ai nói là CÓ -> GẤP
    'Is there a gas smell?', 'Can you check for a gas leak?', 'Please check for gas leaks',
    'Need someone to check for a gas leak', 'Can you check if there\'s a gas leak?', 'Can someone test for carbon monoxide?',
    'Is it normal for an outlet to spark?', 'Should I worry if the smoke alarm goes off?', 'Should I be worried about sparks?',
    "I'm scared it will catch fire", 'Afraid of a gas leak', 'in case there is a gas leak, what should I do?',
    'scared there might be a gas leak',
    'Có mùi gas không ạ?', 'sợ bị chập điện', 'Có nguy cơ cháy nổ không?', 'kiểm tra giúp xem có rò rỉ gas không',
    'kiem tra giup xem co ro ri gas khong',
)
DANGER_NEW = (   # đang xảy ra (EN, VI, trộn, gõ sai, không dấu, phủ định chỉ phủ 1 vế)
    "No idea why but there's smoke", 'Not sure, but I think I smell gas', "No power and there's smoke coming out",
    'No power, smoke coming from the meter box', 'No power since the sparks', 'Never seen this before, sparks everywhere',
    'No one is home and the smoke alarm is going off', "Nobody knows why it's sparking", 'Nothing works and it smells like burning',
    'None of the lights work, burning smell from the switchboard', "The fridge isn't cold and smells like gas",
    'No hot water, gas smell near the meter', "No gas supply but there's a gas smell", 'Gas smell? Not sure',
    "Hmm I don't know if there's a gas leak", "The electrician said there's no gas leak but I can still smell it",
    'No visible smoke but it smells really smoky', "No sparks that I can see, but there's a crackling sound from the outlet",
    'the switchboard is crackling', 'popping sound coming from the power point', "There's no smoke but the outlet is sparking",
    "It doesn't smell like gas, it smells like burning plastic", 'Is it normal that my outlet is sparking?',
    'Should I turn off the power, the outlet is sparking?', "Should I evacuate? There's a strong gas smell",
    'Could the burning smell be from the fan?', 'carbon monoxide poisoning symptoms, headaches, heater on',
    'Không có gì nguy hiểm, chỉ có mùi khét nhẹ', 'Không có ai ở nhà, tủ điện bốc khói',
    'Không có ai ở nhà mà báo khói đang kêu', 'Không có mùi gas nhưng có tia lửa', 'nhà có mùi gas, sợ quá',
    "I'm scared there's smoke coming out of the wall", "afraid there's a gas leak in the laundry",
    # gõ sai
    'smel of gas in the kichen', 'gas smel near the heater', 'i smell gass', 'sparkes from the plug', 'burnign smell',
    'burnt smell from the fridge', 'smokey smell from the outlet', 'electic shock from the tap', 'got electricuted by the fence',
    'the sockit is sparkng', 'spraks from the switchbord', 'gas leek under the house', 'smelll gas', 'gass smell',
    'burnning smell from the heater', 'the plug is sparkign', 'elecrical fire in the roof', 'the outlet is smokin',
    'theres smoek from the plug', 'gas leack in the laundry', 'I got zapped by the toaster',
    # không dấu
    'o cam bi chap', 'o cam boc khoi', 'binh ga bi xi', 'may lanh boc khoi den', 'o cam bi nong chay', 'cong tac co mui khet',
    'ko sao, mui gas thoi', 'nha co mui gas', 'o dien boc chay', 'bep ga bi xi', 'tu dien boc khoi', 'mui khet tu o cam',
    'o cam co tia lua',
    # trộn tiếng Việt / tiếng Anh
    'ổ cắm bị spark', 'máy lạnh có smoke', 'có gas leak ở bếp', 'bị electric shock khi chạm tủ lạnh', 'outlet có tia lửa',
    'smell khét từ ổ cắm', 'tủ lạnh bị shock điện', 'ổ cắm có burning smell',
)
LISTED_NONE = (   # cụm KHÔNG nguy hiểm trong danh sách
    'smoke alarm install', 'Gas fitter needed', 'gas bottle swap', 'Gas hot water not heating', 'Fire extinguisher service',
    'flood lights install', 'Smoke detector test', 'Smoke alarm compliance check for rental', 'Install a carbon monoxide detector',
    'smoked glass shower screen', 'BBQ gas bottle refill', 'Burnt out light bulb', 'the fire in the fireplace won\'t stay lit',
    'gas log fire won\'t ignite', 'the plug keeps popping out of the socket', 'khói nhang làm đen trần',
    'dịch vụ phun khói diệt muỗi', 'báo giá lắp đặt hệ thống báo cháy', 'sửa bếp gas không lên lửa', 'bếp gas lửa yếu',
    'vệ sinh máy lạnh, máy chảy nước',
)
ORDINARY_NONE = (   # việc thường hay gặp: các mẫu mới (nước gần đồ điện, lách tách, không dấu...) không được báo nhầm
    'Install 3 power points in the kitchen', 'Water heater installation near the laundry', 'Rain water tank pump not working',
    'Garden lights not working after the rain', 'Outdoor power point near the pool', 'RCD keeps tripping after rain',
    'Water stains on the ceiling near the light', 'Need a waterproof power point outside',
    'Install a water heater and a new power point', 'need gas hot water fixed today', 'Can you come today to fix the oven?',
    'The aircon is still not working after the last repair', "Last week you replaced the switch, now it's loose again",
    'Lắp ổ cắm gần bồn rửa', 'Hôm qua thợ đã sửa máy lạnh, giờ vẫn không lạnh', 'bình nóng lạnh không nóng, cần thợ hôm nay',
    'máy lạnh kêu to, chảy nước', 'lap dat may lanh', 'may lanh khong lanh', 'quat tran bi rung',
)
NEW = ([(t, 'danger') for t in PAST_AGAIN_DANGER] + [(t, 'uncertain') for t in PAST_UNCERTAIN]
       + [(t, UNC) for t in NEG_THEN_AGAIN] + [(t, 'danger') for t in GONE_THEN_BACK_DANGER]
       + [(t, 'negated') for t in NEGATED_NEW] + [(t, 'none') for t in HEAT_NONE]
       + [(t, 'danger') for t in HOT_ELECTRICS_DANGER] + [(t, 'danger') for t in DEVICE_SMOKE_DANGER]
       + [(t, 'none') for t in COOK_SMOKE_NONE] + [(t, 'danger') for t in ALARM_DANGER] + [(t, 'none') for t in ALARM_NONE]
       + [(t, 'none') for t in PLUMBING_NONE] + [(t, 'danger') for t in WET_ELECTRICS_DANGER]
       + [(t, 'uncertain') for t in QUESTION_UNCERTAIN] + [(t, 'danger') for t in DANGER_NEW]
       + [(t, 'none') for t in LISTED_NONE] + [(t, 'none') for t in ORDINARY_NONE])
_VI_CHARS = 'ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ'
_NO_DIACRITIC_VI = re.compile(r"\b(?:mui|khet|khoi|chap|dien|nuoc|ngap|tia lua|o cam|o dien|bao|ko|khong|het|hom qua|"
                              r"giat|gio|van|lai|cang|nang hon|binh ga|bep ga|tu dien|cong tac|may|nha)\b")


def _ok(verdict, want):
    return verdict in ('danger', 'uncertain') if want == UNC else verdict == want


def alerts():
    return [c for c in CALLS if c[0] == 'alert']


# ================================================================ 1. bảng câu
class HazardTableTests(unittest.TestCase):
    def test_table_size_languages_typos_and_no_overlap(self):
        import test_phase2_fix3_requests3 as old
        texts = [t for t, _ in NEW]
        self.assertEqual(len(set(texts)), len(texts), 'duplicate rows')
        self.assertFalse(set(texts) & {t for t, _ in old.TABLE}, 'rows already in the round-3 table')
        self.assertFalse(set(texts) & {t for t, _ in BRIEF}, 'rows already in the brief block')
        self.assertGreaterEqual(len(NEW), 150)
        vi = [t for t in texts if any(ch in t.lower() for ch in _VI_CHARS)]
        no_dia = [t for t in texts if t not in vi and _NO_DIACRITIC_VI.search(t.lower())]
        self.assertGreaterEqual(len(vi), 50)
        self.assertGreaterEqual(len(no_dia), 25)
        self.assertGreaterEqual(len(texts) - len(vi) - len(no_dia), 120)
        for want in ('danger', 'uncertain', 'negated', 'none', UNC):
            self.assertGreaterEqual(sum(w == want for _, w in NEW), 15, want)

    def test_every_review_phrase(self):
        for txt, want in BRIEF:
            with self.subTest(txt=txt):
                self.assertEqual(technical.classify_hazard(txt), want)
                self.assertEqual(technical.is_emergency(txt), want == 'danger')

    def test_every_new_phrase(self):
        for txt, want in NEW:
            with self.subTest(txt=txt, want=want):
                v = technical.classify_hazard(txt)
                self.assertTrue(_ok(v, want), f'{v} (states {technical.hazard_check(txt)[1]})')

    def test_a_hazard_mention_only_becomes_normal_through_an_explicit_negation_or_a_listed_phrase(self):
        for txt, want in BRIEF + tuple(NEW):
            verdict, states = technical.hazard_check(txt)
            with self.subTest(txt=txt):
                if verdict == 'none':
                    self.assertEqual(states, {})                         # cụm trong danh sách: không còn từ khoá nào
                elif verdict == 'negated':
                    self.assertEqual(set(states.values()), {'negated'})   # MỌI lần nhắc đều phủ định rõ
                else:
                    self.assertTrue(states)

    def test_past_states_and_last_statement(self):
        self.assertEqual(technical.hazard_check('smelled gas last night'), ('uncertain', {'gas': 'past'}))
        self.assertEqual(technical.hazard_check('Gas smell yesterday, today it is stronger'), ('danger', {'gas': 'present'}))
        self.assertEqual(technical.hazard_check('Không có mùi gas, giờ thì nặng hơn'), ('uncertain', {'gas': 'uncertain'}))
        self.assertEqual(technical.hazard_check('Hết mùi khét rồi lại có'), ('danger', {'burning': 'present'}))
        self.assertEqual(technical.hazard_check('Can you check for a gas leak?'), ('uncertain', {'gas': 'question'}))
        self.assertEqual(technical.hazard_check('No one has smelled gas'), ('negated', {'gas': 'negated'}))


# ================================================================ 2. tổ hợp sinh ra theo hợp đồng
class HazardContractComboTests(unittest.TestCase):
    NEG_EN = ('No gas smell', "I don't smell gas", 'No sparks', "There's no smoke", 'No burning smell', 'Not sparking',
              'The gas smell is gone', 'The sparks stopped')
    NEG_VI = ('Không có mùi gas', 'Không thấy tia lửa', 'Hết mùi khét rồi', 'khong co mui gas', 'ko thay tia lua',
              'Không còn khói')
    AGAIN_EN = ("but now it's back", 'today it is stronger', 'again this morning', "it's still there", "it's getting worse",
                'it came back', 'it keeps happening', "it won't stop", "I can't stop it", "can't get it to stop", 'now', 'today',
                'still', 'worse now', 'stronger today', 'keeps coming back', "but it won't stop", "can't get it out",
                "it's back now", "now it's really bad")
    AGAIN_VI = ('giờ lại có', 'nay vẫn còn', 'lại bị', 'vẫn còn', 'càng lúc càng nồng', 'nặng hơn', 'giờ', 'hôm nay lại có',
                'sáng nay vẫn bị', 'gio lai co', 'nay van con', 'van con', 'cang luc cang nang', 'nang hon', 'lai bi roi')

    def test_re_assertion_words_after_a_negation_are_at_least_uncertain(self):
        for negs, agains, seps in ((self.NEG_EN, self.AGAIN_EN, (', ', '. ', ' but ')),
                                   (self.NEG_VI, self.AGAIN_VI, (', ', '. ', ' nhưng '))):
            for neg in negs:
                self.assertEqual(technical.classify_hazard(neg), 'negated', neg)
                for again in agains:
                    for sep in seps:
                        txt = f'{neg}{sep}{again}'
                        with self.subTest(txt=txt):
                            self.assertIn(technical.classify_hazard(txt), ('danger', 'uncertain'))

    def test_past_plus_re_assertion_is_an_emergency(self):
        for past, agains in ((('Smelled gas yesterday', 'Sparks last night', 'Had a burning smell last week',
                               'The outlet smoked two days ago'),
                              ('today it is stronger', 'again this morning', "it's still there", "it's getting worse",
                               'it came back', 'it keeps happening', "it won't stop", 'still smells', "and it hasn't gone",
                               'this morning too')),
                             (('Hôm qua có mùi gas', 'Tối qua bị chập điện', 'Tuần trước ổ cắm bốc khói'),
                              ('sáng nay vẫn còn', 'nay lại bị', 'giờ vẫn còn', 'càng lúc càng nặng', 'nặng hơn', 'lại có rồi'))):
            for p in past:
                self.assertEqual(technical.classify_hazard(p), 'uncertain', p)
                for again in agains:
                    with self.subTest(txt=f'{p}, {again}'):
                        self.assertEqual(technical.classify_hazard(f'{p}, {again}'), 'danger')

    def test_any_appliance_that_is_itself_smoking_or_sparking_is_an_emergency(self):
        devices = ('range hood', 'rangehood', 'exhaust fan', 'extractor fan', 'bathroom exhaust fan', 'cooktop',
                   'induction cooktop', 'toaster', 'oven', 'air fryer', 'microwave', 'kettle', 'dishwasher', 'dryer', 'heater',
                   'aircon', 'fridge')
        forms = ('The {d} is smoking', 'Smoke coming out of the {d}', 'The {d} is sparking', 'sparks from the {d}',
                 'the {d} started smoking', '{d} smoking from the back', 'smoke pouring out of the {d} while we were cooking')
        vi_devices = ('máy hút mùi', 'quạt hút', 'bếp từ', 'lò nướng', 'nồi chiên', 'lò vi sóng', 'máy nướng bánh mì',
                      'ấm siêu tốc', 'máy lạnh', 'tủ lạnh')
        vi_forms = ('{d} bốc khói', '{d} có tia lửa', 'khói bốc ra từ {d}', '{d} tự nhiên bốc khói đen', '{d} bị chập điện')
        for ds, fs in ((devices, forms), (vi_devices, vi_forms)):
            for d in ds:
                for f in fs:
                    txt = f.format(d=d)
                    with self.subTest(txt=txt):
                        self.assertEqual(technical.classify_hazard(txt), 'danger')

    def test_heat_idioms_are_not_hazards_unless_the_subject_is_electrical(self):
        for idiom in ("It's burning hot in here", "It's scorching today", 'Smoking hot day', 'boiling hot in the house',
                      'burning up in the bedroom', 'the water is scorching', 'scorching weather', "it's baking hot"):
            for rest in (' and the aircon is broken', ', need the AC fixed', ', split system not cooling',
                         ', hot water thermostat broken'):
                with self.subTest(txt=idiom + rest):
                    self.assertEqual(technical.hazard_check(idiom + rest), ('none', {}))
        for txt in ('The plug is burning hot', 'the outlet is scorching', 'The power board is smoking hot',
                    'the switch is burning hot', 'The charger is burning hot', 'The extension cord is scorching hot'):
            with self.subTest(txt=txt):
                self.assertEqual(technical.classify_hazard(txt), 'danger')


# ================================================================ 3. qua công cụ thật: mức gấp, chuyển người, câu dặn
class HazardJobToolTests(unittest.TestCase):
    def setUp(self):
        seed()
        self.cid = f'{TECH}:0412345678'
        DB.bot_customers.insert_one({'id': self.cid})

    def fresh(self):
        DB.bot_customers.update_one({'id': self.cid}, {'$set': {'needs_human': None, 'ai_paused': None,
                                                                 'handoff_urgent': None}})
        CALLS.clear()

    def run_job(self, problem, i, **kw):
        self.fresh()
        return job(customer_id=self.cid, args={'problem': problem, 'address': f'{i + 1} King St, Newtown NSW', **kw})

    def test_uncertain_is_urgent_with_a_person_an_owner_alert_and_a_conditional_safety_line(self):
        rows = ('smelled gas last night', 'Can you check for a gas leak?', 'No gas smell. Can you come today?',
                'The outlet sparked yesterday', "I'm scared it will catch fire", 'Không có mùi khét, giờ thì nặng hơn',
                'khong con mui khet, gio nang hon', 'What do I do if the outlet starts sparking again?')
        for i, problem in enumerate(rows):
            with self.subTest(problem=problem):
                self.assertEqual(technical.classify_hazard(problem), 'uncertain')
                out = self.run_job(problem, i)
                self.assertEqual(out['urgency'], 'urgent')
                self.assertTrue(out['possible_hazard'])
                tell = out['tell_customer']
                self.assertIn('URGENT', tell)
                self.assertIn('right now, leave the area and call 000', tell)          # câu dặn CÓ ĐIỀU KIỆN
                for evacuate in ('somewhere safe', 'get everyone', 'If anyone is in danger'):
                    self.assertNotIn(evacuate, tell)                                   # không bảo sơ tán ngay
                self.assertNotIn('safety_tip', out)
                self.assertIn('Do not tell them to evacuate', out['note'])
                bc = DB.bot_customers.find_one({'id': self.cid})
                self.assertTrue(bc['needs_human'] and bc['handoff_urgent'] and bc['ai_paused'])
                self.assertIn('POSSIBLE HAZARD', bc['handoff_reason'])
                self.assertEqual([a[4] for a in alerts()], ['technical_hazard_check'])
                self.assertIn('possible hazard', alerts()[0][3])
                t = DB.tasks.find_one({'id': out['job_id']})
                self.assertEqual((t['urgency'], t['possible_hazard_problem']), ('urgent', problem))
                self.assertIn('Urgency: URGENT', t['noi_dung'])

    def test_vi_shop_uncertain_reply_is_conditional_with_114(self):
        DB.businesses.insert_one({'id': 'tech_vn5', 'name': 'Điện lạnh Q5', 'currency': 'VND', 'country': 'VN',
                                  'industry_code': 'technical'})
        out = technical.execute('technical_request_job', {'customer_name': 'Anh Nam', 'phone': '0901 234 567',
                                                          'address': '5 Lê Lợi, Quận 1, TP HCM',
                                                          'problem': 'Hôm qua có mùi khét'}, ctx('tech_vn5', lang='vi'))
        self.assertEqual(out['urgency'], 'urgent')
        self.assertIn('mức GẤP', out['tell_customer'])
        self.assertIn('Nếu ngay lúc này', out['tell_customer'])
        self.assertIn('gọi 114', out['tell_customer'])
        self.assertNotIn('KHẨN', out['tell_customer'])
        t = DB.tasks.find_one({'id': out['job_id']})
        self.assertIn('Mức độ: GẤP', t['noi_dung'])

    def test_brief_dangers_are_emergencies_and_brief_false_alarms_are_normal_jobs(self):
        dangers = [t for t, w in BRIEF if w == 'danger']
        for i, problem in enumerate(dangers[:12] + dangers[-6:]):
            with self.subTest(problem=problem):
                out = self.run_job(problem, i)
                self.assertEqual(out['urgency'], 'emergency')
                self.assertIn('somewhere safe', out['tell_customer'])
                self.assertIn('000', out['tell_customer'])
                self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])
                self.assertTrue(DB.bot_customers.find_one({'id': self.cid})['needs_human'])
        nones = [t for t, w in BRIEF if w == 'none'] + list(PLUMBING_NONE[:3]) + list(HEAT_NONE[:3])
        for i, problem in enumerate(nones):
            with self.subTest(problem=problem):
                out = self.run_job(problem, 100 + i)
                self.assertEqual(out['urgency'], 'normal')
                self.assertNotIn('000', out['tell_customer'])
                self.assertNotIn('safety_tip', out)
                self.assertEqual([a[4] for a in alerts()], ['technical_job'])
                self.assertFalse(DB.bot_customers.find_one({'id': self.cid}).get('needs_human'))

    def test_clearly_ruled_out_is_a_normal_job_with_the_safety_tip(self):
        for i, problem in enumerate(('Customer denies any gas smell', 'Nothing is sparking or smoking', 'Không ai bị điện giật',
                                     "The gas smell is gone and hasn't come back")):
            with self.subTest(problem=problem):
                out = self.run_job(problem, i)
                self.assertEqual(out['urgency'], 'normal')
                self.assertIn('call 000', out['safety_tip'])
                self.assertEqual([a[4] for a in alerts()], ['technical_job'])

    def test_existing_job_is_raised_to_urgent_once_then_to_emergency_and_never_lowered(self):
        first = job(customer_id=self.cid)                                    # việc thường (máy lạnh chảy nước)
        self.assertEqual(first['urgency'], 'normal')
        self.fresh()
        out = job(customer_id=self.cid, args={'problem': 'smelled gas last night'})
        self.assertEqual((out['job_id'], out['escalated'], out['urgency']), (first['job_id'], True, 'urgent'))
        self.assertIn('URGENT (possible hazard', out['note'])
        self.assertEqual([a[4] for a in alerts()], ['technical_hazard_check'])
        t = DB.tasks.find_one({'id': first['job_id']})
        self.assertEqual(t['urgency'], 'urgent')
        self.assertIn('URGENT, the customer mentioned a possible hazard', t['noi_dung'])
        self.fresh()
        again = job(customer_id=self.cid, args={'problem': 'Is there a gas smell?'})   # nhắc lại: không báo chủ lần 2
        self.assertFalse(again['escalated'])
        self.assertEqual(alerts(), [])
        self.assertTrue(DB.bot_customers.find_one({'id': self.cid})['needs_human'])
        self.fresh()
        worse = job(customer_id=self.cid, args={'problem': 'Smelled gas last night and it still smells'})
        self.assertEqual((worse['escalated'], worse['urgency']), (True, 'emergency'))
        self.assertEqual([a[4] for a in alerts()], ['technical_emergency'])
        self.assertEqual(DB.tasks.find_one({'id': first['job_id']})['urgency'], 'emergency')
        self.fresh()
        later = job(customer_id=self.cid, args={'problem': 'Can you check for a gas leak?'})
        self.assertFalse(later['escalated'])
        self.assertEqual(later['urgency'], 'emergency')                     # nói đúng mức đang có trên bảng
        self.assertIn('now marked EMERGENCY', later['note'])
        self.assertEqual(alerts(), [])
        self.assertEqual(DB.tasks.find_one({'id': first['job_id']})['urgency'], 'emergency')   # không bao giờ hạ

    def test_classifier_never_lowers_the_ai_choice(self):
        out = self.run_job('Is there a gas smell?', 0, urgency='emergency')
        self.assertEqual(out['urgency'], 'emergency')
        self.assertIn('somewhere safe', out['tell_customer'])
        out = self.run_job('Nothing is sparking or smoking', 1, urgency='urgent')
        self.assertEqual(out['urgency'], 'urgent')
        self.assertNotIn('possible_hazard', out)

    def test_prompt_and_tool_text_follow_the_contract(self):
        desc = technical.TOOLS[0]['function']['description']
        self.assertIn('itself smoking or sparking counts', desc)
        self.assertIn('alarm going off', desc)
        self.assertIn("'now', 'still', 'again', 'worse'", desc)
        self.assertIn("hot weather ('burning hot', 'scorching')", desc)
        en, vi = technical.PROMPT_RULES['en'], technical.PROMPT_RULES['vi']
        self.assertIn('range hood or exhaust fan that is itself smoking', en)
        self.assertIn("treat it as not ruled out", en)
        self.assertIn('TỰ bốc khói', vi)
        self.assertIn('nặng hơn', vi)
        self.assertIn('CHƯA loại trừ', vi)


if __name__ == '__main__':
    unittest.main(verbosity=2)
