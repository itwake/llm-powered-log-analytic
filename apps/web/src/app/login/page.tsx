"use client";

import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useEffect, useRef, useState } from "react";
import { Button, Card } from "@/components/ui";
import { buildLoginUrl } from "@/lib/auth";
import { safeNextPath } from "@/lib/navigation";

export default function LoginPage() {
  const [loginUrl, setLoginUrl] = useState(() => buildLoginUrl("/cases"));
  const redirectStartedRef = useRef(false);

  useEffect(() => {
    if (redirectStartedRef.current) {
      return;
    }
    redirectStartedRef.current = true;
    const url = buildLoginUrl(safeNextPath(window.location.search));
    setLoginUrl(url);
    window.location.replace(url);
  }, []);

  return (
    <Box component="main" sx={{ alignItems: "center", display: "flex", minHeight: "100vh", py: 4 }}>
      <Container maxWidth="sm">
        <Card>
          <Stack spacing={2}>
            <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
              Continue to LogAn
            </Typography>
            <Typography>Starting your LogAn session.</Typography>
            <Typography color="text.secondary">
              Authentication is selected by the server configuration.
            </Typography>
            <Box>
              <Button component="a" href={loginUrl} variant="primary">
                Continue
              </Button>
            </Box>
          </Stack>
        </Card>
      </Container>
    </Box>
  );
}
