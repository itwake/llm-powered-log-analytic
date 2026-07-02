"use client";

import AddCircleIcon from "@mui/icons-material/AddCircle";
import Box from "@mui/material/Box";
import CardActionArea from "@mui/material/CardActionArea";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import MuiCard from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import { FormEvent, useEffect, useState } from "react";
import Link from "@/components/Link";
import { CaseListResponse, casesApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Badge, Button, Card, EmptyState, SkeletonBlock, statusTone } from "@/components/ui";

export default function CasesPage() {
  const [data, setData] = useState<CaseListResponse | null>(null);
  const [status, setStatus] = useState("");
  const [product, setProduct] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(nextStatus = status, nextProduct = product) {
    setLoading(true);
    setError(null);
    try {
      const response = await casesApi.list({
        status: nextStatus || undefined,
        product: nextProduct || undefined,
        page_size: 50,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("", "");
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  return (
    <Stack spacing={2.5}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}
      >
        <Box>
          <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
            Incident queue
          </Typography>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
            Cases
          </Typography>
          <Typography color="text.secondary" variant="body1">
            Open incidents, active analyses, and completed reports.
          </Typography>
        </Box>
        <Button component={Link} href="/cases/new" startIcon={<AddCircleIcon />} variant="primary">
          New case
        </Button>
      </Stack>

      <Card>
        <Box component="form" onSubmit={submit}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { xs: "stretch", md: "center" } }}>
          <FormControl sx={{ minWidth: 180 }}>
            <InputLabel id="case-status-filter-label">Status</InputLabel>
            <Select
              label="Status"
              labelId="case-status-filter-label"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <MenuItem value="">Any</MenuItem>
              <MenuItem value="created">Created</MenuItem>
              <MenuItem value="uploading">Uploading</MenuItem>
              <MenuItem value="processing">Processing</MenuItem>
              <MenuItem value="ready">Ready</MenuItem>
              <MenuItem value="failed">Failed</MenuItem>
              <MenuItem value="cancelled">Cancelled</MenuItem>
            </Select>
          </FormControl>
          <TextField
            label="Product"
            sx={{ minWidth: { md: 260 } }}
            value={product}
            onChange={(event) => setProduct(event.target.value)}
          />
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
        </Box>
      </Card>

      {error && <Alert severity="error">{error}</Alert>}

      {loading && (
        <Box
          component="section"
          sx={{
            display: "grid",
            gap: 2,
            gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" },
          }}
        >
          <Card><SkeletonBlock lines={4} /></Card>
          <Card><SkeletonBlock lines={4} /></Card>
          <Card><SkeletonBlock lines={4} /></Card>
        </Box>
      )}

      {!loading && data && data.items.length === 0 && (
        <Card>
          <EmptyState title="No cases found">
            <Button component={Link} href="/cases/new" variant="secondary">
              Create a case
            </Button>
          </EmptyState>
        </Card>
      )}

      {!loading && data && data.items.length > 0 && (
        <Box
          component="section"
          sx={{
            display: "grid",
            gap: 2,
            gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" },
          }}
        >
          {data.items.map((item) => (
            <MuiCard key={item.case_id}>
              <CardActionArea component={Link} href={`/cases/${item.case_id}`} sx={{ height: "100%" }}>
                <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2, height: "100%", p: 2.5 }}>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
                    <Typography color="text.secondary" sx={{ fontWeight: 800 }} variant="caption">
                      {item.case_key}
                    </Typography>
                    <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                  </Stack>
                  <Typography component="h2" sx={{ fontWeight: 850, overflowWrap: "anywhere" }} variant="h6">
                    {valueLabel(item.title)}
                  </Typography>
                  <Box
                    component="dl"
                    sx={{
                      display: "grid",
                      gap: 1,
                      gridTemplateColumns: "120px minmax(0, 1fr)",
                      m: 0,
                      "& dt": { color: "text.secondary" },
                      "& dd": { m: 0, overflowWrap: "anywhere" },
                    }}
                  >
                    <dt>Product</dt>
                    <dd>{valueLabel(item.product)}</dd>
                    <dt>Service</dt>
                    <dd>{valueLabel(item.service)}</dd>
                    <dt>Incident start</dt>
                    <dd>{formatDateTime(item.incident_start)}</dd>
                  </Box>
                  <Typography color="primary" sx={{ fontWeight: 800, mt: "auto" }} variant="body2">
                    Open workspace
                  </Typography>
                </CardContent>
              </CardActionArea>
            </MuiCard>
          ))}
        </Box>
      )}
    </Stack>
  );
}
