import { z } from "zod";

export const EmailCategorySchema = z.enum([
  "how_to",
  "troubleshooting",
  "project_request",
  "refund_cancellation",
  "complaint",
  "quote_request",
  "follow_up"
]);
export type EmailCategory = z.infer<typeof EmailCategorySchema>;

export const UrgencyLevelSchema = z.enum(["low", "medium", "high", "critical"]);
export type UrgencyLevel = z.infer<typeof UrgencyLevelSchema>;

export const RiskLevelSchema = z.enum(["low", "moderate", "commercial", "financial", "reputation"]);
export type RiskLevel = z.infer<typeof RiskLevelSchema>;

export interface CustomerEmail {
  id: string;
  senderName: string;
  senderEmail: string;
  subject: string;
  body: string;
  receivedAt: string;
  expectedCategory?: EmailCategory;
  expectedRisk?: RiskLevel;
  expectedUrgency?: UrgencyLevel;
}

export interface KnowledgeCitation {
  title: string;
  url: string;
  section: string;
  relevance: number;
  image_url?: string | null;
  image_description?: string | null;
  snippet: string;
}

export interface KnowledgeApiResponse {
  answer: string;
  status: "answered" | "insufficient_evidence" | "escalated";
  sources: KnowledgeCitation[];
  confidence: number;
  needs_human: boolean;
  escalation_id?: string | null;
}

export const DraftResponseSchema = z.object({
  emailId: z.string(),
  category: EmailCategorySchema,
  urgency: UrgencyLevelSchema,
  risk: RiskLevelSchema,
  summary: z.string(),
  suggestedReply: z.string(),
  citations: z.array(z.object({
    title: z.string(),
    url: z.string(),
    section: z.string(),
    relevance: z.number(),
    image_url: z.string().nullable().optional(),
    image_description: z.string().nullable().optional(),
    snippet: z.string()
  })),
  requiresHumanApproval: z.boolean(),
  recommendedNextAction: z.string(),
  autonomousEligible: z.boolean(),
  confidence: z.number()
});
export type DraftResponse = z.infer<typeof DraftResponseSchema>;

export type ApprovalOutcome = "approved" | "edited" | "rejected" | "escalated";

export interface FeedbackRecord {
  id: string;
  emailId: string;
  originalEmail: CustomerEmail;
  predictedCategory: EmailCategory;
  generatedDraft: string;
  humanEditedReply?: string;
  finalSentReply: string;
  approvalOutcome: ApprovalOutcome;
  wasModified: boolean;
  editDistanceScore: number; // 0.0 (identical) to 1.0 (completely rewritten)
  modelVersion: string;
  promptVersion: string;
  reviewedBy: string;
  reviewReason?: string;
  timestamp: string;
}

export interface CategoryAutonomyStatus {
  category: EmailCategory;
  consecutiveUneditedCount: number;
  isEligibleForAutonomy: boolean;
  isPermanentlyGuarded: boolean; // Safety guardrail (e.g. refunds, cancellations, complaints)
  lastResetReason?: string;
  updatedAt: string;
}
