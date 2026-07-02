"use client";

import { alpha, createTheme } from "@mui/material/styles";
import type {} from "@mui/x-data-grid/themeAugmentation";

const palette = {
  appBg: "#f3f5ff",
  sidebarBg: "#172033",
  sidebarBorder: "rgba(255, 255, 255, 0.08)",
  sidebarMuted: "#8ea0bd",
  primary: "#5b5cf6",
  primaryDark: "#4543d0",
  cyan: "#06b6d4",
  success: "#10b981",
  warning: "#f97316",
  error: "#ef4444",
  tableHeader: "#e6e1ff",
  tableHover: "#f4f7ff",
  infoPanel: "#d9ecff",
  paper: "#ffffff",
  text: "#101828",
  muted: "#667085",
  divider: "#dfe5f5",
};

export const loganTheme = createTheme({
  cssVariables: true,
  palette: {
    mode: "light",
    primary: { main: palette.primary, dark: palette.primaryDark },
    secondary: { main: "#8b5cf6" },
    success: { main: palette.success },
    warning: { main: palette.warning },
    error: { main: palette.error },
    info: { main: palette.cyan },
    background: {
      default: palette.appBg,
      paper: palette.paper,
    },
    text: {
      primary: palette.text,
      secondary: palette.muted,
    },
    divider: palette.divider,
  },
  shape: {
    borderRadius: 16,
  },
  typography: {
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    button: {
      textTransform: "none",
      fontWeight: 750,
      letterSpacing: 0,
    },
    h1: {
      fontWeight: 850,
      letterSpacing: 0,
    },
    h2: {
      fontWeight: 800,
      letterSpacing: 0,
    },
    h3: {
      fontWeight: 780,
      letterSpacing: 0,
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: (theme) => ({
        body: {
          background:
            `radial-gradient(circle at top left, ${alpha(theme.palette.primary.main, 0.14)}, transparent 34rem), ${theme.palette.background.default}`,
          color: theme.palette.text.primary,
        },
      }),
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: ({ theme }) => ({
          borderRadius: 12,
          fontWeight: 780,
          minHeight: 38,
          whiteSpace: "nowrap",
          "&.MuiButton-containedPrimary": {
            background: `linear-gradient(135deg, ${theme.palette.primary.main}, ${theme.palette.secondary.main})`,
            boxShadow: `0 12px 24px ${alpha(theme.palette.primary.main, 0.24)}`,
          },
          "&.MuiButton-containedPrimary:hover": {
            boxShadow: `0 14px 28px ${alpha(theme.palette.primary.main, 0.3)}`,
          },
          "&.MuiButton-outlined": {
            backgroundColor: alpha(theme.palette.background.paper, 0.76),
            borderColor: alpha(theme.palette.primary.main, 0.22),
          },
          "&.MuiButton-text": {
            backgroundColor: alpha(theme.palette.primary.main, 0.06),
          },
        }),
      },
    },
    MuiCard: {
      defaultProps: {
        variant: "outlined",
      },
      styleOverrides: {
        root: ({ theme }) => ({
          borderColor: alpha(theme.palette.primary.main, 0.1),
          borderRadius: 18,
          boxShadow: `0 18px 45px ${alpha("#243b7a", 0.09)}`,
        }),
      },
    },
    MuiChip: {
      defaultProps: {
        size: "small",
        variant: "outlined",
      },
      styleOverrides: {
        root: ({ theme }) => ({
          border: 0,
          borderRadius: 999,
          fontWeight: 780,
          minHeight: 24,
          "&.MuiChip-colorDefault": {
            backgroundColor: alpha("#64748b", 0.12),
            color: "#475569",
          },
          "&.MuiChip-colorPrimary": {
            backgroundColor: alpha(theme.palette.primary.main, 0.13),
            color: theme.palette.primary.dark,
          },
          "&.MuiChip-colorInfo": {
            backgroundColor: alpha(theme.palette.info.main, 0.14),
            color: "#0e7490",
          },
          "&.MuiChip-colorSuccess": {
            backgroundColor: alpha(theme.palette.success.main, 0.14),
            color: "#047857",
          },
          "&.MuiChip-colorWarning": {
            backgroundColor: alpha(theme.palette.warning.main, 0.14),
            color: "#c2410c",
          },
          "&.MuiChip-colorError": {
            backgroundColor: alpha(theme.palette.error.main, 0.13),
            color: "#b91c1c",
          },
        }),
      },
    },
    MuiTextField: {
      defaultProps: {
        size: "small",
      },
      styleOverrides: {
        root: ({ theme }) => ({
          "& .MuiOutlinedInput-root": {
            backgroundColor: theme.palette.background.paper,
            borderRadius: 12,
          },
        }),
      },
    },
    MuiFormControl: {
      defaultProps: {
        size: "small",
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          borderRadius: 12,
        },
      },
    },
    MuiDataGrid: {
      defaultProps: {
        disableColumnMenu: true,
      },
      styleOverrides: {
        root: ({ theme }) => ({
          borderColor: alpha(theme.palette.primary.main, 0.12),
          borderRadius: 16,
          backgroundColor: theme.palette.background.paper,
          boxShadow: `0 14px 32px ${alpha("#243b7a", 0.06)}`,
          "--DataGrid-rowBorderColor": alpha(theme.palette.primary.main, 0.1),
          "& .MuiDataGrid-columnHeaders": {
            backgroundColor: palette.tableHeader,
            color: "#322572",
            minHeight: "48px !important",
          },
          "& .MuiDataGrid-columnHeader": {
            backgroundColor: palette.tableHeader,
          },
          "& .MuiDataGrid-columnHeaderTitle": {
            fontWeight: 850,
          },
          "& .MuiDataGrid-row:hover": {
            backgroundColor: palette.tableHover,
          },
          "& .MuiDataGrid-cell:focus, & .MuiDataGrid-columnHeader:focus": {
            outline: "none",
          },
          "& .MuiDataGrid-cell:focus-within, & .MuiDataGrid-columnHeader:focus-within": {
            outline: `1px solid ${theme.palette.primary.main}`,
            outlineOffset: -1,
          },
        }),
      },
    },
  },
});

export const loganTokens = palette;
