import httpx
from typing import Dict, Any, List
from app.models import Requirement

class ProductFeasibilityAgent:
    def __init__(self, task1_api_url: str = "http://127.0.0.1:8000"):
        self.api_url = task1_api_url.rstrip("/")

    def check_feasibility(self, requirement: Requirement) -> Requirement:
        query_text = f"{requirement.title}. {requirement.description}"
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(
                    f"{self.api_url}/query",
                    json={"question": query_text, "top_k": 3},
                    headers={"X-Client-Service": "Meeting-To-Scope-Task3"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    sources = data.get("sources", [])
                    confidence = data.get("confidence", 0.0)

                    if status == "answered" and confidence >= 0.60 and sources:
                        top_source = sources[0]
                        lower_ans = data.get("answer", "").lower()
                        if "not possible" in lower_ans or "external" in lower_ans:
                            requirement.feasibility_classification = "existing_feature_limitation"
                            requirement.feasibility_evidence = f"Platform limitation documented: {top_source['title']} ({top_source['url']})"
                        else:
                            requirement.feasibility_classification = "existing_configuration"
                            requirement.feasibility_evidence = f"Supported via platform settings in {top_source['title']} ({top_source['url']})"
                    elif status == "insufficient_evidence" or confidence < 0.40:
                        requirement.feasibility_classification = "custom_development"
                        requirement.feasibility_evidence = "No native setting found in Knowledge Brain. Requires custom engineering implementation."
                    else:
                        requirement.feasibility_classification = "needs_clarification"
                        requirement.feasibility_evidence = "Partial documentation match. Further technical investigation recommended."
                else:
                    requirement.feasibility_classification = "custom_development"
                    requirement.feasibility_evidence = "Knowledge Brain check inconclusive. Defaulting to custom engineering estimate."
        except Exception as e:
            requirement.feasibility_classification = "custom_development"
            requirement.feasibility_evidence = f"Knowledge Brain offline: {str(e)}. Evaluated as custom engineering."

        return requirement

    def evaluate_all(self, requirements: List[Requirement]) -> List[Requirement]:
        return [self.check_feasibility(r) for r in requirements]

feasibility_agent = ProductFeasibilityAgent()
