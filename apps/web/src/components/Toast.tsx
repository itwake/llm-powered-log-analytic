"use client";

import Alert from "@mui/material/Alert";
import Snackbar from "@mui/material/Snackbar";

export interface ToastMessage {
  severity: "success" | "error" | "info";
  text: string;
}

interface ToastProps {
  message: ToastMessage | null;
  onClose: () => void;
}

/** Feedback shown near the bottom of the viewport, where it is visible whatever was clicked. */
export function Toast({ message, onClose }: ToastProps) {
  return (
    <Snackbar
      anchorOrigin={{ horizontal: "center", vertical: "bottom" }}
      autoHideDuration={message?.severity === "error" ? null : 4000}
      key={message ? `${message.severity}:${message.text}` : "none"}
      open={message !== null}
      onClose={(_, reason) => {
        if (reason !== "clickaway") {
          onClose();
        }
      }}
    >
      <Alert
        severity={message?.severity ?? "info"}
        sx={{ boxShadow: 6, maxWidth: 560 }}
        variant="filled"
        onClose={onClose}
      >
        {message?.text}
      </Alert>
    </Snackbar>
  );
}
