"use client";

import { useEffect, useState } from "react";
import {
  api,
  DetectionRule,
  PrimitiveSpec,
  RuleConditionDraft,
  RuleDraft,
  RuleDryRunResult,
} from "@/lib/api";
import { Card, Loader, InfoTooltip, Badge } from "@/components/ui";

const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

function blankCondition(primitive: string, primitives: Record<string, PrimitiveSpec>): RuleConditionDraft {
  return { primitive, params: { ...(primitives[primitive]?.defaults ?? {}) }, negate: false };
}

function emptyDraft(primitives: Record<string, PrimitiveSpec>): RuleDraft {
  const firstPrimitive = Object.keys(primitives)[0] ?? "generic_group_aggregate";
  return {
    rule_id: "",
    name: "",
    description: "",
    detection_type: "custom",
    severity: "MEDIUM",
    rule_json: { combinator: "AND", conditions: [blankCondition(firstPrimitive, primitives)] },
    enabled: true,
  };
}

function ParamInput({
  paramName,
  typeSpec,
  value,
  onChange,
}: {
  paramName: string;
  typeSpec: string;
  value: string | number | boolean;
  onChange: (v: string | number) => void;
}) {
  if (typeSpec.startsWith("enum:")) {
    const options = typeSpec.split(":", 2)[1].split(",");
    return (
      <select
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    );
  }
  if (typeSpec === "int" || typeSpec === "float") {
    return (
      <input
        type="number"
        step={typeSpec === "float" ? "0.01" : "1"}
        value={typeof value === "number" ? value : ""}
        onChange={(e) => onChange(typeSpec === "float" ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
      />
    );
  }
  return (
    <input
      type="text"
      value={String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
    />
  );
}

export default function RulesPage() {
  const [primitives, setPrimitives] = useState<Record<string, PrimitiveSpec> | null>(null);
  const [rules, setRules] = useState<DetectionRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [dryRun, setDryRun] = useState<RuleDryRunResult | null>(null);
  const [dryRunning, setDryRunning] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const loadRules = () => api.getRules().then(setRules).catch(() => setRules([]));

  useEffect(() => {
    Promise.all([api.getRulePrimitives(), api.getRules()])
      .then(([p, r]) => { setPrimitives(p); setRules(r); })
      .finally(() => setLoading(false));
  }, []);

  const selectRule = (rule: DetectionRule) => {
    setDraft({ ...rule });
    setIsNew(false);
    setDryRun(null);
    setSaveError(null);
  };

  const startNewRule = () => {
    if (!primitives) return;
    setDraft(emptyDraft(primitives));
    setIsNew(true);
    setDryRun(null);
    setSaveError(null);
  };

  const updateCondition = (index: number, updates: Partial<RuleConditionDraft>) => {
    if (!draft) return;
    const conditions = draft.rule_json.conditions.map((c, i) => (i === index ? { ...c, ...updates } : c));
    setDraft({ ...draft, rule_json: { ...draft.rule_json, conditions } });
  };

  const setConditionParam = (index: number, paramName: string, value: string | number) => {
    if (!draft) return;
    const conditions = draft.rule_json.conditions.map((c, i) =>
      i === index ? { ...c, params: { ...c.params, [paramName]: value } } : c
    );
    setDraft({ ...draft, rule_json: { ...draft.rule_json, conditions } });
  };

  const addCondition = () => {
    if (!draft || !primitives) return;
    const firstPrimitive = Object.keys(primitives)[0];
    setDraft({
      ...draft,
      rule_json: {
        ...draft.rule_json,
        conditions: [...draft.rule_json.conditions, blankCondition(firstPrimitive, primitives)],
      },
    });
  };

  const removeCondition = (index: number) => {
    if (!draft) return;
    setDraft({
      ...draft,
      rule_json: { ...draft.rule_json, conditions: draft.rule_json.conditions.filter((_, i) => i !== index) },
    });
  };

  const runDryRun = () => {
    if (!draft) return;
    setDryRunning(true);
    api
      .dryRunRule(draft.detection_type, draft.severity, draft.rule_json)
      .then(setDryRun)
      .catch((err) => setSaveError(err.message))
      .finally(() => setDryRunning(false));
  };

  const saveRule = () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    const action = isNew
      ? api.createRule(draft)
      : api.updateRule(draft.rule_id, {
          name: draft.name,
          description: draft.description,
          severity: draft.severity,
          rule_json: draft.rule_json,
          enabled: draft.enabled,
        });
    action
      .then(() => { loadRules(); setDraft(null); })
      .catch((err) => setSaveError(err.message))
      .finally(() => setSaving(false));
  };

  const toggleEnabled = (rule: DetectionRule) => {
    const action = rule.enabled ? api.disableRule(rule.rule_id) : api.enableRule(rule.rule_id);
    action.then(loadRules);
  };

  const deleteRule = (rule: DetectionRule) => {
    if (rule.is_builtin) return;
    if (!confirm(`Delete rule "${rule.name}"? This cannot be undone.`)) return;
    api.deleteRule(rule.rule_id).then(() => { loadRules(); setDraft(null); });
  };

  if (loading) return <div className="min-h-screen bg-[#0b1120] flex items-center justify-center"><Loader /></div>;

  return (
    <div className="min-h-screen bg-[#0b1120] p-6 text-white max-w-[1600px] mx-auto">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Rule Engine</h1>
          <p className="text-xs text-slate-400">
            Edit any detector's thresholds or define new patterns — no code deploy
            <InfoTooltip text="Every built-in detector (round-trip, layering, structuring, etc.) is now a rule you can edit here. Combine primitives with AND/OR to define genuinely new patterns." />
          </p>
        </div>
        <button
          onClick={startNewRule}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg transition font-medium"
        >
          + New Rule
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Rule list */}
        <Card className="lg:col-span-1">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Rules ({rules.length})
          </h3>
          <div className="space-y-1.5 max-h-[70vh] overflow-y-auto">
            {rules.map((rule) => (
              <button
                key={rule.rule_id}
                onClick={() => selectRule(rule)}
                className={`w-full text-left rounded-lg border p-2.5 transition ${
                  draft?.rule_id === rule.rule_id && !isNew
                    ? "border-blue-500/50 bg-blue-500/10"
                    : "border-slate-700/50 hover:bg-slate-800/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-white truncate">{rule.name}</span>
                  {rule.is_builtin && <span className="text-[9px] text-slate-500">🔒</span>}
                </div>
                <div className="flex items-center gap-1.5 mt-1">
                  <Badge variant={rule.enabled ? "success" : "default"}>{rule.enabled ? "enabled" : "disabled"}</Badge>
                  <span className="text-[10px] text-slate-500">{rule.detection_type}</span>
                  <span className="text-[10px] text-slate-600">v{rule.version}</span>
                </div>
              </button>
            ))}
          </div>
        </Card>

        {/* Editor */}
        <Card className="lg:col-span-2">
          {!draft ? (
            <div className="text-center py-16 text-slate-500 text-sm">Select a rule to edit, or create a new one.</div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-slate-200">
                  {isNew ? "New Rule" : draft.name}
                  {!isNew && (draft as DetectionRule).is_builtin && (
                    <span className="ml-2 text-[10px] text-amber-400">built-in — editable, not deletable</span>
                  )}
                </h3>
                {!isNew && !(draft as DetectionRule).is_builtin && (
                  <button
                    onClick={() => deleteRule(draft as DetectionRule)}
                    className="text-[10px] text-red-400 hover:text-red-300"
                  >
                    Delete
                  </button>
                )}
              </div>

              {isNew && (
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="text-[10px] text-slate-500 block mb-1">Rule ID</label>
                    <input
                      value={draft.rule_id}
                      onChange={(e) => setDraft({ ...draft, rule_id: e.target.value.replace(/\s+/g, "_") })}
                      placeholder="my_custom_rule"
                      className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-500 block mb-1">Detection Type</label>
                    <input
                      value={draft.detection_type}
                      onChange={(e) => setDraft({ ...draft, detection_type: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <label className="text-[10px] text-slate-500 block mb-1">Name</label>
                  <input
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 block mb-1">Severity</label>
                  <select
                    value={draft.severity}
                    onChange={(e) => setDraft({ ...draft, severity: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                  >
                    {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>

              <div className="mb-3">
                <label className="text-[10px] text-slate-500 block mb-1">Description</label>
                <input
                  value={draft.description ?? ""}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                />
              </div>

              {/* Combinator */}
              {draft.rule_json.conditions.length > 1 && (
                <div className="mb-3">
                  <label className="text-[10px] text-slate-500 block mb-1">
                    Combine conditions with <InfoTooltip text="AND requires every condition to match the same account. OR flags an account if any condition matches." />
                  </label>
                  <div className="flex gap-1.5">
                    {["AND", "OR"].map((c) => (
                      <button
                        key={c}
                        onClick={() => setDraft({ ...draft, rule_json: { ...draft.rule_json, combinator: c as "AND" | "OR" } })}
                        className={`px-3 py-1 text-[10px] rounded-full font-medium transition ${
                          draft.rule_json.combinator === c ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Conditions */}
              <div className="space-y-3 mb-3">
                {draft.rule_json.conditions.map((cond, i) => {
                  const spec = primitives?.[cond.primitive];
                  return (
                    <div key={i} className="rounded-lg border border-slate-700/50 p-3 bg-slate-900/30">
                      <div className="flex items-center justify-between mb-2">
                        <select
                          value={cond.primitive}
                          onChange={(e) =>
                            updateCondition(i, {
                              primitive: e.target.value,
                              params: { ...(primitives?.[e.target.value]?.defaults ?? {}) },
                            })
                          }
                          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white font-medium"
                        >
                          {primitives && Object.keys(primitives).map((p) => <option key={p} value={p}>{p}</option>)}
                        </select>
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1 text-[10px] text-slate-400">
                            <input
                              type="checkbox"
                              checked={cond.negate}
                              onChange={(e) => updateCondition(i, { negate: e.target.checked })}
                            />
                            NOT
                          </label>
                          {draft.rule_json.conditions.length > 1 && (
                            <button onClick={() => removeCondition(i)} className="text-[10px] text-red-400 hover:text-red-300">
                              ✕
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        {spec && Object.entries(spec.params).map(([paramName, typeSpec]) => (
                          <div key={paramName}>
                            <label className="text-[9px] text-slate-500 block mb-0.5">{paramName}</label>
                            <ParamInput
                              paramName={paramName}
                              typeSpec={typeSpec}
                              value={cond.params[paramName] ?? spec.defaults[paramName]}
                              onChange={(v) => setConditionParam(i, paramName, v)}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
                <button
                  onClick={addCondition}
                  className="text-[10px] text-blue-400 hover:text-blue-300"
                >
                  + Add condition
                </button>
              </div>

              {saveError && (
                <div className="mb-3 text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
                  {saveError}
                </div>
              )}

              <div className="flex items-center gap-2 pt-2 border-t border-slate-800">
                <button
                  onClick={runDryRun}
                  disabled={dryRunning}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 text-xs rounded-lg transition"
                >
                  {dryRunning ? "Running..." : "Dry-run preview"}
                </button>
                <button
                  onClick={saveRule}
                  disabled={saving || !draft.rule_id || !draft.name}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs rounded-lg transition font-medium"
                >
                  {saving ? "Saving..." : isNew ? "Create Rule" : "Save Changes"}
                </button>
                {!isNew && (
                  <button
                    onClick={() => toggleEnabled(draft as DetectionRule)}
                    className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg transition"
                  >
                    {(draft as DetectionRule).enabled ? "Disable" : "Enable"}
                  </button>
                )}
              </div>

              {dryRun && (
                <div className="mt-4 pt-4 border-t border-slate-800">
                  <h4 className="text-xs font-semibold text-slate-300 mb-2">
                    Dry-run: {dryRun.matched_count} account(s) would match
                  </h4>
                  <div className="flex flex-wrap gap-1.5">
                    {dryRun.newly_flagged_accounts.map((acc) => (
                      <span key={acc} className="text-[10px] font-mono bg-slate-800 text-blue-400 px-2 py-0.5 rounded">
                        {acc}
                      </span>
                    ))}
                    {dryRun.newly_flagged_accounts.length === 0 && (
                      <span className="text-[10px] text-slate-600">No accounts currently match this rule.</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
