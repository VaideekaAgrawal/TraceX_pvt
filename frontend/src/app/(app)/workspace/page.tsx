import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Placeholder — the case-tab shell, queue, and Zustand per-case store are
 * Phase 15's scope, per docs/FRONTEND_ROADMAP.md. Nothing case-specific
 * belongs here yet (explicitly out of scope for Phase 13).
 */
export default function WorkspacePage() {
  return (
    <div className="p-6">
      <Card>
        <CardHeader>
          <CardTitle>Investigation Workspace</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          Case queue, tabs, and Triage/Deep Investigation views — built in
          Phases 15–18.
        </CardContent>
      </Card>
    </div>
  );
}
