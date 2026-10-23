import re
import hashlib
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from multimodal.image_analyzer import image_analyzer

class ArticleParser:
    """
    Parses help center HTML into clean structured articles with sections,
    tables, lists, and context-linked screenshots.
    """
    def __init__(self):
        pass

    @staticmethod
    def extract_article_id(url: str) -> str:
        match = re.search(r"/articles/(\d+)(?:-([^/?#]+))?", url)
        if match:
            aid = match.group(1)
            slug = match.group(2) or "article"
            return f"{aid}-{slug[:30]}"
        clean_url = url.split("?")[0].rstrip("/")
        slug_part = clean_url.split("/")[-1]
        slug_part = re.sub(r"[^a-zA-Z0-9_-]", "", slug_part)
        hash_prefix = hashlib.md5(url.encode()).hexdigest()[:8]
        if slug_part:
            return f"{hash_prefix}-{slug_part[:25]}"
        return hash_prefix

    def parse_html(self, html_content: str, url: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_content, "html.parser")

        title = ""
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(strip=True)
        elif soup.title and soup.title.get_text(strip=True):
            title = soup.title.get_text(strip=True).split("|")[0].strip()
        else:
            title = "Help Article"

        category = "General"
        breadcrumb = soup.select(".breadcrumb, .breadcrumbs, .breadcrumb-item, nav[aria-label='breadcrumb']")
        if breadcrumb:
            crumb_texts = [b.get_text(strip=True) for b in breadcrumb[0].find_all(["a", "li", "span"]) if b.get_text(strip=True)]
            if len(crumb_texts) > 1:
                category = " >> ".join(crumb_texts[-3:])

        body_elem = None
        for selector in ["#article-body", ".article-body", ".article__body", "article", ".solution-article", ".content"]:
            match = soup.select_one(selector)
            if match and len(match.get_text(strip=True)) > 100:
                body_elem = match
                break
        
        if not body_elem:
            body_elem = soup.body or soup

        for unwanted in body_elem.find_all(["script", "style", "nav", "footer", ".share-box", ".feedback-box", ".related-articles"]):
            unwanted.decompose()

        sections: List[Dict[str, Any]] = []
        current_section = {
            "heading": "Overview",
            "paragraphs": [],
            "images": []
        }

        raw_images = body_elem.find_all("img")
        valid_images = []
        for img in raw_images:
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            if any(term in src.lower() for term in ["logo", "avatar", "icon", "spinner", "spacer", ".svg"]):
                continue
            
            prev_elem = img.find_previous(["p", "li", "h2", "h3", "h4", "strong"])
            prev_text = prev_elem.get_text(strip=True) if prev_elem else ""
            
            next_elem = img.find_next(["p", "li", "h2", "h3", "h4"])
            next_text = next_elem.get_text(strip=True) if next_elem else ""
            
            surrounding = f"{prev_text} {next_text}".strip()
            
            valid_images.append({
                "src": src,
                "alt": img.get("alt", "").strip(),
                "surrounding_text": surrounding
            })

        elements = body_elem.find_all(["h2", "h3", "h4", "p", "ul", "ol", "table", "blockquote"])
        for el in elements:
            tag = el.name
            text = el.get_text(separator=" ", strip=True)
            if not text:
                continue

            if tag in ["h2", "h3", "h4"]:
                if current_section["paragraphs"] or current_section["images"]:
                    sections.append(current_section)
                current_section = {
                    "heading": text,
                    "paragraphs": [],
                    "images": []
                }
            elif tag in ["ul", "ol"]:
                items = [li.get_text(strip=True) for li in el.find_all("li") if li.get_text(strip=True)]
                if items:
                    list_text = "\n".join(f"• {it}" for it in items)
                    current_section["paragraphs"].append(list_text)
            elif tag == "table":
                rows = []
                for tr in el.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    current_section["paragraphs"].append("\n".join(rows))
            else:
                current_section["paragraphs"].append(text)

        if current_section["paragraphs"] or current_section["images"]:
            sections.append(current_section)

        for img_info in valid_images:
            desc = image_analyzer.analyze_screenshot(
                image_url=img_info["src"],
                article_title=title,
                section_heading=sections[0]["heading"] if sections else "Overview",
                surrounding_text=img_info["surrounding_text"]
            )
            img_record = {
                "url": img_info["src"],
                "alt": img_info["alt"],
                "description": desc
            }
            if sections:
                sections[0]["images"].append(img_record)

        all_text = f"{title}\n" + "\n\n".join(
            f"## {s['heading']}\n" + "\n".join(s['paragraphs']) for s in sections
        )
        content_hash = hashlib.sha256(all_text.encode("utf-8")).hexdigest()
        article_id = self.extract_article_id(url)

        return {
            "article_id": article_id,
            "url": url,
            "title": title,
            "category": category,
            "content_hash": content_hash,
            "raw_text": all_text,
            "sections": sections,
            "screenshot_count": len(valid_images)
        }

article_parser = ArticleParser()
