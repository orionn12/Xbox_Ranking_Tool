import asyncio
from playwright.async_api import async_playwright

async def debug_run(url):
    print(f"Starting debug for: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="ja-JP")
        page = await context.new_page()
        
        await page.goto(url, wait_until="domcontentloaded")
        await page.evaluate("window.scrollTo(0, 1500)")
        await asyncio.sleep(2.0)
        
        review_tab = page.locator('button:has-text("レビュー"), [id*="review-tab"], [aria-label*="レビュー"], button:has-text("Reviews")').first
        if await review_tab.count() > 0:
            await review_tab.click()
            print("CLICKED REVIEW TAB")
            await asyncio.sleep(4.0)
        
        all_aria = await page.evaluate("""
            () => {
                let results = [];
                document.querySelectorAll('[aria-label]').forEach(e => {
                    let txt = e.getAttribute('aria-label');
                    if (txt.includes('星') || txt.includes('%') || txt.includes('star')) {
                        results.push(txt);
                    }
                });
                return results;
            }
        """)
        
        all_text = await page.evaluate("""
            () => {
                let results = [];
                document.querySelectorAll('*').forEach(e => {
                    if (e.innerText && (e.innerText.includes('★') || e.innerText.includes('%'))) {
                        results.push(e.innerText.substring(0, 30).replace(/\\n/g, ' '));
                    }
                });
                return results;
            }
        """)
        
        print("--- ARIA LABELS ---")
        for a in set(all_aria):
            print(a)
            
        print("--- VISIBLE TEXT ---")
        for t in set(all_text):
            print(t)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_run("https://www.xbox.com/ja-JP/games/store/minecraft/9MVXMVT8ZKWC/0010"))
