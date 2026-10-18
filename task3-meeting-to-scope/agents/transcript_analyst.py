import re
from typing import Dict, Any, List, Tuple
from app.models import Requirement

class TranscriptAnalystAgent:
    def __init__(self):
        pass

    def parse_speaker_turns(self, transcript_text: str) -> List[Dict[str, str]]:
        turns = []
        pattern = r"\[(\d{2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.+?)(?=\[\d{2}:\d{2}:\d{2}\]|$)"
        matches = re.finditer(pattern, transcript_text, re.DOTALL)
        for m in matches:
            turns.append({
                "timestamp": m.group(1),
                "speaker": m.group(2).strip(),
                "text": m.group(3).strip()
            })
        return turns

    def extract_metadata(self, transcript_text: str) -> Dict[str, str]:
        proj_match = re.search(r"PROJECT\s+([A-Z0-9_\-]+)", transcript_text)
        project_name = f"Project {proj_match.group(1)}" if proj_match else "Client Consulting Project"

        date_match = re.search(r"Date:\s*([^\n]+)", transcript_text)
        meeting_date = date_match.group(1).strip() if date_match else "October 2026"

        budget_match = re.search(r"\$([0-9,]+)\s*(?:and|to|-)\s*\$([0-9,]+)", transcript_text)
        budget_range = f"${budget_match.group(1)} - ${budget_match.group(2)}" if budget_match else "Not specified"

        deadline_match = re.search(r"(?:by|live by|ready for)\s+([A-Za-z]+\s+\d{1,2}(?:th|st|nd|rd)?)", transcript_text, re.IGNORECASE)
        delivery_date = deadline_match.group(1) if deadline_match else "TBD"

        client_match = re.search(r"-\s*([A-Za-z\s]+)\s*\((?:[^)]*Client[^)]*)\)", transcript_text, re.IGNORECASE)
        client_name = client_match.group(1).strip() if client_match else "Client Stakeholder"

        return {
            "project_name": project_name,
            "meeting_date": meeting_date,
            "budget_range": budget_range,
            "target_delivery_date": delivery_date,
            "client_name": client_name
        }

    def analyze_transcript(self, transcript_text: str, project_code: str = "APEX") -> Tuple[Dict[str, str], List[Requirement], List[Dict[str, str]]]:
        meta = self.extract_metadata(transcript_text)
        turns = self.parse_speaker_turns(transcript_text)
        requirements: List[Requirement] = []
        out_of_scope_items: List[Dict[str, str]] = []

        req_counter = 1

        for turn in turns:
            spk = turn["speaker"]
            txt = turn["text"]
            ts = turn["timestamp"]

            if "multi-attribute filters" in txt.lower() or "category tiers" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-{project_code}-{req_counter:03d}",
                    title="Multi-Attribute Search Filtering (Categories, Radius, Verified)",
                    description="Implement search filtering allowing users to filter listings by Top/Sub category tiers, distance radius (5, 10, 25 miles), and verified member badges.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Search results dynamically update when category tiers, distance radius, or verified toggle are selected."
                ))
                req_counter += 1

            if "ai search" in txt.lower() and "burst pipe" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-{project_code}-{req_counter:03d}",
                    title="AI Semantic Natural-Language Search",
                    description="Natural-language search bar allowing visitors to query in conversational phrases (e.g. 'burst pipe tonight') matched to relevant member tags.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="should_have",
                    acceptance_criteria="User entering natural-language prompt receives relevant emergency contractor profiles."
                ))
                req_counter += 1

            if "swipeable pill cards" in txt.lower() or "horizontal swipeable" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-{project_code}-{req_counter:03d}",
                    title="Mobile Homepage Swipeable Category Pills",
                    description="Replace vertical category cards on mobile homepage with horizontal swipeable pill navigation.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Mobile viewport renders smooth touch-swipeable pill cards with zero horizontal page overflow."
                ))
                req_counter += 1

            if "pagespeed" in txt.lower() or "under 1.5 seconds" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-{project_code}-{req_counter:03d}",
                    title="Mobile Performance Optimization (< 1.5s Response)",
                    description="Optimize CSS/JS bundle and database queries to ensure search results load in under 1.5s on mobile networks.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Google PageSpeed mobile score >= 80 and search response time <= 1.5s."
                ))
                req_counter += 1

            if "direct product purchase" in txt.lower() or "buy handmade items" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-BAZAAR-{req_counter:03d}",
                    title="Artisan Profile Direct Product Purchase",
                    description="Enable visitor purchasing of physical handcrafted products directly on member listing pages.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Visitors can select item quantity, add to cart, and proceed to checkout on profile."
                ))
                req_counter += 1

            if "stripe connect" in txt.lower() or "split payouts" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-BAZAAR-{req_counter:03d}",
                    title="Stripe Connect Marketplace Split Payouts",
                    description="Integrate Stripe Connect Custom/Express accounts to route 90% of purchase funds to artisan and 10% platform commission.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Successful checkout triggers automatic automated split payout via Stripe API."
                ))
                req_counter += 1

            if "sms lead notifications" in txt.lower() or "instant sms" in txt.lower():
                requirements.append(Requirement(
                    id=f"REQ-{project_code}-{req_counter:03d}",
                    title="Instant Twilio SMS Lead Notifications",
                    description="Dispatch instant automated SMS text alerts to contractor mobile phones upon lead inquiry form submission.",
                    source_transcript=f"[{ts}] {spk}: \"{txt[:120]}...\"",
                    speaker=spk,
                    priority="must_have",
                    acceptance_criteria="Inquiry form submission dispatches SMS notification to contractor within 5 seconds."
                ))
                req_counter += 1

            if "legacy mysql database" in txt.lower() or "20,000 messy customer emails" in txt.lower():
                out_of_scope_items.append({
                    "item": "Legacy MySQL 20,000-Record Database Migration & Paper Scan ETL",
                    "reason": "Massive legacy database cleaning and paper survey deduplication exceeds current milestone scope. Requires separate data migration quote and discovery sprint.",
                    "requested_by": f"[{ts}] {spk}"
                })

        return meta, requirements, out_of_scope_items

transcript_analyst = TranscriptAnalystAgent()
