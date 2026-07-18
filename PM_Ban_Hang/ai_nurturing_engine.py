# -*- coding: utf-8 -*-
import random
import datetime

class AINurturingEngine:
    @staticmethod
    def predict_churn_risk(last_purchase_days, total_spending, source_platform):
        """
        Simulates an intelligent risk assessment matrix for churn prediction
        Returns: (nurturing_status, potential_score, ai_notes)
        """
        potential_score = 100
        
        # Adjust base score based on spending
        if total_spending > 10000000:
            potential_score = 95
        elif total_spending > 5000000:
            potential_score = 80
        elif total_spending > 1000000:
            potential_score = 65
        else:
            potential_score = 50

        # Penalize for days since last purchase
        if last_purchase_days > 90:
            nurturing_status = "CHURN_RISK"
            potential_score = max(5, potential_score - 45)
            ai_notes = "Khách hàng có nguy cơ rời bỏ cực cao. Đã hơn 3 tháng không phát sinh giao dịch. Cần tung kịch bản kéo khách khẩn cấp kèm quà tặng lớn."
        elif last_purchase_days > 45:
            nurturing_status = "HIBERNATING"
            potential_score = max(20, potential_score - 25)
            ai_notes = "Khách hàng đang ngủ đông. Đã lâu chưa thấy quay lại. Đề xuất gửi kịch bản upsell hoặc voucher chăm sóc định kỳ."
        elif last_purchase_days > 21:
            nurturing_status = "NEEDS_CARE"
            potential_score = max(40, potential_score - 10)
            ai_notes = "Khách hàng sắp chạm chu kỳ mua lại trung bình. Thích hợp gửi tin nhắn thăm hỏi, tặng ưu đãi nhẹ nhàng."
        else:
            nurturing_status = "REGULAR"
            ai_notes = "Khách hàng thân thiết, hoạt động tích cực. Giữ tần suất tương tác ổn định, gợi ý combo quà tặng sinh nhật hoặc tích điểm thành viên."

        # Source platform modifiers
        if source_platform in ['facebook', 'zalo_oa']:
            ai_notes += " Thường tương tác online qua tin nhắn mạng xã hội."
        elif source_platform == 'pos':
            ai_notes += " Thói quen mua trực tiếp tại quầy thanh toán."

        return nurturing_status, potential_score, ai_notes

    @staticmethod
    def generate_nurturing_copy(industry, goal, tone, customer_name, custom_detail=None):
        """
        Generates industry-specific marketing copy for 3, 7, and 14 days campaign steps.
        Tones: 'friendly', 'premium', 'close', 'urgent', 'professional'
        """
        name = customer_name or "Sếp"
        detail = custom_detail or "BitPaw OS"
        
        # Tone definitions in Vietnamese
        salutations = {
            'friendly': f"Chào {name} thương mến! Cún nhà BitPaw ghé thăm {name} đây ạ. 🐾",
            'premium': f"Kính chào Qúy khách {name}. BitPaw OS xin gửi lời chúc trân quý nhất tới Anh/Chị.",
            'close': f"Chào {name} ơi! BitPaw có chút quà nhỏ gửi tới {name} nè. 🎁",
            'urgent': f"🚨 SẾP {name} ƠI! ƯU ĐÃI ĐỘC QUYỀN SẮP HẾT HẠN TRONG HÔM NAY!",
            'professional': f"Kính gửi {name}, BitPaw OS xin phép gửi thông tin cập nhật lộ trình chuyển đổi số của cơ sở."
        }
        
        # Fallback prompts if combinations are not specific
        templates = {
            "nail": {
                "RECALL": {
                    "3days": "Đã 3 ngày kể từ buổi sơn gel của {name}, sơn có bền màu như ý không ạ? Nếu cần dặm lại miễn phí, nhắn em liền nhé! 💅",
                    "7days": "Một tuần rồi {name} chưa ghé tiệm nails nhà em. Bên em vừa về bộ sưu tập màu sơn pastel Hàn Quốc cực kỳ trendy, em giữ chỗ ưu đãi riêng cho {name} nhé!",
                    "14days": "Voucher giảm 30% dọn da & đắp gel cao cấp chỉ dành riêng cho {name}. Đặt lịch hẹn Zalo hôm nay để giữ tua thợ VIP nhất Sếp ơi!"
                },
                "UPSELL": {
                    "3days": "Chăm sóc móng xinh đừng quên dưỡng da tay mềm mịn {name} ơi! Combo đắp paraffin dưỡng ẩm sâu đang ưu đãi chỉ 99k khi đi kèm lịch làm móng.",
                    "7days": "Mua thẻ liệu trình móng gel 5 buổi tặng ngay 1 buổi dọn da miễn phí. Tiết kiệm 20% chi phí làm đẹp cho {name}!",
                    "14days": "Khóa học đắp bột, vẽ móng nghệ thuật từ master tiệm. Ưu đãi chiết khấu học phí 15% cho thành viên VIP."
                }
            },
            "spa": {
                "RECALL": {
                    "3days": "Chào {name}! Sau buổi trị liệu da mặt 3 ngày trước, làn da có căng bóng mịn màng không ạ? Nhớ thoa kem chống nắng kỹ Sếp nhé! 🌸",
                    "7days": "Đã 1 tuần rồi, liệu trình trẻ hóa da cần thực hiện buổi tiếp theo để đạt hiệu quả tối ưu nhất. Em đặt chỗ giường VIP trước cho {name} nhé?",
                    "14days": "Da cần nạp vitamin định kỳ 2 tuần/lần {name} ơi. Tặng riêng {name} mã giảm 40% liệu trình Chăm Sóc Da Căng Bóng ngày cuối tuần!"
                },
                "UPSELL": {
                    "3days": "Liệu trình triệt lông VIP bảo hành trọn đời đang có deal mua 1 tặng 1 cực hời. {name} rủ bạn thân đi cùng để chia đôi chi phí nha!",
                    "7days": "Nâng cấp gói tắm trắng thảo dược lên tắm trắng phi thuyền hoàng gia với giá trải nghiệm ưu đãi chỉ thêm 199k.",
                    "14days": "Thẻ VIP Spa trả trước nhận ngay 150% giá trị tài khoản. Cơ hội vàng chăm sóc nhan sắc trọn đời siêu tiết kiệm."
                }
            },
            "fnb": {
                "RECALL": {
                    "3days": "Order ly cafe muối 3 ngày trước chắc vẫn còn đọng hương vị {name} nhỉ? Hôm nay có món bánh ngọt sừng bò mới ra lò thơm ngậy gõ cửa {name} đây ạ! ☕",
                    "7days": "Nhớ hương vị lẩu thái chua cay nhà em chưa {name} ơi? Tặng voucher free ly nước ép hoa quả mát rượi khi đặt bàn cuối tuần này nhé!",
                    "14days": "Đã nửa tháng chưa thấy {name} đặt món. Menu nhà em vừa cập nhật thêm 3 món ăn chuẩn vị miền Tây. Tặng code FREESHIP ly trà sữa Sếp nha!"
                },
                "UPSELL": {
                    "3days": "Gọi ngay Combo Gia Đình 4 người tiết kiệm đến 85k so với gọi món lẻ. Tặng kèm đĩa khoai tây chiên giòn rụm!",
                    "7days": "Nâng cấp cỡ ly trà sữa từ M lên L chỉ với 5k. Uống thỏa thích tràn đầy năng lượng ngày làm việc.",
                    "14days": "Đặt tiệc sinh nhật trọn gói tặng ngay gói trang trí bong bóng neon 2D trị giá 1.500.000đ và bánh kem sinh nhật thiết kế."
                }
            },
            "karaoke": {
                "RECALL": {
                    "3days": "Cảm ơn {name} đã quẩy hết mình cùng hội bạn tại phòng VIP Karaoke 3 ngày trước. Giọng hát cực đỉnh của {name} làm tiệm xao xuyến mãi! 🎤",
                    "7days": "Cuối tuần bận rộn xả stress thôi {name} ơi! Đặt trước bàn bida bận/trống hôm nay tặng ngay 1 đĩa trái cây tươi ngọt mát lạnh.",
                    "14days": "Thèm hát hò bida giải trí chưa {name} ơi? Giờ thấp điểm (10h - 14h) bên em giảm 50% tiền giờ chơi, đặt phòng ngay Sếp ơi!"
                },
                "UPSELL": {
                    "3days": "Gọi ngay Combo Bia & Mồi nhắm VIP tặng thêm 1 tiếng hát miễn phí. Phòng đẹp âm thanh chuẩn sẵn sàng phục vụ.",
                    "7days": "Gói trang trí sự kiện sinh nhật/họp lớp tại phòng Karaoke VIP giảm giá 30%. Sân khấu rực rỡ sắc màu.",
                    "14days": "Thành viên kim cương tích điểm tặng micro gold cao cấp riêng biệt. Ưu đãi chiết khấu 10% bill vĩnh viễn."
                }
            },
            "hotel": {
                "RECALL": {
                    "3days": "Kỳ nghỉ tại Homestay của {name} có thoải mái như ý không ạ? Rất mong được đón nhận đánh giá góp ý của {name} để dịch vụ ngày một tốt hơn! 🏨",
                    "7days": "Một tuần trôi qua nhanh quá, công việc chắc hẳn bận rộn. Nếu cần một nơi yên tĩnh thư giãn cuối tuần, căn phòng hướng biển vẫn chờ đón {name} nhé.",
                    "14days": "Ưu đãi đặt phòng sớm mùa du lịch hè! Tặng {name} voucher giảm 20% tiền phòng ngủ khi booking trực tiếp qua Zalo hôm nay."
                },
                "UPSELL": {
                    "3days": "Đăng ký dịch vụ xe đưa đón sân bay khứ hồi tiện lợi chỉ với 250k. An toàn, đúng giờ, không lo trễ chuyến.",
                    "7days": "Nâng cấp từ phòng Standard lên phòng Deluxe view hoàng hôn trọn vẹn với giá ưu đãi chỉ thêm 150k/đêm.",
                    "14days": "Gói combo phòng ngủ kèm vé Buffet sáng chuẩn 4 sao và 1 suất massage chân thư giãn trị liệu."
                }
            },
            "retail": {
                "RECALL": {
                    "3days": "Chiếc váy xinh {name} mua 3 ngày trước mặc có vừa vặn tôn dáng không ạ? Đăng ảnh feedback em gửi tặng ngay voucher 50k cho đơn sau nhé! 👗",
                    "7days": "Bộ sưu tập thời trang mùa thu vừa cập xưởng nhà em sáng nay. Rất nhiều mẫu đầm thiết kế độc quyền nâng tầm phong cách cho {name}!",
                    "14days": "Lâu quá chưa ghé shop mua sắm {name} ơi! Bên em đang có chương trình Flash Sale tri ân khách cũ giảm giá đến 50%. Inbox em giữ size xinh nhé!"
                },
                "UPSELL": {
                    "3days": "Mua thêm chiếc thắt lưng da cao cấp đi kèm váy xinh giảm ngay 40% giá phụ kiện. Đồng bộ phong cách quý phái.",
                    "7days": "Hóa đơn mua sắm từ 1.000.000đ tặng ngay 1 thỏi son môi trendy hoặc túi xách thời trang sành điệu.",
                    "14days": "Gia nhập câu lạc bộ thành viên Bạc tích điểm 2% mọi đơn hàng, quà tặng tri ân bất ngờ ngày lễ Tết."
                }
            },
            "office": {
                "RECALL": {
                    "3days": "Chào {name}, BitPaw gửi tài liệu hướng dẫn tối ưu bảng chấm công tự động. Sếp đã xem qua chưa ạ? Cần hỗ trợ setup gọi em nhé! 💼",
                    "7days": "Một tuần làm việc hiệu suất cao! Gửi Sếp case study doanh nghiệp 50 nhân sự đã số hóa đơn từ phê duyệt 1-touch tiết kiệm 40% chi phí quản lý.",
                    "14days": "Lịch hẹn demo hệ thống OKR/KPI văn phòng thông minh cùng chuyên gia BitPaw chỉ dành riêng cho {name}. Đặt hẹn Zalo ngay Sếp ơi!"
                },
                "UPSELL": {
                    "3days": "Nâng cấp lên gói Office Premium mở rộng không giới hạn dung lượng Drive lưu trữ tài liệu mật.",
                    "7days": "Tích hợp thêm phân hệ HRM tính lương đa biến số tự động chỉ với chi phí ưu đãi thêm 200k/tháng.",
                    "14days": "Mua trọn gói 5 phân hệ văn phòng số hóa tặng ngay gói đào tạo trực tiếp cho toàn thể nhân sự trị giá 10 triệu."
                }
            },
            "technical": {
                "RECALL": {
                    "3days": "Chào {name}! Đội thợ hiện trường vừa hoàn tất lắp đặt thiết bị 3 ngày trước. Máy vận hành êm ái chứ Sếp? Có vấn đề gì báo em ngay! 🛠️",
                    "7days": "Để thiết bị hoạt động bền bỉ, gửi Sếp cẩm nang tự bảo trì máy móc cơ bản tại nhà xưởng vô cùng hữu ích.",
                    "14days": "Đến lịch bảo dưỡng định kỳ rồi Sếp ơi! Tặng ngay {name} suất kiểm tra miễn phí độ an toàn dòng điện và đường dây khi đặt lịch tuần này."
                },
                "UPSELL": {
                    "3days": "Đăng ký gói bảo trì trọn năm tiết kiệm 35% chi phí so với gọi sửa chữa đơn lẻ. Thiết bị luôn sẵn sàng.",
                    "7days": "Nâng cấp phụ tùng linh kiện chính hãng thời gian bảo hành lên đến 24 tháng (gấp đôi tiêu chuẩn).",
                    "14days": "Combo lắp đặt trọn gói hệ thống camera an ninh AI Vision tự động cảnh báo xâm nhập hiện trường."
                }
            },
            "production": {
                "RECALL": {
                    "3days": "Chào Sếp {name}! Lô hàng phân xưởng sản xuất theo lệnh BOM 3 ngày trước đã xuất xưởng thuận lợi. Năng suất đạt chỉ tiêu rất cao! 🏭",
                    "7days": "Gửi Sếp báo cáo tổng hợp tỷ lệ hao hụt phôi vải tuần qua. AI chẩn đoán tiết kiệm được thêm 15% nguyên liệu.",
                    "14days": "Đăng ký buổi tư vấn trực tiếp 1-1 cùng kỹ sư trưởng BitPaw tối ưu hóa dây chuyền xoay ca sản xuất."
                },
                "UPSELL": {
                    "3days": "Tích hợp thêm module quản lý tồn kho nguyên vật liệu gán mã vạch Barcode giảm 90% lệch kho.",
                    "7days": "Gói đào tạo tiêu chuẩn chất lượng QC cho tổ trưởng xưởng may mặc tăng năng suất và giảm sản phẩm lỗi.",
                    "14days": "Mua trọn bộ hạ tầng MES sản xuất nhà xưởng nhận ưu đãi trả góp lãi suất 0% trong 12 tháng."
                }
            },
            "hr": {
                "RECALL": {
                    "3days": "Chào {name}! BitPaw gửi mẫu bảng lương đa biến số tự động hóa tính bảo hiểm. Sếp áp dụng thử cho đơn vị thấy mượt không ạ? 👥",
                    "7days": "Onboarding nhân viên mới là ác mộng? Gửi Sếp quy trình số hóa hồ sơ nhân sự 360 lưu hợp đồng điện tử 1-touch.",
                    "14days": "Đăng ký dùng thử phân hệ ATS tự động lọc CV bằng AI giúp tiết kiệm 80% thời gian tuyển dụng của phòng nhân sự!"
                },
                "UPSELL": {
                    "3days": "Mua thêm phân hệ đánh giá năng lực KPI/OKR nhân viên tăng tính minh bạch trong xét duyệt lương thưởng.",
                    "7days": "Gói tích hợp cổng kết nối AD/LDAP, Microsoft 365, Google Workspace cho doanh nghiệp lớn.",
                    "14days": "Thành viên VIP mua trọn gói HRM trọn đời nhận ngay ưu đãi cập nhật tính năng mới miễn phí trọn đời."
                }
            }
        }

        # Select template
        ind_data = templates.get(industry.lower(), templates["retail"])
        goal_data = ind_data.get(goal.upper(), ind_data["RECALL"])
        
        salutation = salutations.get(tone.lower(), salutations["friendly"])
        
        # Build 3 days, 7 days, 14 days message content
        msg_3d = f"{salutation}\n\n{goal_data.get('3days', '')}"
        msg_7d = f"{salutation}\n\n{goal_data.get('7days', '')}"
        msg_14d = f"{salutation}\n\n{goal_data.get('14days', '')}"
        
        # Replace formatting
        msg_3d = msg_3d.replace("{name}", name).replace("{detail}", detail)
        msg_7d = msg_7d.replace("{name}", name).replace("{detail}", detail)
        msg_14d = msg_14d.replace("{name}", name).replace("{detail}", detail)
        
        # Vouchers đề xuất
        vouchers = {
            "RECALL": "GIAM30 - Giảm 30% hóa đơn",
            "UPSELL": "COMBO99 - Độc quyền trọn gói 99k",
            "REVIEW": "FREEGIFT - Tặng quà lưu niệm miễn phí",
            "BIRTHDAY": "HPBD100 - Tặng 100k ngày sinh nhật",
            "PROMO": "GIOVANG - Giảm 50% khung giờ vàng"
        }
        
        return {
            "3days": msg_3d,
            "7days": msg_7d,
            "14days": msg_14d,
            "voucher": vouchers.get(goal.upper(), "BITPAWVIP - Giảm 10%"),
            "segment_size": random.randint(15, 148)
        }

    @staticmethod
    def get_industry_recommendations(industry):
        """
        Generates smart AI insights customized per industry
        """
        recs = {
            "nail": [
                {"type": "CHURN_ALERT", "text": "Có 12 khách hàng VIP của tiệm Nails chưa quay lại làm móng trong 30 ngày qua. Đề xuất chạy chiến dịch 'Sơn Gel Thu Sáng Tình Cảm' tặng voucher 25%."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Dự báo tuần này có 25 lịch hẹn làm móng trống ca sáng. Đề xuất gửi kịch bản 'Giờ vàng dưỡng móng' ưu đãi dọn da miễn phí khung giờ 9h-11h."},
                {"type": "REVENUE_OPTIMIZE", "text": "Khách hàng mua dịch vụ 'Đắp bột' thường có tỷ lệ quay lại thấp. Gợi ý gửi tin nhắn chăm sóc sau 3 ngày hướng dẫn cách bảo quản móng lâu hỏng."}
            ],
            "spa": [
                {"type": "CHURN_ALERT", "text": "Có 8 khách hàng đang dở dang liệu trình trị mụn 5 buổi chưa quay lại Spa quá 14 ngày. Đề xuất AI tự động gửi tin nhắn nhắc lịch."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Nhiệt độ ngoài trời tăng cao tuần này. Khách hàng quan tâm cao dịch vụ thải độc phục hồi da. Đề xuất chạy chiến dịch 'Thải độc detox mát rượi'."},
                {"type": "REVENUE_OPTIMIZE", "text": "Tỷ lệ mua thêm serum dưỡng sau liệu trình đạt thấp (12%). Đề xuất tích hợp combo tặng mẫu thử serum mini khi đặt liệu trình VIP."}
            ],
            "fnb": [
                {"type": "CHURN_ALERT", "text": "Có 45 khách hàng cũ hay đặt Cafe Muối/Trà Sữa chưa gọi món lại quá 10 ngày. Đề xuất gửi tin nhắn tặng code Freeship ly trà chiều."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Thứ 7 tuần này có giải đấu bóng đá lớn. Đề xuất chạy chiến dịch 'Đồng hành túc cầu' tặng đĩa mồi nhắm khoai tây chiên khi đặt Combo bia."},
                {"type": "REVENUE_OPTIMIZE", "text": "Khách đi nhóm 3-4 người thường gọi nước uống lẻ. Gợi ý cấu hình popup Menu QR giới thiệu thẳng Combo Gia Đình tiết kiệm 15%."}
            ]
        }
        
        return recs.get(industry.lower(), [
            {"type": "CHURN_ALERT", "text": "Có 18 khách hàng tiềm năng đã lâu chưa phát sinh tương tác. Đề xuất gửi tin nhắn thăm hỏi kèm mã ưu đãi tri ân thành viên."},
            {"type": "CAMPAIGN_SUGGESTION", "text": "Cuối tháng là thời điểm nhu cầu mua sắm và chi tiêu tăng cao. Đề xuất chạy chiến dịch 'Flash Sale tri ân khách cũ' kéo tương tác."},
            {"type": "REVENUE_OPTIMIZE", "text": "AI phát hiện 24% đơn hàng có thể upsell bằng cách đính kèm phụ kiện liên quan. Đề xuất tối ưu hóa gợi ý sản phẩm tự động."}
        ])

    @staticmethod
    def get_sample_customers(industry):
        """
        Generates customized realistic industry customer dummy list for seeding/data center UIs
        """
        names = ["Nguyễn Thị Mai", "Trần Hoàng Nam", "Lê Thanh Hương", "Phạm Minh Đức", "Vũ Phương Thảo", "Đỗ Quốc Bảo", "Nguyễn Huy Hoàng", "Lâm Mỹ Tâm", "Phan Anh Tuấn", "Bùi Hồng Ngọc"]
        phones = ["0987654321", "0912345678", "0909876543", "0976543210", "0934567890", "0945678901", "0967890123", "0923456789", "0956789012", "0911223344"]
        emails = ["mai.nguyen@gmail.com", "nam.tran@gmail.com", "huong.le@gmail.com", "duc.pham@gmail.com", "thao.vu@gmail.com", "bao.do@gmail.com", "hoang.huy@gmail.com", "tam.lam@gmail.com", "tuan.phan@gmail.com", "ngoc.bui@gmail.com"]
        platforms = ["pos", "booking", "messenger", "zalo_oa", "whatsapp", "webform"]
        
        services = {
            "nail": ["Sơn móng gel", "Đắp móng bột", "Chà gót tẩy tế bào chết", "Vẽ móng nghệ thuật", "Dưỡng Paraffin tay"],
            "spa": ["Liệu trình trị mụn", "Chăm sóc da căng bóng", "Trẻ hóa da phi thuyền", "Triệt lông VIP", "Massage body thảo dược"],
            "fnb": ["Lẩu thái hải sản", "Cafe muối", "Trà sữa Matcha L", "Combo Gia Đình A", "Bánh sừng bò Pháp"],
            "karaoke": ["Giờ hát phòng VIP", "Bàn bida VIP máy lạnh", "Combo bia Heineken", "Đĩa trái cây tươi", "Khăn lạnh dịch vụ"],
            "hotel": ["Phòng Deluxe view biển", "Homestay Bungalow", "Buffet sáng 4 sao", "Dịch vụ thuê xe máy", "Tour lặn ngắm san hô"],
            "retail": ["Đầm voan hoa nhí", "Váy thiết kế dự tiệc", "Thắt lưng da cao cấp", "Túi xách thu đông", "Son môi trendy"],
            "office": ["Hạ tầng văn phòng số", "Phê duyệt online 1-touch", "BitPaw Drive 100GB", "Hệ thống OKR/KPI", "Module chấm công"],
            "technical": ["Lắp đặt điều hòa xưởng", "Bảo dưỡng máy hàn", "Kiểm tra hệ thống điện", "Phụ tùng thay thế", "Nghiệm thu sự cố"],
            "production": ["Lệnh sản xuất BOM", "Quét mã vạch ca kíp", "Năng suất chuyền may", "Định mức phôi sắt", "Duyệt chất lượng QC"],
            "hr": ["Bảng lương đa biến số", "Tuyển dụng ATS tự động", "Hồ sơ nhân viên 360", "Onboarding tự động", "Báo cáo công ca kíp"]
        }
        
        chosen_services = services.get(industry.lower(), services["retail"])
        
        sample_customers = []
        for i in range(10):
            days_ago = random.choice([5, 12, 25, 48, 95])
            spending = random.choice([250000, 680000, 1200000, 3500000, 8900000, 14500000])
            platform = random.choice(platforms)
            
            # Predict status
            status, score, notes = AINurturingEngine.predict_churn_risk(days_ago, spending, platform)
            
            last_date = (datetime.datetime.now() - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M")
            
            sample_customers.append({
                "id": f"cust-id-00{i+1}",
                "name": names[i],
                "phone": phones[i],
                "email": emails[i],
                "source": platform,
                "industry": industry,
                "last_purchase": last_date,
                "total_spend": spending,
                "service_interest": random.choice(chosen_services),
                "tags": "VIP" if spending > 5000000 else "Khách Quen" if spending > 1000000 else "Mới",
                "status": status,
                "potential_score": score,
                "ai_notes": notes
            })
            
        return sample_customers
