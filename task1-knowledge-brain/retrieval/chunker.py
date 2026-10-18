from typing import List, Dict, Any

class DocumentChunker:
    """
    Heading-aware and context-preserving document chunker.
    Keeps instructions, prerequisite steps, and screenshots attached to chunks.
    """
    def __init__(self, max_chunk_chars: int = 900, overlap_chars: int = 150):
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars

    def chunk_article(self, parsed_article: Dict[str, Any]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        title = parsed_article.get("title", "")
        url = parsed_article.get("url", "")
        sections = parsed_article.get("sections", [])

        # Collect all article-level images as fallback
        all_article_imgs = []
        for s in sections:
            all_article_imgs.extend(s.get("images", []))

        fallback_img_urls = [img["url"] for img in all_article_imgs if "url" in img]
        fallback_img_descs = [img["description"] for img in all_article_imgs if "description" in img]

        if not sections:
            raw = parsed_article.get("raw_text", "")
            if raw:
                chunks.append({
                    "section_heading": "Overview",
                    "content": raw[:self.max_chunk_chars],
                    "image_urls": fallback_img_urls,
                    "image_descriptions": fallback_img_descs
                })
            return chunks

        for sec in sections:
            heading = sec.get("heading", "General")
            paragraphs = sec.get("paragraphs", [])
            images = sec.get("images", [])

            img_urls = [img["url"] for img in images if "url" in img] or fallback_img_urls
            img_descs = [img["description"] for img in images if "description" in img] or fallback_img_descs

            sec_text = "\n\n".join(paragraphs).strip()
            if not sec_text:
                continue

            if len(sec_text) <= self.max_chunk_chars:
                chunks.append({
                    "section_heading": heading,
                    "content": f"Article: {title}\nSection: {heading}\n\n{sec_text}",
                    "image_urls": img_urls,
                    "image_descriptions": img_descs
                })
            else:
                current_subchunk = []
                current_len = 0

                for p in paragraphs:
                    p_len = len(p)
                    if current_len + p_len > self.max_chunk_chars and current_subchunk:
                        sub_text = "\n\n".join(current_subchunk)
                        chunks.append({
                            "section_heading": heading,
                            "content": f"Article: {title}\nSection: {heading}\n\n{sub_text}",
                            "image_urls": img_urls,
                            "image_descriptions": img_descs
                        })
                        if len(current_subchunk[-1]) < self.overlap_chars:
                            current_subchunk = [current_subchunk[-1], p]
                            current_len = len(current_subchunk[0]) + p_len
                        else:
                            current_subchunk = [p]
                            current_len = p_len
                    else:
                        current_subchunk.append(p)
                        current_len += p_len

                if current_subchunk:
                    sub_text = "\n\n".join(current_subchunk)
                    chunks.append({
                        "section_heading": heading,
                        "content": f"Article: {title}\nSection: {heading}\n\n{sub_text}",
                        "image_urls": img_urls,
                        "image_descriptions": img_descs
                    })

        return chunks

document_chunker = DocumentChunker()
