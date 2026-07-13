import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Placeholder — Monitoring (Phase 21, watchlist) and Audit Logs (Phase 14
 * list route) content lands in later phases, per docs/FRONTEND_ROADMAP.md.
 */
export default function MyCenterPage() {
  return (
    <div className="p-6">
      <Card>
        <CardHeader>
          <CardTitle>My Center</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          Monitoring and audit logs — built in Phases 14 and 21.
        </CardContent>
      </Card>
    </div>
  );
}
