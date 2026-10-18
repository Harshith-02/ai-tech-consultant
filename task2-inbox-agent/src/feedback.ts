import { FeedbackRecord, CustomerEmail, EmailCategory, ApprovalOutcome } from "./types";
import { autonomyEngine } from "./autonomy";
import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";

export class FeedbackManager {
  private historyFilePath: string;
  private history: FeedbackRecord[];

  constructor(storageDir: string = path.join(__dirname, "../data")) {
    this.historyFilePath = path.join(storageDir, "feedback-history.json");
    this.history = [];
    this.init();
  }

  private init() {
    if (fs.existsSync(this.historyFilePath)) {
      try {
        const raw = fs.readFileSync(this.historyFilePath, "utf-8");
        this.history = JSON.parse(raw);
      } catch (e) {
        this.history = [];
      }
    }
  }

  private persist() {
    try {
      const dir = path.dirname(this.historyFilePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(this.historyFilePath, JSON.stringify(this.history, null, 2), "utf-8");
    } catch (e) {
      console.error("Failed to persist feedback history:", e);
    }
  }

  public recordFeedback(params: {
    email: CustomerEmail;
    predictedCategory: EmailCategory;
    generatedDraft: string;
    humanEditedReply?: string;
    approvalOutcome: ApprovalOutcome;
    reviewedBy?: string;
    reviewReason?: string;
    promptVersion?: string;
    modelVersion?: string;
  }): FeedbackRecord {
    const finalSent = params.humanEditedReply && params.humanEditedReply.trim()
      ? params.humanEditedReply.trim()
      : params.generatedDraft.trim();

    const editDistance = autonomyEngine.calculateEditDistanceRatio(
      params.generatedDraft,
      finalSent
    );
    const wasModified = editDistance > 0.05 || params.approvalOutcome === "edited";

    const record: FeedbackRecord = {
      id: `FB-${crypto.randomBytes(4).toString("hex").toUpperCase()}`,
      emailId: params.email.id,
      originalEmail: params.email,
      predictedCategory: params.predictedCategory,
      generatedDraft: params.generatedDraft,
      humanEditedReply: params.humanEditedReply,
      finalSentReply: finalSent,
      approvalOutcome: params.approvalOutcome,
      wasModified,
      editDistanceScore: Math.round(editDistance * 100) / 100,
      modelVersion: params.modelVersion || "claude-3-5-sonnet-20241022",
      promptVersion: params.promptVersion || "v1.2",
      reviewedBy: params.reviewedBy || "Support Supervisor",
      reviewReason: params.reviewReason,
      timestamp: new Date().toISOString()
    };

    this.history.unshift(record);
    this.persist();

    // Update 20-send autonomy tracker
    autonomyEngine.recordReviewOutcome(
      params.predictedCategory,
      wasModified,
      params.approvalOutcome,
      params.reviewReason
    );

    return record;
  }

  public getHistory(limit: number = 50): FeedbackRecord[] {
    return this.history.slice(0, limit);
  }

  public getMetrics(): {
    totalInteractions: number;
    approvedCount: number;
    editedCount: number;
    rejectedCount: number;
    escalatedCount: number;
    approvalRatePct: number;
    editRatePct: number;
    averageEditDistance: number;
  } {
    const total = this.history.length;
    if (total === 0) {
      return {
        totalInteractions: 0,
        approvedCount: 0,
        editedCount: 0,
        rejectedCount: 0,
        escalatedCount: 0,
        approvalRatePct: 0,
        editRatePct: 0,
        averageEditDistance: 0
      };
    }

    const approved = this.history.filter(h => h.approvalOutcome === "approved").length;
    const edited = this.history.filter(h => h.approvalOutcome === "edited" || h.wasModified).length;
    const rejected = this.history.filter(h => h.approvalOutcome === "rejected").length;
    const escalated = this.history.filter(h => h.approvalOutcome === "escalated").length;
    const totalEditDist = this.history.reduce((sum, h) => sum + h.editDistanceScore, 0);

    return {
      totalInteractions: total,
      approvedCount: approved,
      editedCount: edited,
      rejectedCount: rejected,
      escalatedCount: escalated,
      approvalRatePct: Math.round((approved / total) * 1000) / 10,
      editRatePct: Math.round((edited / total) * 1000) / 10,
      averageEditDistance: Math.round((totalEditDist / total) * 100) / 100
    };
  }
}

export const feedbackManager = new FeedbackManager();
