import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * L1 Triage §9 — AI Recommendation. **UI slot only, deliberately not wired
 * to any endpoint** — the Recommendation Engine is Phase 9 backend work,
 * not started (`docs/FRONTEND_ROADMAP.md` decision 5 / Phase 16 checklist).
 * Do not add a fetch here until that phase ships; per the cross-phase
 * invariant, a `TODO`/empty state is always preferred over faked data.
 */
export function AiRecommendationSlot() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Recommendation</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground text-sm">
          Recommendations will appear here once available.
        </p>
      </CardContent>
    </Card>
  );
}
