keywords = ["assistant", "ad_assistant", "ad-assistant", "ai_bot", "ai-studio", "ai_studio", "campaign_builder", "customer_nurturing", "crm_automation"]
content = open('app.py', 'r', encoding='utf-8').read().splitlines()

for i, line in enumerate(content):
    for kw in keywords:
        if kw in line:
            print(f"Line {i+1}: {line.strip()}")
            break
