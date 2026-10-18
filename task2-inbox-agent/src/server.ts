import express from "express";
import cors from "cors";
import * as path from "path";
import * as fs from "fs";
import { CustomerEmail, DraftResponse } from "./types";
import { emailClassifier } from "./classifier";
import { knowledgeClient } from "./knowledge-client";
import { responseDrafter } from "./drafter";
import { autonomyEngine } from "./autonomy";
import { feedbackManager } from "./feedback";

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Load 50-email dataset
const emailDatasetPath = path.join(__dirname, "../data/email-dataset.json");
let emailDataset: CustomerEmail[] = [];
if (fs.existsSync(emailDatasetPath)) {
  emailDataset = JSON.parse(fs.readFileSync(emailDatasetPath, "utf-8"));
}

app.get("/health", async (req, res) => {
  const kbHealth = await knowledgeClient.checkHealth();
  res.json({
    status: "ok",
    service: "Task 2 - Inbox Agent (TypeScript)",
    port: PORT,
    emailDatasetCount: emailDataset.length,
    knowledgeBrainStatus: kbHealth
  });
});

app.get("/emails", (req, res) => {
  const { category, search } = req.query;
  let filtered = [...emailDataset];

  if (category && typeof category === "string") {
    filtered = filtered.filter(e => e.expectedCategory === category);
  }
  if (search && typeof search === "string") {
    const s = search.toLowerCase();
    filtered = filtered.filter(e => e.subject.toLowerCase().includes(s) || e.body.toLowerCase().includes(s));
  }
  res.json({
    total: filtered.length,
    emails: filtered
  });
});

app.get("/emails/:id", (req, res) => {
  const found = emailDataset.find(e => e.id === req.params.id);
  if (!found) {
    return res.status(404).json({ error: "Email not found" });
  }
  res.json(found);
});

app.post("/process-email", async (req, res) => {
  try {
    const { emailId, rawEmail } = req.body;
    let email: CustomerEmail | undefined;

    if (emailId) {
      email = emailDataset.find(e => e.id === emailId);
    } else if (rawEmail) {
      email = rawEmail as CustomerEmail;
    }

    if (!email) {
      return res.status(400).json({ error: "Must provide valid emailId or rawEmail" });
    }

    // 1. Classify intent, urgency, and risk
    const classification = emailClassifier.classify(email);

    // 2. Fetch facts from Task 1 API (strictly over HTTP)
    const queryText = `${email.subject}. ${email.body.slice(0, 300)}`;
    const knowledgeResponse = await knowledgeClient.query(queryText, 4);

    // 3. Check autonomy eligibility
    const autonomyStatus = autonomyEngine.getStatus(classification.category);

    // 4. Draft structured response
    const draft = responseDrafter.generateDraft(
      email,
      classification,
      knowledgeResponse,
      autonomyStatus.isEligibleForAutonomy
    );

    res.json({
      email,
      classification,
      knowledgeResponse,
      draft,
      autonomyStatus
    });
  } catch (err: any) {
    res.status(500).json({ error: "Failed to process email", details: err.message });
  }
});

app.post("/review-draft", (req, res) => {
  try {
    const {
      emailId,
      predictedCategory,
      generatedDraft,
      humanEditedReply,
      approvalOutcome,
      reviewedBy,
      reviewReason
    } = req.body;

    const email = emailDataset.find(e => e.id === emailId) || {
      id: emailId || "custom",
      senderName: "Customer",
      senderEmail: "client@example.com",
      subject: "Inquiry",
      body: "",
      receivedAt: new Date().toISOString()
    };

    const record = feedbackManager.recordFeedback({
      email,
      predictedCategory: predictedCategory || "how_to",
      generatedDraft: generatedDraft || "",
      humanEditedReply,
      approvalOutcome: approvalOutcome || "approved",
      reviewedBy,
      reviewReason
    });

    const updatedAutonomy = autonomyEngine.getStatus(record.predictedCategory);

    res.json({
      status: "recorded",
      record,
      autonomyStatus: updatedAutonomy
    });
  } catch (err: any) {
    res.status(500).json({ error: "Failed to record review", details: err.message });
  }
});

app.get("/autonomy-status", (req, res) => {
  res.json({
    ruleDescription: "20 consecutive unedited approvals unlock autonomous sending for low-risk categories. High-risk categories remain permanently guarded.",
    statuses: autonomyEngine.getAllStatuses()
  });
});

app.get("/feedback-metrics", (req, res) => {
  const metrics = feedbackManager.getMetrics();
  const recentHistory = feedbackManager.getHistory(20);
  res.json({
    metrics,
    recentHistory
  });
});

app.listen(PORT, () => {
  console.log(`[Task 2: Inbox Agent] TypeScript API server running at http://127.0.0.1:${PORT}`);
});

export { app };
