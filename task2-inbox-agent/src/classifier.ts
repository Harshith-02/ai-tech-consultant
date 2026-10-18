import { CustomerEmail, EmailCategory, RiskLevel, UrgencyLevel } from "./types";

export interface ClassificationResult {
  category: EmailCategory;
  urgency: UrgencyLevel;
  risk: RiskLevel;
  requiresHumanApproval: boolean;
  confidence: number;
  reasoning: string;
}

export class EmailClassifier {
  public classify(email: CustomerEmail): ClassificationResult {
    const text = `${email.subject} ${email.body}`.toLowerCase();

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

    if (isExplicitFollowUp) {
      category = "follow_up";
      risk = urgency === "high" || urgency === "critical" ? "reputation" : "low";
      reasoning = "Customer is tracking or following up on existing ticket, proposal, or incident.";
    } else if (/(refund|cancel|cancellation|chargeback|duplicate charge|reverse transaction|terminate|termination)/i.test(text)) {
      category = "refund_cancellation";
      risk = "financial";
      reasoning = "Involves billing transactions, refund requests, or account cancellation.";
    } else if (/(unacceptable|terrible|furious|complaint|outage|wiped out|broke our|regressed|dispute|incorrect billing|ruining|timing out)/i.test(text)) {
      category = "complaint";
      risk = /incorrect billing/i.test(text) ? "financial" : "reputation";
      reasoning = "Customer expressing dissatisfaction, billing dispute, service degradation, or platform outage.";
    } else if (/(quote|cost estimate|pricing for|how much would|price estimate)/i.test(text)) {
      category = "quote_request";
      risk = "commercial";
      reasoning = "Commercial request for pricing, estimates, or quotation.";
    } else if (/(build a custom|develop custom|mobile apps|marketplace addon|commission|proposal|hubspot crm|integration request|implementation project|contract your team)/i.test(text)) {
      category = "project_request";
      risk = "commercial";
      reasoning = "Client requesting bespoke engineering, add-ons, or custom development.";
    } else if (/(fails|error|broken|not delivering|not saving|mismatch|stuck|timing out|warning|not updating|blank options|corrupted)/i.test(text)) {
      category = "troubleshooting";
      risk = "moderate";
      reasoning = "Technical troubleshooting request reporting unexpected behavior or errors.";
    } else {
      category = "how_to";
      risk = "low";
      reasoning = "Standard how-to inquiry regarding configuration, settings, or documentation.";
    }

    // Guardrail rule: Financial, commercial, legal, and reputation risks MUST require human review
    const requiresHumanApproval = (
      category === "refund_cancellation" ||
      category === "complaint" ||
      category === "project_request" ||
      category === "quote_request" ||
      risk === "financial" ||
      risk === "reputation" ||
      risk === "commercial" ||
      urgency === "high" ||
      urgency === "critical"
    );

    return {
      category,
      urgency,
      risk,
      requiresHumanApproval,
      confidence: 0.94,
      reasoning
    };
  }
}

export const emailClassifier = new EmailClassifier();
