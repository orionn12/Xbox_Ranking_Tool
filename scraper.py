import asyncio
import re
import traceback

import aiohttp
from playwright.async_api import async_playwright


class XboxScraper:
    """Xbox ストアのランキングと詳細情報を取得するスクレイパー"""

    BASE_URL = (
        "https://www.xbox.com/ja-jp/games/all-games"
        "?PlayWith=XboxSeriesXS,XboxOne&SortBy=TopPaid"
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    # =========================================================
    # ランキング一覧の取得
    # =========================================================

    async def fetch_ranking(self, limit: int = 350) -> list[dict]:
        """「売れ筋」ランキング一覧を取得する（最大 limit 件）"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                locale="ja-JP",
                ignore_https_errors=True,
            )
            page = await context.new_page()

            print(f"Fetching ranking: {self.BASE_URL}")
            try:
                await page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"Warning: page.goto error: {e}")
            await asyncio.sleep(2.0)

            card_sel = 'a[class*="basicButton"]'
            # 「もっと表示する」ボタンを繰り返しクリックして必要件数まで読み込む
            for _ in range(40):
                current_cards = await page.query_selector_all(card_sel)
                valid = [
                    c for c in current_cards
                    if await c.get_attribute("title") or await c.get_attribute("aria-label")
                ]
                print(f"  Loaded cards: {len(valid)}")
                if len(valid) >= limit:
                    break
                try:
                    btn = page.locator('button:has-text("もっと表示する")').first
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        await btn.click()
                        await asyncio.sleep(2.5)
                    else:
                        break
                except Exception:
                    break

            all_cards = await page.query_selector_all(card_sel)
            ranking_data = []

            for card in all_cards:
                if len(ranking_data) >= limit:
                    break

                title = await card.get_attribute("title")
                aria_label = await card.get_attribute("aria-label") or ""
                url = await card.get_attribute("href") or ""

                if not title and aria_label:
                    m = re.match(r"^『?(.+?)』?[、,]", aria_label)
                    title = m.group(1) if m else aria_label.split("、")[0]

                if not title and not aria_label:
                    continue

                if url and not url.startswith("http"):
                    url = "https://www.xbox.com" + url

                price_info = self._parse_aria_label(aria_label)

                # Game Pass バッジの確認
                is_gp = False
                if "Game Pass" in aria_label or "ゲーム パス" in aria_label:
                    is_gp = True
                if not is_gp:
                    badge = await card.query_selector(
                        '[class*="Badge-module__badge"], [class*="gamePass"]'
                    )
                    if badge:
                        is_gp = True
                if not is_gp:
                    try:
                        inner = await card.inner_text()
                        if "GAME PASS" in inner.upper():
                            is_gp = True
                    except Exception:
                        pass

                ranking_data.append({
                    "rank": len(ranking_data) + 1,
                    "title": title or "タイトル不明",
                    "price": price_info["current_price"],
                    "original_price": price_info["original_price"],
                    "is_sale": price_info["is_sale"],
                    "is_game_pass": is_gp,
                    "url": url,
                })

            await browser.close()
            print(f"Fetched {len(ranking_data)} items.")
            return ranking_data

    # =========================================================
    # 価格テキストのパース
    # =========================================================

    def _parse_aria_label(self, label: str) -> dict:
        """aria-label から価格情報を解析する"""
        res = {"current_price": "不明", "original_price": None, "is_sale": False}
        if not label:
            return res

        if "ゲームを表示" in label or "価格を表示" in label or "詳細を表示" in label:
            res["current_price"] = "詳細を確認"
            return res

        m_orig = re.search(r"元の価格\s*(¥[\d,]+|無料)", label)
        m_sale = re.search(r"セール価格\s*(¥[\d,]+|無料)", label)
        if m_orig and m_sale:
            res["original_price"] = m_orig.group(1)
            res["current_price"] = m_sale.group(1)
            res["is_sale"] = True
            return res

        m_norm = re.search(r"価格\s*(¥[\d,]+|無料)", label)
        if m_norm:
            res["current_price"] = m_norm.group(1)
            return res

        m_direct = re.search(r"(¥[\d,]+|無料)", label)
        if m_direct:
            res["current_price"] = m_direct.group(1)
        return res

    # =========================================================
    # Microsoft Display Catalog API
    # =========================================================

    async def fetch_media_from_api(self, product_id: str):
        """
        Display Catalog API からメディア・評価・詳細情報を取得する。

        Returns: (imgs, vids, ratings, product_id, api_extra)
        """
        api_url = (
            f"https://displaycatalog.mp.microsoft.com/v7.0/products"
            f"?bigIds={product_id}&market=JP&languages=ja-JP"
        )
        _empty = ([], [], {"avg": "0.0", "count": "0"}, None, None)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    if response.status != 200:
                        return _empty
                    data = await response.json()
                    if not data.get("Products"):
                        return _empty

                    product = data["Products"][0]
                    prop = product.get("LocalizedProperties", [{}])[0]

                    # ---- 画像 ----
                    imgs = []
                    for purpose in ["SuperHeroArt", "Screenshot", "Wallpaper"]:
                        for img in prop.get("Images", []):
                            if img.get("ImagePurpose") != purpose:
                                continue
                            uri = img.get("Uri")
                            if not uri:
                                continue
                            if uri.startswith("//"):
                                uri = "https:" + uri
                            base = uri.split("?")[0]
                            if not any(base in ex.split("?")[0] for ex in imgs):
                                imgs.append(uri)

                    # ---- 動画 ----
                    vids = []
                    for vid in prop.get("CMSVideos", []):
                        if vid.get("VideoPurpose") not in ["HeroTrailer", "Trailer"]:
                            continue
                        hls = vid.get("HLS", "")
                        if hls.startswith("//"):
                            hls = "https:" + hls
                        preview = (vid.get("PreviewImage") or {}).get("Uri", "")
                        if preview.startswith("//"):
                            preview = "https:" + preview
                        vids.append({"url": hls or preview, "thumbnail": preview})

                    # ---- 評価（UsageData） ----
                    ratings = {"avg": "0.0", "count": "0"}
                    for usage in (product.get("MarketProperties") or [{}])[0].get("UsageData", []):
                        if usage.get("AggregateTimeSpan") == "AllTime":
                            ratings["avg"] = f"{usage.get('AverageRating', 0.0):.1f}"
                            ratings["count"] = str(usage.get("RatingCount", 0))
                            break

                    # ---- 説明・Play Anywhere・日本語サポート ----
                    desc = prop.get("ProductDescription") or prop.get("ShortDescription")
                    attrs = [a.get("Name") for a in product.get("Properties", {}).get("Attributes", [])]
                    play_anywhere = any(k in attrs for k in ["XPA", "XboxPlayAnywhere", "Xbox Play Anywhere"])

                    # 日本語サポート（API 経由では細分化不可のため全項目 True と仮定）
                    lang_code = prop.get("Language", "").lower()
                    has_jp = any(k in lang_code for k in ["ja", "jp", "japanese", "日本語"])
                    if not has_jp:
                        for sku_av in product.get("DisplaySkuAvailabilities", []):
                            for pkg in (sku_av.get("Sku") or {}).get("Properties", {}).get("Packages", []):
                                for lang in pkg.get("Languages", []):
                                    if isinstance(lang, str) and any(
                                        k in lang.lower() for k in ["ja", "jp"]
                                    ):
                                        has_jp = True
                                        break

                    api_extra = {
                        "description": desc,
                        "play_anywhere": play_anywhere,
                        "jp_support": {"ui": True, "audio": True, "subtitles": True} if has_jp else None,
                    }

                    return imgs, vids, ratings, product.get("ProductId"), api_extra

        except Exception as e:
            print(f"fetch_media_from_api error: {e}")
        return _empty

    # =========================================================
    # Emerald API（星別レビュー内訳）
    # =========================================================

    async def fetch_ratings_from_api(self, product_id: str) -> dict | None:
        """emerald.xboxservices.com から星1〜5の内訳を含む詳細評価を取得する"""
        url = (
            f"https://emerald.xboxservices.com/xboxcomfd/ratingsandreviews"
            f"/summaryandreviews/{product_id}?locale=ja-JP&starFilter=NoFilter&itemCount=25"
        )
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*",
            "x-ms-api-version": "1.0",
            "ms-cv": "D6BfX/yPqE6N1i2z.1",
            "referer": "https://www.xbox.com/",
            "origin": "https://www.xbox.com",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        print(f"fetch_ratings_from_api ({product_id}): HTTP {response.status}")
                        return None
                    data = await response.json()
                    summary = data.get("ratingsSummary", {})
                    total = summary.get("totalRatingsCount", 0)
                    dist = {}
                    for i in range(1, 6):
                        count = summary.get(f"star{i}Count", 0)
                        pct = int(count / total * 100) if total > 0 else 0
                        dist[str(i)] = f"{pct}%"
                    return {
                        "average": f"{summary.get('averageRating', 0.0):.1f}",
                        "total_count": str(total),
                        "dist": dist,
                    }
        except Exception as e:
            print(f"fetch_ratings_from_api error ({product_id}): {e}")
        return None

    # =========================================================
    # ゲーム詳細の取得
    # =========================================================

    async def fetch_details(self, url: str) -> dict:
        """ゲーム詳細ページから説明・画像・動画・言語サポート・評価を取得する"""
        # URL 正規化
        url = url.replace("/ja-jp/", "/ja-JP/")
        sep = "&" if "?" in url else "?"
        if "activetab" not in url:
            url += f"{sep}activetab=pivot:reviewstab"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                locale="ja-JP",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"Warning: page.goto error in fetch_details: {e}")
                await asyncio.sleep(2.0)

                # 年齢確認モーダルを JS で強制削除
                async def dismiss_modal():
                    try:
                        removed = await page.evaluate("""
                            () => {
                                let n = 0;
                                document.querySelectorAll('reach-portal').forEach(e => { e.remove(); n++; });
                                document.querySelectorAll(
                                    '[data-reach-dialog-overlay],[class*="modalOverlay"],[class*="AgeGating"]'
                                ).forEach(e => { e.remove(); n++; });
                                return n;
                            }
                        """)
                        if removed > 0:
                            await asyncio.sleep(0.3)
                    except Exception:
                        pass

                # ---- 製品 ID の抽出と API 呼び出し ----
                m_id = re.search(r"/([a-zA-Z0-9]{12})($|\?|/)", url)
                product_id = m_id.group(1) if m_id else None

                imgs, vids, api_ratings, api_product_id, api_extra = [], [], {"avg": "0.0", "count": "0"}, None, None
                if product_id:
                    imgs, vids, api_ratings, api_product_id, api_extra = await self.fetch_media_from_api(product_id)
                    if not api_product_id:
                        api_product_id = product_id
                    print(f"API images: {len(imgs)}, videos: {len(vids)}")

                # ---- 説明文 ----
                desc_text = "説明なし"
                if api_extra and api_extra.get("description"):
                    desc_text = api_extra["description"]

                if desc_text == "説明なし":
                    try:
                        expand = page.locator(
                            'button:has-text("続きを表示"), button:has-text("詳細を表示"), button:has-text("さらに表示")'
                        ).first
                        if await expand.count() > 0 and await expand.is_visible():
                            await expand.click()
                            await asyncio.sleep(0.5)
                    except Exception:
                        pass

                    desc_sels = [
                        'div[class*="Description-module__descriptionContainer"]',
                        'div[class*="Description-module__description"]',
                        'div[class*="ProductDescription-module__description"]',
                        'div[class*="ExpandableText-module__container"]',
                        'div[id="product-description"]',
                    ]
                    for sel in desc_sels:
                        for el in await page.query_selector_all(sel):
                            txt = (await el.inner_text()).strip()
                            if len(txt) > 50:
                                desc_text = txt
                                break
                        if desc_text != "説明なし":
                            break

                    # フォールバック: h2「説明」の親要素
                    if desc_text == "説明なし":
                        try:
                            h2 = page.locator('h2:has-text("説明")').first
                            if await h2.count() > 0:
                                content = (await h2.locator("xpath=./..").inner_text()).replace("説明", "").strip()
                                if len(content) > 50:
                                    desc_text = content
                        except Exception:
                            pass

                # ---- ジャンル ----
                genre = "未定義"
                try:
                    for sel in [
                        'a[href*="genre"]',
                        'div[class*="publisherGenre"] a',
                        'div[class*="gameInfo"] a',
                    ]:
                        genres = []
                        for el in await page.query_selector_all(sel):
                            txt = (await el.inner_text()).strip()
                            if txt and txt not in genres:
                                genres.append(txt)
                        if genres:
                            genre = " / ".join(genres)
                            break
                except Exception:
                    pass

                # ---- 画像（API 未取得時のフォールバック） ----
                if not imgs:
                    try:
                        await asyncio.sleep(1.0)
                        blocked = page.locator('section[class*="Gallery"] button:has-text("生年月日の入力")').first
                        if await blocked.count() > 0:
                            await dismiss_modal()
                            await page.evaluate("window.scrollBy(0, 100)")
                            await asyncio.sleep(1.0)
                    except Exception:
                        pass

                if not imgs:
                    try:
                        gallery_items = await page.locator(
                            'button[class*="MediaGallery-module__item"], div[class*="MediaGallery-module__item"]'
                        ).all()
                        for item in gallery_items:
                            parent_cls = await item.evaluate(
                                "el => el.closest('section, div[class*=\"Rating\"], div[class*=\"Edition\"]')?.className || ''"
                            )
                            if any(k in parent_cls for k in ["EsrbRating", "CeroRating", "EditionCard"]):
                                continue
                            img_el = item.locator("img").first
                            if await img_el.count() > 0:
                                src = await img_el.get_attribute("src")
                                if src and ("store-images" in src or "images-microsoft-com" in src):
                                    clean = f"{src.split('?')[0]}?q=90&w=640&h=360"
                                    if clean not in imgs:
                                        imgs.append(clean)
                            if len(imgs) >= 12:
                                break

                        # セーフティフォールバック
                        if not imgs:
                            gallery_sel = (
                                'section[aria-labelledby*="gallery"], '
                                'section#ProductOverviewGallerySection, '
                                'section[class*="Gallery"]'
                            )
                            gallery = page.locator(gallery_sel).first
                            if await gallery.count() > 0:
                                for im in await gallery.locator("img").all():
                                    alt = await im.get_attribute("alt") or ""
                                    if "CERO" in alt or "Rating" in alt:
                                        continue
                                    src = await im.get_attribute("src")
                                    if src and ("store-images" in src or "images-microsoft-com" in src):
                                        clean = f"{src.split('?')[0]}?q=90&w=640&h=360"
                                        if clean not in imgs:
                                            imgs.append(clean)
                                    if len(imgs) >= 8:
                                        break
                    except Exception as e:
                        print(f"Gallery extraction error: {e}")

                # ---- 動画 ----
                video_url = "なし"
                video_thumbnail = None

                # ページ内 YouTube iframe を優先
                try:
                    gallery_sel = (
                        'section[aria-labelledby*="gallery"], '
                        'section#ProductOverviewGallerySection, '
                        'section[class*="Gallery"]'
                    )
                    gallery = page.locator(gallery_sel).first
                    scope = gallery if await gallery.count() > 0 else page.locator("body")
                    for f in await scope.locator('iframe[src*="youtube"], iframe[src*="youtu.be"]').all():
                        src = await f.get_attribute("src") or ""
                        m = re.search(r'(?:embed/|v=|youtu\.be/)([A-Za-z0-9_-]{11})', src)
                        if m:
                            video_url = f"https://www.youtube.com/watch?v={m.group(1)}"
                            break
                    if video_url == "なし":
                        m = re.search(r'youtube\.com/embed/([A-Za-z0-9_-]{11})', await page.content())
                        if m:
                            video_url = f"https://www.youtube.com/watch?v={m.group(1)}"
                except Exception:
                    pass

                # API 動画（HLS形式の場合は YouTube 検索でフォールバック）
                if video_url == "なし" and vids:
                    video_thumbnail = vids[0]["thumbnail"]
                    v_url = vids[0]["url"]
                    if ".m3u8" in v_url:
                        try:
                            v_title = (await page.locator("h1").inner_text()).strip()
                            print(f"Searching YouTube for: {v_title} Official Trailer")
                            await page.goto(
                                f"https://www.youtube.com/results?search_query={v_title}+Official+Trailer",
                                wait_until="networkidle",
                                timeout=15000,
                            )
                            first_vid = page.locator('ytd-video-renderer a#video-title, a[href*="/watch?v="]').first
                            if await first_vid.count() > 0:
                                href = await first_vid.get_attribute("href")
                                if "/watch?v=" in href:
                                    video_url = "https://www.youtube.com" + href
                        except Exception:
                            pass
                        if video_url == "なし":
                            video_url = f"https://hls-js.netlify.app/demo/?src={v_url}"
                    else:
                        video_url = v_url

                if video_url != "なし" and not video_thumbnail:
                    m = re.search(r'(?:v=|be/)([A-Za-z0-9_-]{11})', video_url)
                    if m:
                        video_thumbnail = f"https://img.youtube.com/vi/{m.group(1)}/maxresdefault.jpg"

                # ---- Play Anywhere ----
                is_play_anywhere = bool(api_extra and api_extra.get("play_anywhere"))
                if not is_play_anywhere:
                    try:
                        for sel in [
                            'div[class*="Capabilities-module__container"]',
                            'div[class*="ProductKeyFeatures-module"]',
                            'div[class*="ProductDetailsHeader-module__badgeWrapper"]',
                        ]:
                            els = page.locator(sel)
                            if await els.count() > 0 and "Xbox Play Anywhere" in await els.first.inner_text():
                                is_play_anywhere = True
                                break
                        if not is_play_anywhere and "Xbox Play Anywhere" in await page.content():
                            is_play_anywhere = True
                    except Exception:
                        pass

                # ---- レビュー評価 ----
                ratings_info = {
                    "average": api_ratings["avg"],
                    "total_count": api_ratings["count"],
                    "dist": {"5": "0%", "4": "0%", "3": "0%", "2": "0%", "1": "0%"},
                }
                if api_product_id:
                    detailed = await self.fetch_ratings_from_api(api_product_id)
                    if detailed:
                        ratings_info = detailed

                # フォールバック: ページスクレイピングで補完
                try:
                    if ratings_info["dist"]["5"] == "0%":
                        await page.evaluate("window.scrollTo(0, 1500)")
                        await asyncio.sleep(1.0)
                        review_tab = page.locator(
                            'button:has-text("レビュー"), [id*="review-tab"], '
                            '[aria-label*="レビュー"], button:has-text("Reviews")'
                        ).first
                        if await review_tab.count() > 0:
                            await review_tab.click()
                            await asyncio.sleep(2.0)

                    content = await page.content()
                    body_text = await page.inner_text("body")

                    if ratings_info["average"] == "0.0":
                        m_avg = re.search(r'"ratingValue":\s*"([\d.]+)"', content)
                        if m_avg:
                            ratings_info["average"] = m_avg.group(1)
                    if ratings_info["total_count"] == "0":
                        m_cnt = re.search(r'"ratingCount":\s*"(\d+)"', content)
                        if m_cnt:
                            ratings_info["total_count"] = m_cnt.group(1)

                    for s in ["5", "4", "3", "2", "1"]:
                        m_dist = re.search(rf'{s}\s*(?:★|星|star)?[^\d%]*?(\d+)%', body_text)
                        if m_dist:
                            ratings_info["dist"][s] = f"{m_dist.group(1)}%"

                    # aria-label から星内訳を抽出
                    all_aria = await page.evaluate("""
                        () => {
                            let results = [];
                            document.querySelectorAll('[aria-label]').forEach(e => {
                                if (e.getAttribute('aria-label').includes('星'))
                                    results.push(e.getAttribute('aria-label'));
                            });
                            return results;
                        }
                    """)
                    for aria in all_aria:
                        m = re.search(r'(\d)\s*つ星\s*(\d+)%', aria)
                        if m:
                            ratings_info["dist"][m.group(1)] = f"{m.group(2)}%"

                    # 平均がまだ 0.0 の場合、分布から算出
                    if ratings_info["average"] in ("0.0", "0"):
                        score_sum = sum(
                            int(s) * int(ratings_info["dist"].get(s, "0%").replace("%", ""))
                            for s in ["5", "4", "3", "2", "1"]
                            if ratings_info["dist"].get(s, "0%").replace("%", "").isdigit()
                        )
                        if score_sum > 0:
                            ratings_info["average"] = f"{score_sum / 100:.1f}"

                    if ratings_info["total_count"] == "0":
                        ratings_info["total_count"] = "--(非表示)"
                except Exception as e:
                    print(f"Rating parse error: {e}")

                # ---- 日本語サポート ----
                jp_support = None
                if api_extra and api_extra.get("jp_support"):
                    jp_support = api_extra["jp_support"]
                else:
                    try:
                        all_tabs = page.locator('button:has-text("その他")')
                        tab_found = False
                        for ti in range(await all_tabs.count()):
                            if await all_tabs.nth(ti).is_visible():
                                await dismiss_modal()
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
                                await asyncio.sleep(2.5)
                                tab_found = True
                                print("Clicked 'その他' tab")
                                break

                        if tab_found:
                            table = None
                            for tsel in ['[class*="LanguageSupport"]', "table", '[class*="languageSupport"]']:
                                for el in await page.locator(tsel).all():
                                    try:
                                        inner = await el.inner_text()
                                        if "サポートされている言語" in inner or "日本語" in inner:
                                            table = el
                                            break
                                    except Exception:
                                        continue
                                if table:
                                    break

                            if table:
                                jp_support = {"ui": False, "audio": False, "subtitles": False}
                                for row in await table.locator("tr").all():
                                    cells = await row.locator("td, th").all()
                                    if len(cells) < 4:
                                        continue
                                    lang_name = (await cells[0].inner_text()).strip()
                                    if "日本語" not in lang_name:
                                        continue
                                    # 列順: [1]=オーディオ [2]=インターフェイス [3]=字幕
                                    for ci, key in [(1, "audio"), (2, "ui"), (3, "subtitles")]:
                                        cell_html = await cells[ci].inner_html()
                                        cell_txt = await cells[ci].inner_text()
                                        aria = (await cells[ci].get_attribute("aria-label") or "").lower()
                                        if any([
                                            'aria-checked="true"' in cell_html.lower(),
                                            "checkedbox" in cell_html.lower(),
                                            "サポートされています" in cell_html,
                                            "supported" in cell_html.lower(),
                                            "supported" in aria,
                                            "サポートされています" in aria,
                                            "✓" in cell_txt,
                                            "○" in cell_txt,
                                        ]):
                                            jp_support[key] = True
                                    print(f"JP support: {jp_support}")
                                    break
                    except Exception as e:
                        print(f"Language support error: {e}")
                        traceback.print_exc()
                        jp_support = None

                return {
                    "genre": genre,
                    "description": desc_text,
                    "screenshots": imgs[:12],
                    "video_url": video_url,
                    "video_thumbnail": video_thumbnail,
                    "play_anywhere": is_play_anywhere,
                    "languages": jp_support,
                    "ratings": ratings_info,
                }

            except Exception as e:
                traceback.print_exc()
                return {
                    "genre": "取得エラー",
                    "description": f"エラー: {str(e)}",
                    "screenshots": [],
                    "video_url": "なし",
                    "video_thumbnail": None,
                    "play_anywhere": False,
                    "languages": None,
                    "ratings": {"average": "0.0", "total_count": "0", "dist": {}},
                }
            finally:
                await browser.close()
