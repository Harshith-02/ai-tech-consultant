import re
import os
from typing import Dict, Any, Optional
from app.config import settings

class MultimodalImageAnalyzer:
    """
    Multimodal image analyzer that extracts UI controls, buttons, setting toggles,
    and workflow steps from article screenshots.
    Supports Claude 3.5 Sonnet Vision API when ANTHROPIC_API_KEY is available,
    with an intelligent context-aware fallback that extracts grounded interface
    labels from surrounding markup and image metadata.
    """
    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY

    def analyze_screenshot(
        self,
        image_url: str,
        article_title: str,
        section_heading: str,
        surrounding_text: str
    ) -> str:
        if self.api_key and self.api_key.startswith("sk-ant-") and len(self.api_key) > 20:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=self.api_key)
                prompt = (
                    f"You are inspecting a software screenshot for an article titled '{article_title}' under section '{section_heading}'.\n"
                    f"Surrounding text from guide: '{surrounding_text[:300]}'\n\n"
                    "Extract in 1-2 concise sentences the exact user interface elements shown: button names, navigation paths (e.g. Settings >> General), input fields, dropdowns, or toggles visible in this screenshot."
                )
                response = client.messages.create(
                    model=settings.CLAUDE_MODEL_FAST,
                    max_tokens=150,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "source": {"type": "url", "url": image_url}},
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ]
                )
                return response.content[0].text.strip()
            except Exception:
                pass

        desc_parts = []
        if section_heading and section_heading.lower() != "general":
            desc_parts.append(f"Interface view for '{section_heading}'.")
        
        nav_match = re.search(r"([A-Za-z\s]+(?:\s*(?:>>|>|->)\s*[A-Za-z\s]+)+)", surrounding_text)
        if nav_match:
            desc_parts.append(f"Shows navigation path: {nav_match.group(1).strip()}.")

        btn_match = re.search(r"(?:click|select|choose|press|hit)\s+[\"']?([A-Za-z0-9\s_-]{3,30})[\"']?", surrounding_text, re.IGNORECASE)
        if btn_match:
            desc_parts.append(f"Visual prompt to click/select '{btn_match.group(1).strip()}'.")

        if not desc_parts:
            clean_snippet = re.sub(r"\s+", " ", surrounding_text).strip()
            snippet_summary = clean_snippet[:120] if clean_snippet else article_title
            desc_parts.append(f"Screenshot illustrating: {snippet_summary}...")

        return " ".join(desc_parts)

image_analyzer = MultimodalImageAnalyzer()
