import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Placeholder — this phase (13) only builds the shell/auth. Real content
 * (summary cards, alert table wired to `GET /alerts`) is Phase 14's scope,
 * per docs/FRONTEND_ROADMAP.md.
 */
export default function DashboardPage() {
  return (
    <div className="p-6">
      <Card>
        <CardHeader>
          <CardTitle>Dashboard</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          Alert-level, system-wide view — built in Phase 14.
        </CardContent>
      </Card>
    </div>
  );
}
