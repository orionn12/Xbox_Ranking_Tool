import asyncio
from playwright.async_api import async_playwright

async def debug_lang_tr():
    url = "https://www.xbox.com/ja-JP/games/store/a/BT5P2X999VH2"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP"
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")

        # Age gate removal
        await page.evaluate("""
            () => {
                document.querySelectorAll('reach-portal').forEach(e => e.remove());
                document.querySelectorAll('[data-reach-dialog-overlay],[class*="modalOverlay"],[class*="AgeGating"]').forEach(e => e.remove());
            }
        """)

        # Click Others tab
        await page.evaluate("""
            () => {
                for (const b of document.querySelectorAll('button')) {
                    if (b.textContent.trim() === 'その他' && b.offsetParent !== null) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        await asyncio.sleep(5)

        table = page.locator('table[class*="LanguageSupport"]').first
        if await table.count() > 0:
            rows = await table.locator('tr').all()
            for row in rows:
                inner_text = await row.inner_text()
                if "日本語" in inner_text:
                    print(f"--- Japanese row full inner HTML ---")
                    print(await row.inner_html())
                    cells = await row.locator('td, th').all()
                    for i, cell in enumerate(cells):
                        print(f"Cell {i} ({await cell.inner_text()}):")
                        print(await cell.inner_html())
                    break
        else:
            print("Language support table not found.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_lang_tr())
