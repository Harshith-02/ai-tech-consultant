import { KnowledgeApiResponse } from "./types";

export class KnowledgeBrainClient {
  private baseUrl: string;
  private timeoutMs: number;

  constructor(baseUrl: string = process.env.TASK1_API_URL || "http://127.0.0.1:8000", timeoutMs: number = 8000) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
  }

  public async query(question: string, topK: number = 4): Promise<KnowledgeApiResponse> {
    const endpoint = `${this.baseUrl}/query`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-Client-Service": "Inbox-Agent-Task2"
        },
        body: JSON.stringify({
          question: question,
          top_k: topK
        }),
        signal: controller.signal
      });

      clearTimeout(timeout);

      if (!response.ok) {
        const errorText = await response.text();
        return {
          answer: `Knowledge service returned status ${response.status}: ${errorText}`,
          status: "insufficient_evidence",
          sources: [],
          confidence: 0.0,
          needs_human: true,
          escalation_id: null
        };
      }

      const data = await response.json() as KnowledgeApiResponse;
      return data;
    } catch (err: any) {
      clearTimeout(timeout);
      const isTimeout = err.name === "AbortError";
      return {
        answer: isTimeout
          ? "The Knowledge Brain request timed out. Routing directly to support engineer for review."
          : `Failed to connect to Knowledge Brain API (${this.baseUrl}): ${err.message}`,
        status: "insufficient_evidence",
        sources: [],
        confidence: 0.0,
        needs_human: true,
        escalation_id: null
      };
    }
  }

  public async checkHealth(): Promise<{ ok: boolean; message: string }> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.ok) {
        const data = await response.json();
        return { ok: true, message: `Knowledge Brain operational (v${data.version}, ${data.indexed_articles} articles)` };
      }
      return { ok: false, message: `Knowledge Brain returned status ${response.status}` };
    } catch (e: any) {
      return { ok: false, message: `Knowledge Brain unreachable: ${e.message}` };
    }
  }
}

export const knowledgeClient = new KnowledgeBrainClient();
