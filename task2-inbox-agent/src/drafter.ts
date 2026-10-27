import { CustomerEmail, DraftResponse, KnowledgeApiResponse } from "./types";
import { ClassificationResult } from "./classifier";

const LEAK_PATTERNS = [
  /\*\(💡\s*AI Learning Engine Applied.*?\)\*/gi,
  /AI Learning Engine Applied/gi,
  /supervisor edit:/gi,
  /FEEDBACK_RULES?/gi,
  /internal reasoning:/gi,
  /system prompt:/gi,
  /requiresHumanApproval/gi
];

export function sanitizeCustomerReply(replyText: string): string {
  if (!replyText) return "";
  let sanitized = replyText;
  for (const pat of LEAK_PATTERNS) {
    sanitized = sanitized.replace(pat, "");
  }
  return sanitized.replace(/\n{3,}/g, "\n\n").trim();
}

export class ResponseDrafter {
  /**
   * Primary LLM reply generator if provider is configured, falling back to grounded extractive generation.
   */
  public async generateDraftWithLLM(
    email: CustomerEmail,
    classification: ClassificationResult,
    knowledge: KnowledgeApiResponse,
    isAutonomousEligible: boolean = false,
    feedbackRule?: string
  ): Promise<DraftResponse> {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey || process.env.NODE_ENV === "test") {
      return this.generateDraft(email, classification, knowledge, isAutonomousEligible, feedbackRule);
    }

