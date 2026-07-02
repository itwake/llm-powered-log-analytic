"use client";

import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import Link from "@/components/Link";
import { Button, Card } from "@/components/ui";
import { buildSsoLoginUrl } from "@/lib/auth";
import { safeNextPath } from "@/lib/navigation";

export default function LoginPage() {
  const [ssoUrl, setSsoUrl] = useState(() => buildSsoLoginUrl("/cases"));

  useEffect(() => {
    const url = buildSsoLoginUrl(safeNextPath(window.location.search));
    setSsoUrl(url);
    window.location.replace(url);
  }, []);

  return (
    <Box component="main" sx={{ alignItems: "center", display: "flex", minHeight: "100vh", py: 4 }}>
      <Container maxWidth="sm">
        <Card>
          <Stack spacing={2}>
            <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
              Continue with SSO
            </Typography>
            <Typography>Redirecting to corporate sign-in for LogAn Platform access.</Typography>
            <Typography color="text.secondary">
              LogAn only supports corporate single sign-on. Your account is provisioned automatically
              the first time you complete SSO.
            </Typography>
            <Box>
              <Button component={Link} href={ssoUrl} variant="primary">
                Continue with SSO
              </Button>
            </Box>
          </Stack>
        </Card>
      </Container>
    </Box>
  );
}
