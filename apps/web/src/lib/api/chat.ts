import {
  API_BASE_URL,
  ApiError,
  errorMessage,
  parseResponse,
} from "./http";

import type {
  ChatRequest,
  ChatStreamHandlers,
  EvidenceRef,
} from "../api";

export const chatApi = {
  stream: async (
    payload: ChatRequest,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> => {
    const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      body: JSON.stringify(payload),
      credentials: "include",
      headers: {"content-type": "application/json"},
      signal,
    });
    if (!response.ok) {
      const errorPayload = await parseResponse(response);
      throw new ApiError(response.status, errorMessage(response.status, errorPayload), errorPayload);
    }
    if (!response.body) {
      throw new Error("Streaming response body is unavailable");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, {stream: true});
      buffer = dispatchSseFrames(buffer, handlers);
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      dispatchSseFrame(buffer, handlers);
    }
  },
};

function dispatchSseFrames(buffer: string, handlers: ChatStreamHandlers): string {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  const remainder = frames.pop() || "";
  for (const frame of frames) {
    dispatchSseFrame(frame, handlers);
  }
  return remainder;
}

function dispatchSseFrame(frame: string, handlers: ChatStreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      const data = line.slice(5);
      dataLines.push(data.startsWith(" ") ? data.slice(1) : data);
    }
  }
  if (dataLines.length === 0) {
    return;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(dataLines.join("\n"));
  } catch {
    parsed = {};
  }
  if (!parsed || typeof parsed !== "object") {
    return;
  }
  const payload = parsed as Record<string, unknown>;

  if (event === "delta" && typeof payload.delta === "string") {
    handlers.delta?.(payload.delta);
  } else if (event === "evidence" && Array.isArray(payload.evidence_refs)) {
    handlers.evidence?.(payload.evidence_refs as EvidenceRef[]);
  } else if (event === "done" && typeof payload.message === "string") {
    handlers.done?.(payload.message);
  } else if (event === "error" && typeof payload.message === "string") {
    handlers.error?.(payload.message);
  }
}
