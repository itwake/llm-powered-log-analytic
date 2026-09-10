import { ColorBadge } from "@/components/ui";
import { signalColor } from "@/lib/signals";

export function SignalBadge({ signal }: { signal: string }) {
  const color = signalColor(signal);

  return (
    <ColorBadge
      color={color}
      sx={{
        bgcolor: color,
        borderColor: color,
        boxShadow: `0 0 0 3px ${color}26`,
        color: "#fff",
        textTransform: "capitalize",
      }}
    >
      {signal}
    </ColorBadge>
  );
}
