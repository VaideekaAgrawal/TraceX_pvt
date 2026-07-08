"use client";
import { useState, useEffect } from "react";
import { api, Account } from "@/lib/api";
import { Card, Loader, Badge, InfoTooltip } from "@/components/ui";
import { formatINR, getRiskBg } from "@/lib/utils";

interface GeneratedCase {
  case_id: string;
  generated_at: string;
  accounts_count: number;
  pattern_type: string;
  summary: Record<string, unknown>;
  pdf_base64: string;
  json_data: string;
}

function generateCaseId(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `STR-${yyyy}-${mm}${dd}-${hh}${min}${ss}`;
}

export default function EvidencePage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Form state
  const [caseId, setCaseId] = useState(generateCaseId());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchFilter, setSearchFilter] = useState("");
  const [patternType, setPatternType] = useState("Layering");
  const [caseNotes, setCaseNotes] = useState("");

  // Result state
  const [result, setResult] = useState<GeneratedCase | null>(null);
  const [cases, setCases] = useState<GeneratedCase[]>([]);

  useEffect(() => {
    api.getAccounts().then((data) => {
      setAccounts(Array.isArray(data) ? data : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const filteredAccounts = accounts.filter((a) => {
    if (!a) return false;
    const q = searchFilter.toLowerCase();
    return (
      (a.account_id || "").toLowerCase().includes(q) ||
      (a.role || "").toLowerCase().includes(q) ||
      (a.branch_city || "").toLowerCase().includes(q)
    );
  });

  const toggleAccount = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (selectedIds.size === 0) return;
    setGenerating(true);
    try {
      const res = await api.generateEvidence(caseId, Array.from(selectedIds), patternType, caseNotes);
      const generated: GeneratedCase = {
        case_id: res.case_id,
        generated_at: new Date().toISOString(),
        accounts_count: selectedIds.size,
        pattern_type: patternType,
        summary: res.summary,
        pdf_base64: res.pdf_base64,
        json_data: res.json_data,
      };
      setResult(generated);
      setCases((prev) => [generated, ...prev]);
      setCaseId(generateCaseId());
      setSelectedIds(new Set());
      setCaseNotes("");
    } catch (e) {
      console.error("Evidence generation failed:", e);
    } finally {
      setGenerating(false);
    }
  };

  const downloadPdf = () => {
    if (!result) return;
    const byteCharacters = atob(result.pdf_base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.case_id}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJson = () => {
    if (!result) return;
    const blob = new Blob([result.json_data], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.case_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <Loader />;

  const summary = result?.summary as Record<string, unknown> | undefined;

  return (
    <div className="space-y-6 p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">FIU Evidence Generator <InfoTooltip text="Suspicious Transaction Report (STR) is a mandatory filing with FIU-India under PMLA Section 12. Banks must file within 7 days of detecting suspicious activity. This tool generates a structured evidence pack to support your STR filing." /></h1>
        <p className="text-slate-400 text-sm mt-1">Generate FIU-IND compliant STR reports</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Case Builder Form */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-white mb-4">Case Builder</h2>

            {/* Case ID */}
            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">Case ID <InfoTooltip text="A unique identifier for this investigation case. Use your internal case numbering system (e.g. STR-2026-001). This will appear in the STR reference number." /></label>
              <input
                type="text"
                value={caseId}
                onChange={(e) => setCaseId(e.target.value)}
                className="w-full bg-[#1a2332] border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            {/* Pattern Type */}
            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">Pattern Type <InfoTooltip text="Select the primary AML typology that best describes the suspicious behaviour. This determines which FATF typology code is referenced in the STR and guides the narrative section." /></label>
              <select
                value={patternType}
                onChange={(e) => setPatternType(e.target.value)}
                className="w-full bg-[#1a2332] border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                {["Layering", "Round-Tripping", "Structuring", "Dormant Activation", "Fan-In", "Fan-Out", "Combined", "Other"].map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            {/* Account Selection */}
            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">
                Select Accounts <InfoTooltip text="Select all accounts involved in this suspicious activity — both the primary account and any connected intermediary or destination accounts identified in your investigation." /> <span className="text-blue-400">({selectedIds.size} selected)</span>
              </label>
              <input
                type="text"
                placeholder="Search accounts by ID, role, or city..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="w-full bg-[#1a2332] border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none mb-2"
              />
              <div className="max-h-60 overflow-y-auto border border-slate-700/50 rounded-lg bg-[#0b1120] p-2 space-y-1">
                {filteredAccounts.map((acc) => (
                  <label
                    key={acc.account_id}
                    className="flex items-center gap-3 px-2 py-1.5 rounded hover:bg-slate-800/50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(acc.account_id)}
                      onChange={() => toggleAccount(acc.account_id)}
                      className="rounded border-slate-600"
                    />
                    <span className="text-sm text-white font-mono">{acc.account_id}</span>
                    <Badge variant={acc.risk_level === "CRITICAL" || acc.risk_level === "HIGH" ? "danger" : acc.risk_level === "MEDIUM" ? "warning" : "success"}>
                      {acc.risk_score.toFixed(1)}
                    </Badge>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${getRiskBg(acc.risk_level)}`}>
                      {acc.role}
                    </span>
                  </label>
                ))}
                {filteredAccounts.length === 0 && (
                  <p className="text-sm text-slate-500 text-center py-4">No accounts match filter</p>
                )}
              </div>
            </div>

            {/* Case Notes */}
            <div className="mb-4">
              <label className="block text-sm text-slate-400 mb-1">Case Notes <InfoTooltip text="Enter investigation notes that will be included in the STR narrative. Include: what triggered the investigation, key findings, accounts of concern, and recommended action. FIU-India reviewers read this section carefully." /></label>
              <textarea
                value={caseNotes}
                onChange={(e) => setCaseNotes(e.target.value)}
                placeholder="Additional notes for the STR report..."
                rows={3}
                className="w-full bg-[#1a2332] border border-slate-600 text-white rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none resize-none"
              />
            </div>

            {/* Submit */}
            <div className="flex items-center gap-2 mb-1">
              <InfoTooltip text="The evidence pack contains: case summary, account profiles, transaction history, risk scores, detected patterns, and a pre-drafted STR narrative. Download as JSON for your records or PDF to attach to the FIU-India STR filing." />
              <span className="text-xs text-slate-500">Generates a complete FIU-IND compliant evidence pack</span>
            </div>
            <button
              onClick={handleSubmit}
              disabled={selectedIds.size === 0 || generating}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
            >
              {generating ? "Generating..." : "Generate Evidence Pack"}
            </button>
          </Card>
        </div>

        {/* Cases History */}
        <div className="space-y-4">
          <Card>
            <h2 className="text-lg font-semibold text-white mb-3">Cases History</h2>
            {cases.length === 0 ? (
              <p className="text-sm text-slate-500">No cases generated yet</p>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {cases.map((c, i) => (
                  <div
                    key={i}
                    onClick={() => setResult(c)}
                    className="p-3 rounded-lg bg-[#0b1120] border border-slate-700/50 hover:border-blue-500/50 cursor-pointer transition-colors"
                  >
                    <p className="text-sm text-white font-mono">{c.case_id}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-slate-500">{new Date(c.generated_at).toLocaleString()}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="info">{c.accounts_count} accounts</Badge>
                      <Badge>{c.pattern_type}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Results Panel */}
      {result && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Evidence Pack: {result.case_id}</h2>
            <div className="flex gap-2">
              <button
                onClick={downloadPdf}
                className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                Download PDF
              </button>
              <button
                onClick={downloadJson}
                className="bg-slate-700 hover:bg-slate-600 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                Download JSON
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Case ID</p>
              <p className="text-sm text-white font-mono mt-1">{result.case_id}</p>
            </div>
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Generated At</p>
              <p className="text-sm text-white mt-1">{new Date(result.generated_at).toLocaleString()}</p>
            </div>
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Accounts Investigated</p>
              <p className="text-sm text-white mt-1">{result.accounts_count}</p>
            </div>
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Total Transactions</p>
              <p className="text-sm text-white mt-1">{summary?.total_transactions as number ?? "—"}</p>
            </div>
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Total Amount</p>
              <p className="text-sm text-white mt-1">{typeof summary?.total_amount === "number" ? formatINR(summary.total_amount as number) : "—"}</p>
            </div>
            <div className="bg-[#0b1120] rounded-lg p-3 border border-slate-700/50">
              <p className="text-xs text-slate-500">Max Risk Score</p>
              <p className="text-sm text-red-400 font-bold mt-1">{summary?.max_risk_score as number ?? "—"}</p>
            </div>
          </div>

          {/* Summary Preview — structured for compliance officer review */}
          {summary && (
            <div className="mt-4 bg-[#0b1120] rounded-lg p-4 border border-slate-700/50">
              <h3 className="text-sm font-medium text-slate-400 mb-3">Case Summary</h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
                <div>
                  <span className="text-slate-500 block mb-0.5">Suspicious Pattern</span>
                  <span className="text-slate-200 font-medium">{(summary.pattern_type as string) ?? result.pattern_type ?? "—"}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-0.5">Accounts Investigated</span>
                  <span className="text-slate-200 font-medium">{(summary.accounts_investigated as number) ?? result.accounts_count ?? "—"}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-0.5">Transactions Reviewed</span>
                  <span className="text-slate-200 font-medium">{(summary.total_transactions as number) ?? "—"}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-0.5">Total Suspicious Flow</span>
                  <span className="text-slate-200 font-medium">
                    {typeof summary.total_amount === "number"
                      ? `₹${(summary.total_amount as number).toLocaleString("en-IN")}`
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-0.5">Max Risk Score</span>
                  <span className="text-red-400 font-bold">{(summary.max_risk_score as number) ?? "—"}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-0.5">Report Reference</span>
                  <span className="text-slate-200 font-mono">{result.case_id}</span>
                </div>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
