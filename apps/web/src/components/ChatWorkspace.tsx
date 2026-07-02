"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import type { AnalysisRunResponse, EvidenceRef } from "@/lib/api";
import { chatApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { EvidenceChip } from "@/components/Evidence";
import { MarkdownMessage } from "@/components/MarkdownMessage";
import { Button, Card, EmptyState } from "@/components/ui";

interface ChatWorkspaceProps {
  caseId: string;
  run: AnalysisRunResponse | null;
  onEvidenceSelect?: (ref: EvidenceRef) => void;
}

type ChatRole = "user" | "assistant";
type ChatMessageStatus = "complete" | "streaming" | "error" | "cancelled";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  evidenceRefs: EvidenceRef[];
  status: ChatMessageStatus;
  createdAt: number;
}

const QUICK_PROMPTS = [
  "Summarize what changed and why it matters",
  "What is the most likely root cause?",
  "Show the strongest evidence",
  "Draft a customer-safe update",
];

function makeId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function messageStatusLabel(status: ChatMessageStatus): string | null {
  if (status === "streaming") return "Streaming response";
  if (status === "error") return "Response error";
  if (status === "cancelled") return "Cancelled";
  return null;
}

export function ChatWorkspace({ caseId, onEvidenceSelect, run }: ChatWorkspaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function updateMessage(
    messageId: string,
    updater: (message: ChatMessage) => ChatMessage,
  ) {
    setMessages((current) =>
      current.map((message) => (message.id === messageId ? updater(message) : message)),
    );
  }

  async function sendMessage(prompt?: string) {
    const question = (prompt ?? input).trim();
    if (!run) {
      setError("Start an analysis run before asking LogAn AI.");
      return;
    }
    if (!question || streamingMessageId) {
      return;
    }

    const controller = new AbortController();
    const assistantId = makeId("assistant");
    abortRef.current = controller;
    setError(null);
    setInput("");
    setStreamingMessageId(assistantId);
    setMessages((current) => [
      ...current,
      {
        id: makeId("user"),
        role: "user",
        content: question,
        evidenceRefs: [],
        status: "complete",
        createdAt: Date.now(),
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        evidenceRefs: [],
        status: "streaming",
        createdAt: Date.now(),
      },
    ]);

    try {
      await chatApi.stream(
        {
          message: question,
          case_id: caseId,
          analysis_run_id: run.analysis_run_id,
        },
        {
          delta: (delta) => {
            updateMessage(assistantId, (message) => ({
              ...message,
              content: `${message.content}${delta}`,
            }));
          },
          evidence: (evidenceRefs) => {
            updateMessage(assistantId, (message) => ({ ...message, evidenceRefs }));
          },
          done: (doneMessage) => {
            updateMessage(assistantId, (message) => ({
              ...message,
              content: message.content || doneMessage,
              status: "complete",
            }));
          },
          error: (messageText) => {
            setError(messageText);
            updateMessage(assistantId, (message) => ({
              ...message,
              content: message.content ? `${message.content}\n${messageText}` : messageText,
              status: "error",
            }));
          },
        },
        controller.signal,
      );
    } catch (caught) {
      if (isAbortError(caught)) {
        updateMessage(assistantId, (message) => ({
          ...message,
          content: message.content || "Cancelled.",
          status: "cancelled",
        }));
      } else {
        const messageText = apiErrorMessage(caught);
        setError(messageText);
        updateMessage(assistantId, (message) => ({
          ...message,
          content: message.content || messageText,
          status: "error",
        }));
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      setStreamingMessageId(null);
    }
  }

  function cancel() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreamingMessageId(null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  const composerDisabled = !run || Boolean(streamingMessageId);

  return (
    <Card sx={{ background: "linear-gradient(180deg, #ffffff, rgba(230,225,255,0.26))" }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
          <Box
            sx={{
              alignItems: "center",
              background: "linear-gradient(135deg, #5b5cf6, #06b6d4)",
              borderRadius: "50%",
              boxShadow: "0 14px 28px rgba(91,92,246,0.22)",
              color: "#ffffff",
              display: "flex",
              flex: "0 0 auto",
              fontWeight: 900,
              height: 46,
              justifyContent: "center",
              width: 46,
            }}
          >
            AI
          </Box>
          <Box>
            <Typography color="primary" sx={{ fontWeight: 850, letterSpacing: 0.5, textTransform: "uppercase" }} variant="caption">
              AI Analyst
            </Typography>
            <Typography component="h2" sx={{ fontWeight: 900 }} variant="h6">
              Analysis Chat
            </Typography>
          </Box>
        </Stack>

        {messages.length === 0 && (
          <Stack spacing={1.5}>
            <EmptyState
              icon={
                <Box component="span" sx={{ fontSize: 13, fontWeight: 900 }}>
                  AI
                </Box>
              }
              title="Ask about this incident"
            >
              Ask about symptoms, timelines, evidence, likely root cause, and next actions. AI Analyst supports tables, lists, and code blocks.
            </EmptyState>
            <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
              {QUICK_PROMPTS.map((prompt) => (
                <Button
                  disabled={!run || Boolean(streamingMessageId)}
                  key={prompt}
                  size="sm"
                  variant="ghost"
                  onClick={() => void sendMessage(prompt)}
                >
                  {prompt}
                </Button>
              ))}
            </Stack>
          </Stack>
        )}

        {messages.length > 0 && (
          <Stack
            ref={scrollRef}
            spacing={2}
            sx={{
              border: 1,
              borderColor: "rgba(91,92,246,0.12)",
              borderRadius: "14px",
              bgcolor: "rgba(255,255,255,0.72)",
              maxHeight: 520,
              minHeight: 320,
              overflowY: "auto",
              p: 2,
            }}
          >
            {messages.map((message) => {
              const isUser = message.role === "user";
              const statusLabel = messageStatusLabel(message.status);
              return (
                <Stack
                  component="article"
                  key={message.id}
                  spacing={0.75}
                  sx={{ alignItems: isUser ? "flex-end" : "flex-start" }}
                >
                  <Typography
                    color={isUser ? "text.secondary" : "primary"}
                    sx={{ fontWeight: 800 }}
                    variant="caption"
                  >
                    {isUser ? "You" : "AI Analyst"}
                  </Typography>
                  <Box
                    sx={{
                      background: isUser
                        ? "linear-gradient(135deg, #5b5cf6, #8b5cf6)"
                        : "linear-gradient(180deg, #ffffff, #f7f5ff)",
                      border: isUser ? 0 : "1px solid rgba(91,92,246,0.12)",
                      borderRadius: "14px",
                      boxShadow: isUser ? "0 12px 24px rgba(91,92,246,0.22)" : "0 10px 22px rgba(36,59,122,0.06)",
                      color: isUser ? "primary.contrastText" : "text.primary",
                      maxWidth: isUser ? "min(680px, 88%)" : "min(860px, 96%)",
                      overflowWrap: "anywhere",
                      p: isUser ? 1.5 : { xs: 1.5, sm: 2 },
                      whiteSpace: isUser ? "pre-wrap" : "normal",
                      wordBreak: "break-word",
                    }}
                  >
                    {message.content ? (
                      isUser ? (
                        <Typography sx={{ color: "inherit", whiteSpace: "pre-wrap", wordBreak: "break-word" }} variant="body2">
                          {message.content}
                        </Typography>
                      ) : (
                        <MarkdownMessage content={message.content} />
                      )
                    ) : (
                      <Typography color={isUser ? "primary.contrastText" : "text.secondary"} variant="body2">
                        {message.status === "streaming" ? "Analyzing run context..." : "No response"}
                      </Typography>
                    )}
                  </Box>
                  {statusLabel && (
                    <Typography color="text.secondary" variant="caption">
                      {statusLabel}
                    </Typography>
                  )}
                  {message.role === "assistant" && message.evidenceRefs.length > 0 && (
                    <Stack spacing={0.75} sx={{ maxWidth: "min(760px, 92%)" }}>
                      <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
                        Evidence references
                      </Typography>
                      <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                        {message.evidenceRefs.map((refItem) => (
                          <EvidenceChip
                            key={`${refItem.log_id}-${refItem.line_number}`}
                            refItem={refItem}
                            onClick={onEvidenceSelect}
                          />
                        ))}
                      </Stack>
                    </Stack>
                  )}
                </Stack>
              );
            })}
          </Stack>
        )}

        {error && <Alert severity="error">{error}</Alert>}
        {!run && (
          <Typography color="text.secondary" variant="caption">
            Start an analysis run before asking LogAn AI.
          </Typography>
        )}

        <Box
          component="form"
          onSubmit={(event) => {
            event.preventDefault();
            void sendMessage();
          }}
        >
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: "flex-end" }}>
            <TextField
              aria-label="Ask LogAn AI"
              disabled={composerDisabled}
              fullWidth
              minRows={3}
              multiline
              placeholder="Ask about this incident, logs, timeline, or likely root cause..."
              sx={{
                "& .MuiOutlinedInput-root": {
                  borderRadius: "12px",
                  p: 0.5,
                },
              }}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
            />
            {streamingMessageId ? (
              <Button variant="secondary" onClick={cancel}>
                Cancel
              </Button>
            ) : (
              <Button disabled={!input.trim() || !run} type="submit">
                Ask
              </Button>
            )}
          </Stack>
        </Box>
      </Stack>
    </Card>
  );
}
