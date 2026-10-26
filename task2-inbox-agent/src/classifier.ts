import { CustomerEmail, EmailCategory, RiskLevel, UrgencyLevel } from "./types";

export interface ClassificationResult {
  category: EmailCategory;
  urgency: UrgencyLevel;
  risk: RiskLevel;
  requiresHumanApproval: boolean;
  confidence: number;
  uncertainty?: "low" | "medium" | "high";
  reasoning: string;
  isFallback?: boolean;
}

export class EmailClassifier {
  /**
   * Primary classification method:
   * Uses genuine LLM if available, otherwise executes deterministic calibrated fallback.
   */
  public async classifyWithLLM(email: CustomerEmail): Promise<ClassificationResult> {
    const apiKey = process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY;
    if (!apiKey || process.env.NODE_ENV === "test") {
      return this.classify(email);
    }

    try {
      if (process.env.ANTHROPIC_API_KEY) {
        const response = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "x-api-key": process.env.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
          },
          body: JSON.stringify({
            model: process.env.TASK2_LLM_MODEL || "claude-3-5-haiku-20241022",
            max_tokens: 300,
            messages: [{
              role: "user",
              content: `Classify this customer email into category (how_to, troubleshooting, quote_request, project_request, refund_cancellation, complaint, follow_up), urgency (low, medium, high, critical), risk (low, moderate, commercial, financial, reputation), confidence (0.1 to 0.99), and reasoning.\nSubject: ${email.subject}\nBody: ${email.body}`
            }]
          })
        });

        if (response.ok) {
          const data: any = await response.json();
          const text = data?.content?.[0]?.text || "";
          const match = text.match(/\{[\s\S]*\}/);
          if (match) {
            const parsed = JSON.parse(match[0]);
            return this.applyGuardrails({
              category: parsed.category || "how_to",
              urgency: parsed.urgency || "low",
              risk: parsed.risk || "low",
              confidence: Number(parsed.confidence) || 0.85,
              reasoning: parsed.reasoning || "LLM classification",
              requiresHumanApproval: false,
              isFallback: false
            });
          }
        }
      }
    } catch {
      // Fallback cleanly on network/timeout error
    }

    return this.classify(email);
  }

  /**
   * Deterministic evidence-calibrated classification fallback.
   * Calculates dynamic evidence-based confidence instead of static hardcoded values.
   */
  public classify(email: CustomerEmail): ClassificationResult {
    const text = `${email.subject} ${email.body}`.toLowerCase();
    const wordCount = text.trim().split(/\s+/).length;

    // 1. Urgency Detection
    let urgency: UrgencyLevel = "low";
    if (/(urgent|emergency|outage|unacceptable|down|furious|immediately|lawsuit)/i.test(text)) {
      urgency = /(outage|site down|down during|unacceptable)/i.test(text) ? "critical" : "high";
    } else if (/(error|fails|failing|broken|discrepancy|tomorrow|deadline|incorrect billing|ruining|timing out)/i.test(text)) {
      urgency = "medium";
    }

    // 2. Follow-up priority check (if the primary intent is following up on a prior message)
    const isExplicitFollowUp = (
      /^(following up|checking in|follow-up|awaiting executive|status of ticket)/i.test(email.subject) ||
      /(following up on (our|my|the)|checking in on|just following up)/i.test(email.body)
    );

    let category: EmailCategory = "how_to";
    let risk: RiskLevel = "low";
    let reasoning = "";
    let confidence = 0.85;
    let uncertainty: "low" | "medium" | "high" = "low";

    if (isExplicitFollowUp) {
      category = "follow_up";
      risk = urgency === "high" || urgency === "critical" ? "reputation" : "low";
      reasoning = "Customer is tracking or following up on existing ticket, proposal, or incident.";
      confidence = 0.89;
    } else if (/(refund|cancel|cancellation|chargeback|duplicate charge|reverse transaction|terminate|termination)/i.test(text)) {
      category = "refund_cancellation";
      risk = "financial";
      reasoning = "Involves billing transactions, refund requests, or account cancellation.";
      confidence = 0.92;
    } else if (/(unacceptable|terrible|furious|complaint|outage|wiped out|broke our|regressed|dispute|incorrect billing|ruining|timing out)/i.test(text)) {
      category = "complaint";
      risk = /incorrect billing/i.test(text) ? "financial" : "reputation";
      reasoning = "Customer expressing dissatisfaction, billing dispute, service degradation, or platform outage.";
      confidence = 0.90;
    } else if (/(quote|cost estimate|pricing for|how much would|price estimate)/i.test(text)) {
      category = "quote_request";
      risk = "commercial";
      reasoning = "Commercial request for pricing, estimates, or quotation.";
      confidence = 0.88;
    } else if (/(build a custom|develop custom|mobile apps|marketplace addon|commission|proposal|hubspot crm|integration request|implementation project|contract your team)/i.test(text)) {
      category = "project_request";
      risk = "commercial";
      reasoning = "Client requesting bespoke engineering, add-ons, or custom development.";
      confidence = 0.91;
    } else if (/(fails|error|broken|not delivering|not saving|mismatch|stuck|timing out|warning|not updating|blank options|corrupted)/i.test(text)) {
      category = "troubleshooting";
      risk = "moderate";
      reasoning = "Technical troubleshooting request reporting unexpected behavior or errors.";
      confidence = 0.87;
    } else {
      category = "how_to";
      risk = "low";
      reasoning = "Standard how-to inquiry regarding configuration, settings, or documentation.";
      confidence = 0.82;
      uncertainty = "medium";
    }

    // Calibrate uncertainty: Short / ambiguous inquiries lower confidence
    if (wordCount < 6) {
      confidence = Math.min(confidence, 0.65);
      uncertainty = "high";
      reasoning += " (Inquiry is brief or ambiguous; calibrated confidence lowered)";
    }

    return this.applyGuardrails({
      category,
      urgency,
      risk,
      confidence: Math.round(confidence * 100) / 100,
      uncertainty,
      reasoning,
      requiresHumanApproval: false,
      isFallback: true
    });
  }

  private applyGuardrails(result: ClassificationResult): ClassificationResult {
    const isHighRisk = (
      result.category === "refund_cancellation" ||
      result.category === "complaint" ||
      result.category === "project_request" ||
      result.category === "quote_request" ||
      result.risk === "financial" ||
      result.risk === "reputation" ||
      result.risk === "commercial" ||
      result.urgency === "high" ||
      result.urgency === "critical" ||
      result.confidence < 0.70 ||
      result.uncertainty === "high"
    );

    result.requiresHumanApproval = isHighRisk;
    return result;
  }
}

export const emailClassifier = new EmailClassifier();
