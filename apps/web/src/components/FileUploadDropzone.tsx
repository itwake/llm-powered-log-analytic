"use client";

import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useState, type DragEvent, type ReactNode } from "react";
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

function fileMatchesAccept(file: File, accept: string): boolean {
  const rules = accept
    .split(",")
    .map((rule) => rule.trim().toLowerCase())
    .filter(Boolean);

  if (rules.length === 0) {
    return true;
  }

  const fileName = file.name.toLowerCase();
  const fileType = file.type.toLowerCase();

  return rules.some((rule) => {
    if (rule.startsWith(".")) {
      return fileName.endsWith(rule);
    }
    if (rule.endsWith("/*")) {
      return fileType.startsWith(rule.slice(0, -1));
    }
    return fileType === rule;
  });
}

function acceptedFilesFromList(fileList: FileList, accept: string, multiple: boolean): File[] {
  const accepted = Array.from(fileList).filter((file) => fileMatchesAccept(file, accept));
  return multiple ? accepted : accepted.slice(0, 1);
}

function isFileDrag(event: DragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
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
  const [dragDepth, setDragDepth] = useState(0);
  const isDragging = dragDepth > 0 && !disabled;
  const selectedLabel = files.length
    ? `${files.length} file${files.length === 1 ? "" : "s"} selected`
    : "No files selected";
  const hintContent = isDragging ? "Drop files to attach them." : hint || selectedLabel;

  function handleDragEnter(event: DragEvent<HTMLElement>) {
    if (disabled || !isFileDrag(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDragDepth((current) => current + 1);
  }

  function handleDragOver(event: DragEvent<HTMLElement>) {
    if (disabled || !isFileDrag(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDragLeave(event: DragEvent<HTMLElement>) {
    if (disabled || !isFileDrag(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDragDepth((current) => Math.max(0, current - 1));
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    if (disabled) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDragDepth(0);
    const nextFiles = acceptedFilesFromList(event.dataTransfer.files, accept, multiple);
    if (nextFiles.length > 0) {
      onFilesSelected(nextFiles);
    }
  }

  return (
    <Box
      aria-disabled={disabled}
      sx={{
        background: isDragging
          ? "linear-gradient(135deg, rgba(91,92,246,0.16), rgba(6,182,212,0.15))"
          : "linear-gradient(135deg, rgba(217,236,255,0.56), rgba(230,225,255,0.48))",
        border: "1px dashed",
        borderColor: isDragging ? "primary.main" : "rgba(91,92,246,0.28)",
        borderRadius: "14px",
        boxShadow: isDragging ? "0 16px 34px rgba(91,92,246,0.16)" : "none",
        p: { xs: 1.75, sm: 2.25 },
        transition: "background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease",
      }}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
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
          <FieldHint>{hintContent}</FieldHint>
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
              const nextFiles = event.currentTarget.files
                ? acceptedFilesFromList(event.currentTarget.files, accept, multiple)
                : [];
              onFilesSelected(nextFiles);
              event.currentTarget.value = "";
            }}
          />
        </Button>
      </Stack>
    </Box>
  );
}