    try {
      const topDocs = (knowledge.sources || []).map(s => `Title: ${s.title}\nURL: ${s.url}\nContent: ${s.snippet}`).join("\n\n");
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "content-type": "application/json"
        },
        body: JSON.stringify({
          model: process.env.TASK2_LLM_MODEL || "claude-3-5-haiku-20241022",
          max_tokens: 500,
          system: "You are a customer support agent. Answer strictly using facts in the provided documentation. Never fabricate policies. Do not include internal feedback rules, supervisor notes, or internal reasoning in the reply body.",
          messages: [{
            role: "user",
            content: `Customer: ${email.senderName}\nSubject: ${email.subject}\nInquiry: ${email.body}\n\nEvidence Documents:\n${topDocs}`
          }]
        })
      });

      if (res.ok) {
        const data: any = await res.json();
        const rawText = data?.content?.[0]?.text || "";
        const cleanReply = sanitizeCustomerReply(rawText);
        if (cleanReply) {
          const canSendAutonomously = isAutonomousEligible && !classification.requiresHumanApproval;
          return {
            emailId: email.id,
            category: classification.category,
            urgency: classification.urgency,
            risk: classification.risk,
            summary: `LLM grounded draft response for ${email.senderName}`,
            suggestedReply: cleanReply,
            citations: knowledge.sources,
            requiresHumanApproval: !canSendAutonomously,
            recommendedNextAction: canSendAutonomously ? "Autonomous send eligible" : "Review and approve draft reply",
            autonomousEligible: canSendAutonomously,
            confidence: knowledge.confidence > 0 ? knowledge.confidence : 0.88
          };
        }
      }
    } catch {
      // Clean fallback on provider failure
    }

    return this.generateDraft(email, classification, knowledge, isAutonomousEligible, feedbackRule);
  }

  /**
   * Deterministic grounded response drafter.
   * NEVER appends internal learning notes or supervisor feedback to suggestedReply.
   */
  public generateDraft(
    email: CustomerEmail,
    classification: ClassificationResult,
    knowledge: KnowledgeApiResponse,
    isAutonomousEligible: boolean = false,
    _feedbackRule?: string
  ): DraftResponse {
    const sender = email.senderName || "Valued Customer";
    const firstName = sender.split(" ")[0];
    
    let suggestedReply = "";
    let recommendedNextAction = "";
    let summary = "";

    switch (classification.category) {
      case "how_to":
      case "troubleshooting": {
        summary = `Customer asked: ${email.subject}.`;
        if (knowledge.status === "answered" && knowledge.sources.length > 0) {
          const topSource = knowledge.sources[0];
          const screenshotNote = topSource.image_description
            ? `\n\nVisual Reference:\n${topSource.image_description}`
            : "";

          suggestedReply = (
            `Hi ${firstName},\n\n` +
            `Thank you for reaching out to support.\n\n` +
            `${knowledge.answer}\n` +
            `${screenshotNote}\n\n` +
            `You can also review the complete step-by-step documentation here: ${topSource.url}\n\n` +
            `Please let us know if you run into any questions as you set this up!\n\n` +
            `Best regards,\n` +
            `Support Operations Team`
          );
          recommendedNextAction = "Send reply to customer; close ticket if no follow-up needed.";
        } else {
          suggestedReply = (
            `Hi ${firstName},\n\n` +
            `Thank you for contacting us regarding ${email.subject}.\n\n` +
            `To ensure we provide the most accurate resolution for your specific directory setup, I have flagged this ticket for our senior product specialist who is reviewing the configuration details.\n\n` +
            `We will follow up with verified guidance shortly.\n\n` +
            `Best regards,\n` +
            `Support Operations Team`
          );
          recommendedNextAction = "Escalate ticket to Tier-2 product specialist.";
        }
        break;
      }

      case "project_request": {
        summary = `Client submitted custom development inquiry: ${email.subject}.`;
        suggestedReply = (
          `Hi ${firstName},\n\n` +
          `Thank you for considering our team for your custom project!\n\n` +
          `We would be delighted to help explore the architectural requirements for ${email.subject.toLowerCase()}.\n\n` +
          `Our technical consulting team typically begins with a brief discovery meeting to review existing platform capabilities, outline technical feasibility, and prepare an itemized Scope of Work and estimate.\n\n` +
          `Would you have 20 minutes available later this week for an initial discussion?\n\n` +
          `Looking forward to collaborating,\n` +
          `AI Tech Consulting Team`
        );
        recommendedNextAction = "Schedule technical scoping call with solutions architect.";
        break;
      }

      case "quote_request": {
        summary = `Client requested commercial quotation: ${email.subject}.`;
        suggestedReply = (
          `Hi ${firstName},\n\n` +
          `Thank you for your interest in our consulting and implementation services.\n\n` +
          `We are reviewing the requirements outlined in your inquiry regarding "${email.subject}". To deliver an accurate, fixed-price proposal, our engineering team is verifying the data structures and necessary integrations.\n\n` +
          `We will prepare a formal scope and pricing breakdown for your review within 24 business hours.\n\n` +
          `Best regards,\n` +
          `Commercial Solutions Team`
        );
        recommendedNextAction = "Run Task 3 Meeting-to-Scope pipeline to generate itemized estimate.";
        break;
      }

      case "refund_cancellation": {
        summary = `Customer requested billing action / refund: ${email.subject}.`;
        suggestedReply = (
          `Hi ${firstName},\n\n` +
          `Thank you for contacting our accounts department regarding your request (${email.subject}).\n\n` +
          `I have received your inquiry and submitted your account details directly to our billing supervisor for immediate review in accordance with our terms of service and satisfaction guarantee.\n\n` +
          `You will receive a formal confirmation along with the transaction reference once the review is finalized today.\n\n` +
          `Sincerely,\n` +
          `Billing & Accounts Team`
        );
        recommendedNextAction = "Route ticket to human billing supervisor for refund authorization. DO NOT auto-send.";
        break;
      }

      case "complaint": {
        summary = `Customer escalation / service complaint: ${email.subject}.`;
        suggestedReply = (
          `Hi ${firstName},\n\n` +
          `I am truly sorry to hear about your experience regarding ${email.subject.toLowerCase()}.\n\n` +
          `We understand the critical importance of your directory's uptime and reliability, and we take this situation very seriously. I have escalated this issue directly to our lead engineering director for immediate investigation.\n\n` +
          `A member of our leadership team will follow up directly with a full incident report and status update.\n\n` +
          `Sincerely,\n` +
          `Executive Support Team`
        );
        recommendedNextAction = "High-priority leadership escalation. Human manager intervention required.";
        break;
      }

      case "follow_up": {
        summary = `Customer following up on previous correspondence: ${email.subject}.`;
        suggestedReply = (
          `Hi ${firstName},\n\n` +
          `Thank you for following up with us.\n\n` +
          `We have your previous notes on file and our technical team is currently actively working on the requested items. We will provide a comprehensive progress update shortly.\n\n` +
          `Thank you for your patience,\n` +
          `Client Success Team`
        );
        recommendedNextAction = "Check ongoing ticket status and synchronize with assignee.";
        break;
      }
    }

    // Determine autonomy eligibility
    // Must be unedited-category eligible, AND must NOT have financial, commercial, or reputation risk!
    const canSendAutonomously = isAutonomousEligible && !classification.requiresHumanApproval;
    const cleanReply = sanitizeCustomerReply(suggestedReply);

    return {
      emailId: email.id,
      category: classification.category,
      urgency: classification.urgency,
      risk: classification.risk,
      summary,
      suggestedReply: cleanReply,
      citations: knowledge.sources,
      requiresHumanApproval: !canSendAutonomously,
      recommendedNextAction,
      autonomousEligible: canSendAutonomously,
      confidence: knowledge.confidence > 0 ? knowledge.confidence : 0.88
    };
  }
}

export const responseDrafter = new ResponseDrafter();
