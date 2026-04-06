import asyncio
import re
import aiohttp
import traceback
from playwright.async_api import async_playwright


class XboxScraper:
    def __init__(self):
        self.base_url = "https://www.xbox.com/ja-jp/games/all-games?PlayWith=XboxSeriesXS,XboxOne&SortBy=TopPaid"

    async def fetch_ranking(self, limit=350):
        """ランキング一覧を取得する"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="ja-JP",
                ignore_https_errors=True
            )
            page = await context.new_page()

            print(f"Fetching ranking from: {self.base_url}")
            try:
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"Warning: page.goto timeout or error: {e}")
            await asyncio.sleep(2.0)

            card_sel = 'a[class*="basicButton"]'
            for _ in range(40): # 350件程度まで読み込めるようにループ回数を最適化
                current_cards = await page.query_selector_all(card_sel)
                valid = [c for c in current_cards
                         if await c.get_attribute("title") or await c.get_attribute("aria-label")]
                print(f"Valid cards so far: {len(valid)}")
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
                    title_match = re.match(r"^『?(.+?)』?[、,]", aria_label)
                    title = title_match.group(1) if title_match else aria_label.split("、")[0]

                if not title and not aria_label:
                    continue

                if url and not url.startswith("http"):
                    url = "https://www.xbox.com" + url

                price_info = self._parse_aria_label(aria_label)

                is_gp = False
                if "Game Pass" in aria_label or "ゲーム パス" in aria_label:
                    is_gp = True
                if not is_gp:
                    badge = await card.query_selector('[class*="Badge-module__badge"], [class*="gamePass"]')
                    if badge:
                        is_gp = True
                if not is_gp:
                    try:
                        inner_text = await card.inner_text()
                        if "GAME PASS" in inner_text.upper():
                            is_gp = True
                    except Exception:
                        pass

                ranking_data.append({
                    "rank": len(ranking_data) + 1,
                    "title": title if title else "タイトル不明",
                    "price": price_info["current_price"],
                    "original_price": price_info["original_price"],
                    "is_sale": price_info["is_sale"],
                    "is_game_pass": is_gp,
                    "url": url
                })

            await browser.close()
            print(f"Fetched {len(ranking_data)} items.")
            return ranking_data

    def _parse_aria_label(self, label):
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

    async def fetch_media_from_api(self, product_id):
        """Microsoft Display Catalog API を使用してメディア（画像・動画）を直接取得する (年齢制限回避)"""
        api_url = f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={product_id}&market=JP&languages=ja-JP"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if not data.get("Products"):
                            return [], [], {"avg": "0.0", "count": "0"}, None, None
                        
                        product = data["Products"][0]
                        prop = product.get("LocalizedProperties", [{}])[0]
                        
                        # 画像 (ギャラリー素材) の抽出
                        imgs = []
                        api_images = prop.get("Images", [])
                        # 優先順位: SuperHeroArt (メイン) -> Screenshot -> Wallpaper
                        for purpose in ["SuperHeroArt", "Screenshot", "Wallpaper"]:
                            for img in api_images:
                                if img.get("ImagePurpose") == purpose:
                                    uri = img.get("Uri")
                                    if uri:
                                        if uri.startswith("//"):
                                            uri = "https:" + uri
                                        
                                        # 重複チェック (ベースURLで比較)
                                        base_url = uri.split('?')[0]
                                        if not any(base_url in (existing.split('?')[0]) for existing in imgs):
                                            imgs.append(uri)
                        # 動画 (トレイラー) の抽出
                        vids = []
                        api_videos = prop.get("CMSVideos", [])
                        for vid in api_videos:
                            # HeroTrailer または Trailer
                            if vid.get("VideoPurpose") in ["HeroTrailer", "Trailer"]:
                                # プレビュー画像とストリーミングURLの両方を保持
                                hls_url = vid.get("HLS")
                                if hls_url and hls_url.startswith("//"):
                                    hls_url = "https:" + hls_url
                                
                                preview = vid.get("PreviewImage", {}).get("Uri")
                                if preview and preview.startswith("//"):
                                    preview = "https:" + preview
                                
                                vids.append({
                                    "url": hls_url or preview, # 再生先
                                    "thumbnail": preview      # 表示用
                                })
                        
                        # 評価データの抽出 (MarketProperties -> UsageData)
                        ratings = {"avg": "0.0", "count": "0"}
                        market_props = product.get("MarketProperties", [{}])
                        if market_props:
                            usage_data = market_props[0].get("UsageData", [])
                            for usage in usage_data:
                                if usage.get("AggregateTimeSpan") == "AllTime":
                                    ratings["avg"] = f"{usage.get('AverageRating', 0.0):.1f}"
                                    ratings["count"] = str(usage.get("RatingCount", 0))
                                    break
                        
                        
                        # (追加) 詳細情報・言語・Play Anywhereの抽出
                        api_extra = {
                            "description": None,
                            "play_anywhere": False,
                            "jp_support": None
                        }
                        
                        desc = prop.get("ProductDescription")
                        if not desc:
                            desc = prop.get("ShortDescription")
                        if desc:
                            # タグなどが含まれている場合があるが基本はテキスト
                            api_extra["description"] = desc
                            
                        # Play Anywhere
                        attrs = [a.get("Name") for a in product.get("Properties", {}).get("Attributes", [])]
                        if "XPA" in attrs or "XboxPlayAnywhere" in attrs or "Xbox Play Anywhere" in attrs:
                            api_extra["play_anywhere"] = True
                            
                        # 日本語対応
                        lang = prop.get("Language", "").lower()
                        has_jp = "ja" in lang or "jp" in lang or "japanese" in lang or "日本語" in lang
                        if not has_jp:
                            for sku_av in product.get("DisplaySkuAvailabilities", []):
                                for pkg in sku_av.get("Sku", {}).get("Properties", {}).get("Packages", []):
                                    for l in pkg.get("Languages", []):
                                        if isinstance(l, str) and ("ja" in l.lower() or "jp" in l.lower()):
                                            has_jp = True
                                            break
                                            
                        if has_jp:
                            # APIで多言語サポートが確認できた場合、UI/音声/字幕が対応していると仮定(APIで細分化されていないため)
                            api_extra["jp_support"] = {"ui": True, "audio": True, "subtitles": True}
                        
                        return imgs, vids, ratings, product.get("ProductId"), api_extra
        except Exception as e:
            print(f"API Media Fetch Error: {e}")
        return [], [], {"avg": "0.0", "count": "0"}, None, None

    async def fetch_ratings_from_api(self, product_id):
        """emerald.xboxservices.com API を使用して、星1〜5の内訳を含む詳細な評価データを取得する"""
        url = f"https://emerald.xboxservices.com/xboxcomfd/ratingsandreviews/summaryandreviews/{product_id}?locale=ja-JP&starFilter=NoFilter&itemCount=25"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "x-ms-api-version": "1.0",
            "ms-cv": "D6BfX/yPqE6N1i2z.1",
            "referer": "https://www.xbox.com/",
            "origin": "https://www.xbox.com"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        # フィールド名の存在確認 (ratingsSummary オブジェクト内に格納されている)
                        summary = data.get("ratingsSummary", {})
                        total = summary.get("totalRatingsCount", 0)
                        dist = {}
                        for i in range(1, 6):
                            # APIにより count が missing の場合があるため対処
                            count = summary.get(f"star{i}Count", 0)
                            pct = 0
                            if total > 0:
                                pct = int((count / total) * 100)
                            dist[str(i)] = f"{pct}%"
                        
                        return {
                            "average": f"{summary.get('averageRating', 0.0):.1f}",
                            "total_count": str(total),
                            "dist": dist
                        }
                    else:
                        print(f"API Ratings Fetch Error ({product_id}): Status {response.status}")
        except Exception as e:
            print(f"API Ratings Fetch Exception ({product_id}): {e}")
        return None

    async def fetch_details(self, url):
        """詳細取得 (説明、画像、動画、言語サポート)"""
        # URLの正規化とレビューセクションへの直接遷移設定
        url = url.replace("/ja-jp/", "/ja-JP/")
        if "activetab" not in url:
            sep = "&" if "?" in url else "?"
            url += f"{sep}activetab=pivot:reviewstab"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ja-JP",
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"Warning: page.goto timeout or error in fetch_details: {e}")
                await asyncio.sleep(2.0)

                # --- 年齢確認モーダルをJSで強制削除 ---
                async def dismiss_modal():
                    try:
                        removed = await page.evaluate("""
                            () => {
                                let n = 0;
                                document.querySelectorAll('reach-portal').forEach(e => { e.remove(); n++; });
                                document.querySelectorAll('[data-reach-dialog-overlay],[class*="modalOverlay"],[class*="AgeGating"]').forEach(e => { e.remove(); n++; });
                                return n;
                            }
                        """)
                        if removed > 0:
                            await asyncio.sleep(0.3)
                    except:
                        pass

                # --- 年齢確認・素材取得 (API方式) ---
                product_id_match = re.search(r"/([a-zA-Z0-9]{12})($|\?|/)", url)
                product_id = product_id_match.group(1) if product_id_match else None
                
                imgs = []
                vids = []
                api_ratings = {"avg": "0.0", "count": "0"}
                api_product_id = None
                api_extra = None
                
                if product_id:
                    imgs, vids, api_ratings, api_product_id, api_extra = await self.fetch_media_from_api(product_id)
                    if not api_product_id: api_product_id = product_id
                    
                    if imgs:
                        print(f"Fetched {len(imgs)} images from API for {api_product_id}")

                # --- 詳細説明 ---
                desc_text = "説明なし"
                if api_extra and api_extra.get("description"):
                    desc_text = api_extra["description"]
                
                if desc_text == "説明なし":
                    try:
                        expand = page.locator('button:has-text("続きを表示"), button:has-text("詳細を表示"), button:has-text("さらに表示")').first
                        if await expand.count() > 0 and await expand.is_visible():
                            await expand.click()
                            await asyncio.sleep(0.5)
                    except:
                        pass

                    for sel in [
                        'div[class*="Description-module__descriptionContainer"]',
                        'div[class*="Description-module__description"]',
                        'div[class*="ProductDescription-module__description"]',
                        'div[class*="ExpandableText-module__container"]',
                        'div[id="product-description"]',
                    ]:
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
                                content = (await h2.locator('xpath=./..').inner_text()).replace("説明", "").strip()
                                if len(content) > 50:
                                    desc_text = content
                        except:
                            pass

                # --- ジャンル ---
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
                except:
                    pass

                # --- 画像取得 (API未取得時のフォールバック) ---
                if not imgs:
                    # 年齢制限が解除されたことを確認 (「生年月日の入力」ボタンが消えるまで待機)
                    try:
                        await asyncio.sleep(1.0)
                        blocked_in_gallery = page.locator('section[class*="Gallery"] button:has-text("生年月日の入力")').first
                        if await blocked_in_gallery.count() > 0:
                            # モーダルを閉じる
                            await dismiss_modal()
                            await page.evaluate("window.scrollBy(0, 100)")
                            await asyncio.sleep(1.0)
                    except:
                        pass

                if not imgs:
                    # Xboxストアのギャラリーアイテムは 'MediaGallery' クラスを持つ button 内に配置されている
                    try:
                        # ギャラリー内の全アイテム(画像)を特定
                        # MediaGallery-module__item などのクラスを持つ要素内の img を探す
                        gallery_items = await page.locator('button[class*="MediaGallery-module__item"], div[class*="MediaGallery-module__item"]').all()
                        
                        for item in gallery_items:
                            # 不要な要素（CEROロゴ等）が含まれる親要素をチェックして除外
                            parent_html = await item.evaluate("el => el.closest('section, div[class*=\"Rating\"], div[class*=\"Edition\"]')?.className || ''")
                            if "EsrbRating" in parent_html or "CeroRating" in parent_html or "EditionCard" in parent_html:
                                continue

                            img_el = item.locator('img').first
                            if await img_el.count() > 0:
                                src = await img_el.get_attribute("src")
                                if src and ("store-images" in src or "images-microsoft-com" in src):
                                    base = src.split('?')[0]
                                    # 詳細表示用に高解像度化
                                    clean = f"{base}?q=90&w=640&h=360"
                                    if clean not in imgs:
                                        imgs.append(clean)
                            if len(imgs) >= 12: break

                        # もし MediaGallery 経由で取れなかった場合のセーフティ
                        if not imgs:
                            gallery_sel = 'section[aria-labelledby*="gallery"], section#ProductOverviewGallerySection, section[class*="Gallery"]'
                            gallery_section = page.locator(gallery_sel).first
                            if await gallery_section.count() > 0:
                                for im in await gallery_section.locator('img').all():
                                    # ロゴ類をパス記号やクラス名でより厳密に排除
                                    alt = await im.get_attribute("alt") or ""
                                    if "CERO" in alt or "Rating" in alt: continue
                                    
                                    src = await im.get_attribute("src")
                                    if src and ("store-images" in src or "images-microsoft-com" in src):
                                        base = src.split('?')[0]
                                        clean = f"{base}?q=90&w=640&h=360"
                                        if clean not in imgs: imgs.append(clean)
                                    if len(imgs) >= 8: break
                    except Exception as e:
                        print(f"Gallery extraction error: {e}")

                # --- YouTube動画 (ページ内抽出 & API & YouTube検索) ---
                video_url = "なし"
                video_thumbnail = None
                
                # ページタイトルを取得 (検索用)
                v_title = ""
                try: 
                    v_title = (await page.locator('h1').inner_text()).strip()
                except:
                    pass
                
                # 1. ページ内のiframe(YouTube)をまず探す
                try:
                    gallery_sel = 'section[aria-labelledby*="gallery"], section#ProductOverviewGallerySection, section[class*="Gallery"]'
                    gallery_section = page.locator(gallery_sel).first
                    target_scope = gallery_section if await gallery_section.count() > 0 else page.locator("body")
                    
                    for f in await target_scope.locator('iframe[src*="youtube"], iframe[src*="youtu.be"]').all():
                        src = await f.get_attribute("src") or ""
                        m = re.search(r'(?:embed/|v=|youtu\.be/)([A-Za-z0-9_-]{11})', src)
                        if m:
                            video_url = f"https://www.youtube.com/watch?v={m.group(1)}"
                            break
                    
                    if video_url == "なし":
                        # コンテンツ全体から抽出
                        m = re.search(r'youtube\.com/embed/([A-Za-z0-9_-]{11})', await page.content())
                        if m:
                            video_url = f"https://www.youtube.com/watch?v={m.group(1)}"
                except:
                    pass

                # 2. ページ内に見つからず、APIでの取得がある場合
                if video_url == "なし" and vids:
                    # API動画のサムネイルは常に利用
                    video_thumbnail = vids[0]["thumbnail"]
                    v_url = vids[0]["url"]
                    
                    if ".m3u8" in v_url:
                        # HLS (API動画) しかない場合、YouTubeで同タイトルのトレーラーを検索して「再生可能」なリンクを得る
                        if v_title:
                            try:
                                print(f"Searching YouTube for: {v_title} Official Trailer")
                                await page.goto(f"https://www.youtube.com/results?search_query={v_title}+Official+Trailer", wait_until="networkidle", timeout=15000)
                                # 最初に出てくる動画リンクを取得
                                first_vid = page.locator('ytd-video-renderer a#video-title, a[href*="/watch?v="]').first
                                if await first_vid.count() > 0:
                                    href = await first_vid.get_attribute("href")
                                    if "/watch?v=" in href:
                                        video_url = "https://www.youtube.com" + href
                            except:
                                pass
                        
                        # YouTube検索も失敗した場合は HLSプレイヤーを最終手段にする
                        if video_url == "なし":
                            video_url = f"https://hls-js.netlify.app/demo/?src={v_url}"
                    else:
                        video_url = v_url
                
                # サムネイルがまだ無い場合はYouTubeから補完
                if video_url != "なし" and not video_thumbnail:
                    m = re.search(r'(?:v=|be/)([A-Za-z0-9_-]{11})', video_url)
                    if m:
                        video_thumbnail = f"https://img.youtube.com/vi/{m.group(1)}/maxresdefault.jpg"

                # --- Xbox Play Anywhere ---
                is_play_anywhere = False
                if api_extra and api_extra.get("play_anywhere", False):
                    is_play_anywhere = True
                else:
                    try:
                        for sel in [
                            'div[class*="Capabilities-module__container"]',
                            'div[class*="ProductKeyFeatures-module"]',
                            'div[class*="ProductDetailsHeader-module__badgeWrapper"]',
                        ]:
                            els = page.locator(sel)
                            if await els.count() > 0:
                                if "Xbox Play Anywhere" in await els.first.inner_text():
                                    is_play_anywhere = True
                                    break
                        if not is_play_anywhere and "Xbox Play Anywhere" in await page.content():
                            is_play_anywhere = True
                    except:
                        pass

                # --- レビュー評価 (APIを優先) ---
                ratings_info = {
                    "average": api_ratings["avg"], 
                    "total_count": api_ratings["count"], 
                    "dist": {"5": "0%", "4": "0%", "3": "0%", "2": "0%", "1": "0%"}
                }
                
                # 詳細な内訳(星1-5)をAPIから取得 (取得した正式なIDを使用)
                if api_product_id:
                    detailed_ratings = await self.fetch_ratings_from_api(api_product_id)
                    if detailed_ratings:
                        ratings_info = detailed_ratings

                try:
                    # 分布がまだ0%の場合のみ、スクレイピングを試みる(フォールバック)
                    if ratings_info["dist"]["5"] == "0%":
                        await page.evaluate("window.scrollTo(0, 1500)")
                        await asyncio.sleep(1.0)
                        
                        review_tab = page.locator('button:has-text("レビュー"), [id*="review-tab"], [aria-label*="レビュー"], button:has-text("Reviews")').first
                        if await review_tab.count() > 0:
                            await review_tab.click()
                            await asyncio.sleep(2.0)
                        
                        content = await page.content()
                        # APIで平均が取れていない場合のみ補完
                        if ratings_info["average"] == "0.0":
                            m_avg = re.search(r'"ratingValue":\s*"([\d.]+)"', content)
                            if m_avg: ratings_info["average"] = m_avg.group(1)
                        if ratings_info["total_count"] == "0":
                            m_cnt = re.search(r'"ratingCount":\s*"(\d+)"', content)
                            if m_cnt: ratings_info["total_count"] = m_cnt.group(1)
                        
                        body_text = await page.inner_text("body")
                        # 星1-5の内訳抽出
                        for s in ["5", "4", "3", "2", "1"]:
                            m_dist = re.search(fr'{s}\s*(?:★|星|star)?[^\d%]*?(\d+)%', body_text)
                            if m_dist: 
                                ratings_info["dist"][s] = f"{m_dist.group(1)}%"

                    body_text = await page.inner_text("body")
                    
                    if ratings_info["average"] == "0.0":
                        p_avg = re.search(r'(\d\.\d)\s*星の評価|(\d\.\d)\s*/\s*5|(\d\.\d)つ星', body_text)
                        if p_avg: ratings_info["average"] = p_avg.group(1) or p_avg.group(2) or p_avg.group(3)
                        p_cnt = re.search(r'合計(?:レビュー|評価)(?:数)?\s*([0-9,.]+[a-zA-Z]?)|\(([0-9,.]+[KkMm]?)\)\s*評価', body_text)
                        if p_cnt: ratings_info["total_count"] = p_cnt.group(1) or p_cnt.group(2)
                    
                    # 星1-5の内訳 (テキストから直接抽出)
                    for s in ["5", "4", "3", "2", "1"]:
                        m_dist = re.search(fr'{s}\s*(?:★|星|star)?[^\d%]*?(\d+)%', body_text)
                        if m_dist: 
                            ratings_info["dist"][s] = f"{m_dist.group(1)}%"
                            
                    all_aria = await page.evaluate("""
                        () => {
                            let results = [];
                            document.querySelectorAll('[aria-label]').forEach(e => {
                                if (e.getAttribute('aria-label').includes('星')) results.push(e.getAttribute('aria-label'));
                            });
                            return results;
                        }
                    """)
                    for aria in all_aria:
                        m = re.search(r'(\d)\s*つ星\s*(\d+)%', aria)
                        if m: ratings_info["dist"][m.group(1)] = f"{m.group(2)}%"
                        
                    if ratings_info["average"] == "0.0" or ratings_info["average"] == "0":
                        score_sum = 0
                        for s in ["5", "4", "3", "2", "1"]:
                            pct_str = ratings_info["dist"].get(s, "0%").replace("%", "")
                            if pct_str.isdigit():
                                score_sum += int(s) * int(pct_str)
                        if score_sum > 0:
                            ratings_info["average"] = f"{score_sum / 100:.1f}"

                    if ratings_info["total_count"] == "0":
                        ratings_info["total_count"] = "--(非表示)"
                except Exception as e:
                    print(f"RATING PARSE EXCEPTION: {e}")

                # --- 日本語サポート状況 ---
                jp_support = None
                
                # まずAPIから取得した結果があればそれを利用する
                if api_extra and api_extra.get("jp_support"):
                    jp_support = api_extra["jp_support"]
                else:
                    # 「その他」タブ（visible=Trueのもの）をJSでクリック → 言語テーブルを解析
                    try:
                        tab_found = False
                        all_tabs = page.locator('button:has-text("その他")')
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
                            print("Looking for table...")
                            table = None
                            # 全てのテーブル候補をチェック
                            for tsel in ['[class*="LanguageSupport"]', 'table', '[class*="languageSupport"]']:
                                elements = await page.locator(tsel).all()
                                for el in elements:
                                    try:
                                        inner = await el.inner_text()
                                        if "サポートされている言語" in inner or "日本語" in inner:
                                            table = el
                                            print(f"Found correct table with selector: {tsel}")
                                            break
                                    except: continue
                                if table: break

                            if table:
                                jp_support = {"ui": False, "audio": False, "subtitles": False}
                                rows = await table.locator('tr').all()
                                print(f"Table has {len(rows)} rows.")
                                for row in rows:
                                    cells = await row.locator('td, th').all()
                                    if len(cells) >= 4:
                                        lang_name = (await cells[0].inner_text()).strip()
                                        if "日本語" in lang_name:
                                            print(f"Matched language: {lang_name}")
                                            # 列順: [1]=オーディオ [2]=インターフェイス [3]=字幕
                                            for ci, key in [(1, "audio"), (2, "ui"), (3, "subtitles")]:
                                                cell_html = await cells[ci].inner_html()
                                                html_lower = cell_html.lower()
                                                cell_txt = await cells[ci].inner_text()
                                                aria_label = (await cells[ci].get_attribute("aria-label") or "").lower()
                                                
                                                if (
                                                    'aria-checked="true"' in html_lower
                                                    or 'checkedbox' in html_lower
                                                    or 'サポートされています' in cell_html
                                                    or 'supported' in html_lower
                                                    or 'supported' in aria_label
                                                    or 'サポートされています' in aria_label
                                                    or "✓" in cell_txt
                                                    or "○" in cell_txt
                                                ):
                                                    jp_support[key] = True
                                            print(f"Final JP support: {jp_support}")
                                            break
                            else:
                                print("Language support table NOT found even after tab click.")
                    except Exception as e:
                        print(f"Language support error: {e}")
                        import traceback
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
                    "ratings": ratings_info
                }
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {
                    "genre": "取得エラー",
                    "description": f"エラー: {str(e)}",
                    "screenshots": [],
                    "video_url": "なし",
                    "play_anywhere": False,
                    "languages": None
                }
            finally:
                await browser.close()
