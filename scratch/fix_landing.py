import re

def fix_landing():
    file_path = "templates/landing.html"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Restore broken changeLanguage and togglePricing functions
    bad_part = """            elements.forEach(el => {
                const key = el.getAttribute('data-i18n');            VanillaTilt.init(document.querySelectorAll("[data-tilt]"), { max: 10, speed: 400, glare: true, "max-glare": 0.3 });
        }ment.getElementById('current-lang-text').innerText === 'EN';"""
    
    good_part = """            elements.forEach(el => {
                const key = el.getAttribute('data-i18n');
                if (translations[lang] && translations[lang][key]) {
                    el.innerHTML = translations[lang][key];
                }
            });

            const inputs = document.querySelectorAll('[data-i18n-placeholder]');
            inputs.forEach(el => {
                const key = el.getAttribute('data-i18n-placeholder');
                if (translations[lang] && translations[lang][key]) {
                    el.setAttribute('placeholder', translations[lang][key]);
                }
            });

            const titles = document.querySelectorAll('[data-i18n-title]');
            titles.forEach(el => {
                const key = el.getAttribute('data-i18n-title');
                if (translations[lang] && translations[lang][key]) {
                    el.setAttribute('title', translations[lang][key]);
                }
            });
        }
    </script>

    <script>
        function togglePricing() {
            const toggle = document.getElementById('pricing-toggle');
            const priceVals1 = document.querySelectorAll('.price-val-1');
            const priceVals2 = document.querySelectorAll('.price-val-2');
            const priceVals3 = document.querySelectorAll('.price-val-3');
            const pricePeriods = document.querySelectorAll('.price-period');
            const labelMonthly = document.getElementById('label-monthly');
            const labelYearly = document.getElementById('label-yearly');

            const pricesMonth = ["1.500.000", "1.200.000", "1.800.000"];
            const pricesYear = ["1.200.000", "990.000", "1.500.000"];
            const isEng = document.getElementById('current-lang-text') && document.getElementById('current-lang-text').innerText === 'EN';"""

    if bad_part in content:
        content = content.replace(bad_part, good_part)
        print("[+] Restored changeLanguage and togglePricing successfully!")
    else:
        print("[-] Bad part 1 not found (it might be already fixed).")

    # 2. Revert dynamic rotating typing script cleanly
    typing_pattern = r"""\s+// Typing & Rotating Words Effect for Hero\s+\(function\(\)\s*\{\s+const rotatingWords = \["POS thông minh", "QR Order", "HRM & Payroll", "CRM & AI CSKH"\];[\s\S]+?\}\)\(\);"""
    
    if re.search(typing_pattern, content):
        content = re.sub(typing_pattern, "", content)
        print("[+] Removed Typing & Rotating script successfully!")
    else:
        print("[-] Typing & Rotating script not found in file.")

    # 3. Restore Hero static text layout
    old_hero = 'id="hero-rotating-text" class="text-gradient">POS • HRM • CRM • AI CSKH'
    new_hero = 'class="text-gradient">POS • HRM • CRM • AI CSKH'
    if old_hero in content:
        content = content.replace(old_hero, new_hero)
        print("[+] Restored static Hero text successfully!")
    
    old_hero_alt = 'id="hero-rotating-text" class="text-gradient"'
    new_hero_alt = 'class="text-gradient"'
    if old_hero_alt in content:
        content = content.replace(old_hero_alt, new_hero_alt)
        print("[+] Restored static Hero text alt successfully!")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[*] Completed writing landing.html successfully!")

if __name__ == "__main__":
    fix_landing()
