"use client";

import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";
import { Button, FieldHint } from "@/components/ui";

interface FileUploadDropzoneProps {
  accept: string;
  files: File[];
  onFilesSelected: (files: File[]) => void;
  actionLabel?: string;
  description?: string;
  disabled?: boolean;
  hint?: ReactNode;
  multiple?: boolean;
  title?: string;
}

export function FileUploadDropzone({
  accept,
  actionLabel = "Choose files",
  description = "Select log, text, JSON, or archive files for analysis.",
  disabled = false,
  files,
  hint,
  multiple = true,
  onFilesSelected,
  title = "Log/archive files",
}: FileUploadDropzoneProps) {
  const selectedLabel = files.length
    ? `${files.length} file${files.length === 1 ? "" : "s"} selected`
    : "No files selected";

  return (
    <Box
      sx={{
        background: "linear-gradient(135deg, rgba(217,236,255,0.56), rgba(230,225,255,0.48))",
        border: "1px dashed",
        borderColor: "rgba(91,92,246,0.28)",
        borderRadius: "14px",
        p: { xs: 1.75, sm: 2.25 },
      }}
    >
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { xs: "stretch", sm: "center" } }}>
        <Box
          sx={{
            alignItems: "center",
            background: "linear-gradient(135deg, #5b5cf6, #06b6d4)",
            borderRadius: "12px",
            boxShadow: "0 12px 24px rgba(91,92,246,0.18)",
            color: "#ffffff",
            display: { xs: "none", sm: "flex" },
            flex: "0 0 auto",
            height: 44,
            justifyContent: "center",
            width: 44,
          }}
        >
          <InsertDriveFileIcon fontSize="small" />
        </Box>
        <Box sx={{ flex: "1 1 auto", minWidth: 0 }}>
          <Typography sx={{ fontWeight: 850 }} variant="body1">
            {title}
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 0.35 }} variant="body2">
            {description}
          </Typography>
          <FieldHint>{hint || selectedLabel}</FieldHint>
        </Box>
        <Button
          component="label"
          disabled={disabled}
          startIcon={<UploadFileIcon fontSize="small" />}
          sx={{ alignSelf: { xs: "flex-start", sm: "center" } }}
          variant="secondary"
        >
          {actionLabel}
          <Box
            aria-label={title}
            component="input"
            accept={accept}
            disabled={disabled}
            multiple={multiple}
            type="file"
            sx={{
              clip: "rect(0 0 0 0)",
              clipPath: "inset(50%)",
              height: 1,
              overflow: "hidden",
              position: "absolute",
              whiteSpace: "nowrap",
              width: 1,
            }}
            onChange={(event) => {
              onFilesSelected(Array.from(event.currentTarget.files || []));
              event.currentTarget.value = "";
            }}
          />
        </Button>
      </Stack>
    </Box>
  );
}
