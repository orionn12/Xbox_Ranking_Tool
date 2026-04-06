import asyncio
from playwright.async_api import async_playwright

async def debug_flow(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        try:
            print(f"Navigating to {url}...")
            await page.goto(url, wait_until="commit")
            await asyncio.sleep(5)
            await page.screenshot(path="debug_1_initial.png")
            
            # Age gate check
            btns = page.locator('text="生年月日の入力"')
            count = await btns.count()
            print(f"Found {count} age gate buttons.")
            
            if count > 0:
                await btns.first.click()
                await asyncio.sleep(3)
                await page.screenshot(path="debug_2_modal.png")
                
                # Fill logic
                target = page
                for f in page.frames:
                    if await f.locator('select').count() >= 3:
                        target = f; break
                print(f"Using frame: {target.name or '(main)'}")
                
                selects = await target.locator('select').all()
                if len(selects) >= 3:
                    await selects[0].select_option(label="2000")
                    await selects[1].select_option(index=1)
                    await selects[2].select_option(index=1)
                    print("Selected options.")
                
                submit = target.get_by_text("送信").first
                if await submit.count() > 0:
                    await submit.click()
                    print("Clicked submit.")
                    await asyncio.sleep(5)
                    await page.screenshot(path="debug_3_after_submit.png")
            
            await page.evaluate("window.scrollTo(0, 1500)")
            await asyncio.sleep(2)
            await page.screenshot(path="debug_4_scrolled.png")
            
            # Check description
            h2 = page.locator('h2:has-text("説明")').first
            if await h2.count() > 0:
                print("Found '説明' header.")
            
        finally:
            await browser.close()

if __name__ == '__main__':
    url = "https://www.xbox.com/ja-JP/games/store/roblox/BQ1QS1TH96BC"
    asyncio.run(debug_flow(url))
