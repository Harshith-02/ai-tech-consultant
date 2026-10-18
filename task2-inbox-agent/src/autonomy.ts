import { CategoryAutonomyStatus, EmailCategory } from "./types";
import * as fs from "fs";
import * as path from "path";

const PERMANENTLY_GUARDED_CATEGORIES: Set<EmailCategory> = new Set([
  "refund_cancellation",
  "complaint",
  "project_request",
  "quote_request"
]);

export class AutonomyEngine {
  private statusFilePath: string;
  private statusMap: Map<EmailCategory, CategoryAutonomyStatus>;

  constructor(storageDir: string = path.join(__dirname, "../data")) {
    this.statusFilePath = path.join(storageDir, "autonomy-status.json");
    this.statusMap = new Map();
    this.init();
  }

  private init() {
    const allCategories: EmailCategory[] = [
      "how_to",
      "troubleshooting",
      "project_request",
      "refund_cancellation",
      "complaint",
      "quote_request",
      "follow_up"
    ];

    if (fs.existsSync(this.statusFilePath)) {
      try {
        const raw = fs.readFileSync(this.statusFilePath, "utf-8");
        const data = JSON.parse(raw);
        for (const cat of allCategories) {
          if (data[cat]) {
            this.statusMap.set(cat, data[cat]);
          }
        }
      } catch (e) {
        // Fall back to defaults
      }
    }

    // Ensure all categories exist
    const now = new Date().toISOString();
    for (const cat of allCategories) {
      if (!this.statusMap.has(cat)) {
        const isGuarded = PERMANENTLY_GUARDED_CATEGORIES.has(cat);
        this.statusMap.set(cat, {
          category: cat,
          consecutiveUneditedCount: 0,
          isEligibleForAutonomy: false,
          isPermanentlyGuarded: isGuarded,
          lastResetReason: undefined,
          updatedAt: now
        });
      }
    }
    this.persist();
  }

  private persist() {
    try {
      const obj: Record<string, CategoryAutonomyStatus> = {};
      this.statusMap.forEach((v, k) => {
        obj[k] = v;
      });
      const dir = path.dirname(this.statusFilePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(this.statusFilePath, JSON.stringify(obj, null, 2), "utf-8");
    } catch (e) {
      console.error("Failed to persist autonomy status:", e);
    }
  }

  public getStatus(category: EmailCategory): CategoryAutonomyStatus {
    return this.statusMap.get(category)!;
  }

  public getAllStatuses(): CategoryAutonomyStatus[] {
    return Array.from(this.statusMap.values());
  }

  public recordReviewOutcome(
    category: EmailCategory,
    wasModified: boolean,
    outcome: "approved" | "edited" | "rejected" | "escalated",
    reason?: string
  ): CategoryAutonomyStatus {
    const status = this.statusMap.get(category)!;
    const now = new Date().toISOString();

    if (status.isPermanentlyGuarded) {
      // Guarded categories (refunds, complaints, commercial quotes) are locked from autonomous send
      status.consecutiveUneditedCount = 0;
      status.isEligibleForAutonomy = false;
      status.lastResetReason = "Safety Lock: Category is permanently guarded against autonomous sending.";
      status.updatedAt = now;
      this.persist();
      return status;
    }

    if (outcome === "approved" && !wasModified) {
      // Unedited approval increments streak
      status.consecutiveUneditedCount += 1;
      if (status.consecutiveUneditedCount >= 20) {
        status.isEligibleForAutonomy = true;
      }
    } else {
      // Any human edit, rejection, or escalation breaks the streak!
      const priorCount = status.consecutiveUneditedCount;
      status.consecutiveUneditedCount = 0;
      status.isEligibleForAutonomy = false;
      status.lastResetReason = outcome === "rejected"
        ? `Draft rejected by human reviewer (broke streak of ${priorCount}). Reason: ${reason || 'Unspecified'}`
        : `Human reviewer modified draft text before sending (broke streak of ${priorCount}).`;
    }

    status.updatedAt = now;
    this.persist();
    return status;
  }

  public calculateEditDistanceRatio(originalText: string, editedText: string): number {
    const cleanOrig = originalText.trim().replace(/\r\n/g, "\n");
    const cleanEdit = editedText.trim().replace(/\r\n/g, "\n");
    
    if (cleanOrig === cleanEdit) return 0.0;
    if (!cleanOrig || !cleanEdit) return 1.0;

    // Simple Levenshtein approximation for speed on large email bodies
    const lenA = cleanOrig.length;
    const lenB = cleanEdit.length;
    const maxLen = Math.max(lenA, lenB);
    
    // Quick diff sampling
    let diffChars = Math.abs(lenA - lenB);
    const minLen = Math.min(lenA, lenB);
    for (let i = 0; i < minLen; i++) {
      if (cleanOrig[i] !== cleanEdit[i]) {
        diffChars++;
      }
    }
    return Math.min(1.0, diffChars / maxLen);
  }
}

export const autonomyEngine = new AutonomyEngine();
