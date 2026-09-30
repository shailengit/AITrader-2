import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Rocket, AlertCircle, History, FileCode, RotateCcw, RefreshCw } from "lucide-react";
import { strategyLabApi, type AccountDeployInfo } from "../../lib/strategyLab";

interface StepDeployProps {
  strategyClassPath: string;
  experimentId: string;
  onDeployed: () => void;
}

export function StepDeploy({ strategyClassPath, experimentId, onDeployed }: StepDeployProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sourceHypothesisIds, setSourceHypothesisIds] = useState("");
  const [selectedPrefix, setSelectedPrefix] = useState<string | null>(null);
  const qc = useQueryClient();

  const deployMut = useMutation({
    mutationFn: () =>
      strategyLabApi.deployStrategyClass(
        strategyClassPath,
        experimentId,
        sourceHypothesisIds
          .split(/[\s,]+/)
          .map((s) => s.trim())
          .filter(Boolean)
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-lab-deployments"] });
      onDeployed();
    },
  });

  const deployToAccountMut = useMutation({
    mutationFn: (prefix: string) =>
      strategyLabApi.deployStrategyToAccount(strategyClassPath, prefix),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-lab-accounts"] });
      qc.invalidateQueries({ queryKey: ["strategy-lab-deployments"] });
      onDeployed();
    },
  });

  const accounts = useQuery({
    queryKey: ["strategy-lab-accounts"],
    queryFn: () => strategyLabApi.listAccounts(),
  });

  const deployments = useQuery({
    queryKey: ["strategy-lab-deployments"],
    queryFn: () => strategyLabApi.listDeployments(),
  });

  const rollback = useMutation({
    mutationFn: (deploymentId: string) => strategyLabApi.rollbackDeployment(deploymentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-lab-deployments"] });
    },
  });

  // ── Account admin: liquidate / update keys ──
  const [liquidatingPrefix, setLiquidatingPrefix] = useState<string | null>(null);
  const [updateKeysPrefix, setUpdateKeysPrefix] = useState<string | null>(null);
  const [keyForm, setKeyForm] = useState({ api_key: "", secret_key: "", account_number: "" });
  const [keyMsg, setKeyMsg] = useState<string | null>(null);

  const liquidateMut = useMutation({
    mutationFn: (prefix: string) => strategyLabApi.liquidateAccount(prefix),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-lab-accounts"] });
      setLiquidatingPrefix(null);
    },
    onError: (e) => setKeyMsg(`Liquidate failed: ${e instanceof Error ? e.message : "error"}`),
  });

  const updateKeysMut = useMutation({
    mutationFn: (prefix: string) =>
      strategyLabApi.updateAccountKeys(prefix, {
        api_key: keyForm.api_key,
        secret_key: keyForm.secret_key,
        account_number: keyForm.account_number || undefined,
      }),
    onSuccess: (r) => {
      setKeyMsg(`Keys updated — account ${r.account_number}.`);
      setUpdateKeysPrefix(null);
      setKeyForm({ api_key: "", secret_key: "", account_number: "" });
      qc.invalidateQueries({ queryKey: ["strategy-lab-accounts"] });
    },
    onError: (e) => setKeyMsg(`Update failed: ${e instanceof Error ? e.message : "error"}`),
  });

  const strategyName = strategyClassPath.split("/").pop()?.replace(".py", "") || "Unknown";

  const handleDeployToAccount = () => {
    if (!selectedPrefix) return;
    setConfirmOpen(false);
    deployToAccountMut.mutate(selectedPrefix);
  };

  return (
    <>
      <div className="slab-page-head">
        <div>
          <div className="slab-eyebrow slab-eyebrow--gold">// 02 · Deploy</div>
          <h1 className="slab-page-head__title">Ship to paper.</h1>
          <p className="slab-page-head__lede">
            Deploy the winning strategy to your Alpaca paper account.
            Previous deployments are deactivated and can be rolled back.
          </p>
        </div>
        <div className="slab-page-head__meta">
          <span>{strategyName}</span>
          <span className="slab-mono slab-mono--gold">READY</span>
        </div>
      </div>

      <div className="slab-page-body">
        <div className="slab-corner-marks slab-panel" style={{ maxWidth: 920, position: "relative" }}>
          <div className="slab-panel__head">
            <span className="slab-eyebrow slab-eyebrow--gold">// Selected strategy</span>
            <span className="slab-mono slab-mono--xs slab-mono--dim">{strategyClassPath}</span>
          </div>
          <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
                padding: 14,
                background: "var(--surface-raised)",
                border: "1px solid var(--border)",
              }}
            >
              <div>
                <div className="slab-eyebrow">Target</div>
                <div className="slab-mono slab-mono--md slab-mono--gold" style={{ marginTop: 4 }}>
                  📄 Paper account
                </div>
              </div>
              <div>
                <div className="slab-eyebrow">Side effects</div>
                <div className="slab-mono slab-mono--md slab-mono--dim" style={{ marginTop: 4 }}>
                  swaps the strategy on the chosen account
                </div>
              </div>
            </div>

            {/* Account selector */}
            <div>
              <div className="slab-eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                Which account to replace?
                <button
                  type="button"
                  onClick={() => accounts.refetch()}
                  className="slab-btn slab-btn--xs"
                  title="Refresh account equity"
                  style={{ padding: "2px 6px" }}
                >
                  <RefreshCw size={9} />
                </button>
              </div>
              <div className="slab-mono slab-mono--xs slab-mono--dim" style={{ marginTop: 4 }}>
                Pick the account this strategy will trade on. The account number and balance are preserved;
                only the strategy changes.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 10 }}>
                {accounts.isLoading ? (
                  <div className="slab-mono slab-mono--sm slab-mono--dim">Loading accounts…</div>
                ) : !accounts.data || accounts.data.length === 0 ? (
                  <div className="slab-mono slab-mono--sm slab-mono--faint">No accounts configured.</div>
                ) : (
                  accounts.data.map((a: AccountDeployInfo) => (
                    <div
                      key={a.prefix}
                      onClick={() => setSelectedPrefix(a.prefix)}
                      style={{
                        textAlign: "left",
                        padding: 12,
                        cursor: "pointer",
                        background: selectedPrefix === a.prefix ? "var(--accent-glow)" : "var(--surface-raised)",
                        border: `1px solid ${selectedPrefix === a.prefix ? "var(--accent)" : "var(--border)"}`,
                        color: "var(--foreground)",
                        fontFamily: "inherit",
                        borderRadius: 8,
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span className="slab-mono slab-mono--sm" style={{ fontWeight: 600, color: "var(--accent)" }}>
                          {a.label}
                        </span>
                        {a.needs_reset && (
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
                            background: "var(--bad-bg, rgba(255,80,80,0.15))", color: "var(--bad)",
                            whiteSpace: "nowrap",
                          }}>NEEDS RESET</span>
                        )}
                      </div>
                      <div className="slab-mono slab-mono--xs slab-mono--dim">{a.account_number}</div>
                      <div className="slab-mono slab-mono--md">
                        {a.configured && a.equity != null ? `$${a.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
                      </div>
                      <div className="slab-mono slab-mono--xs slab-mono--dim">
                        {a.configured ? `${a.n_positions ?? 0} positions` : (a.reason ?? "not configured")}
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
                        <button
                          type="button"
                          className="slab-btn slab-btn--xs slab-btn--ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm(`Liquidate account ${a.label}? This cancels all orders and closes all positions.`)) {
                              setLiquidatingPrefix(a.prefix);
                              liquidateMut.mutate(a.prefix);
                            }
                          }}
                          disabled={liquidatingPrefix === a.prefix}
                          title="Cancel all orders and close all positions"
                        >
                          {liquidatingPrefix === a.prefix ? "Liquidating…" : "Liquidate"}
                        </button>
                        <button
                          type="button"
                          className="slab-btn slab-btn--xs slab-btn--ghost"
                          onClick={(e) => { e.stopPropagation(); setUpdateKeysPrefix(a.prefix); setKeyMsg(null); }}
                          title="Paste new API key/secret (e.g. after creating a new account)"
                        >
                          Update keys
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div>
              <div className="slab-eyebrow">Source hypotheses</div>
              <div className="slab-mono slab-mono--xs slab-mono--dim" style={{ marginTop: 4 }}>
                Optional — paste hypothesis IDs (comma/space/newline separated) from the Terminal banner
                to link this strategy back to its source hypotheses.
              </div>
              <textarea
                value={sourceHypothesisIds}
                onChange={(e) => setSourceHypothesisIds(e.target.value)}
                placeholder="e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6 9b2c…"
                rows={2}
                style={{
                  width: "100%",
                  marginTop: 8,
                  padding: "10px 12px",
                  background: "var(--surface)",
                  color: "var(--foreground)",
                  border: "1px solid var(--border)",
                  fontFamily: "var(--slab-mono, monospace)",
                  fontSize: 13,
                  resize: "vertical",
                }}
              />
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={deployMut.isPending || deployToAccountMut.isPending || !selectedPrefix}
                className="slab-btn slab-btn--terminal"
                style={{ padding: "12px 24px" }}
              >
                <Rocket size={12} />
                {deployToAccountMut.isPending ? "Deploying…" : "Deploy to paper"}
              </button>
              {(deployMut.isError || deployToAccountMut.isError) && (
                <span className="slab-mono slab-mono--sm slab-mono--rose" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertCircle size={12} />
                  {String((deployToAccountMut.error ?? deployMut.error as Error)?.message ?? "Deploy failed")}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Deploy result */}
        <AnimatePresence>
          {(deployMut.isSuccess || deployToAccountMut.isSuccess) && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="slab-corner-marks slab-panel"
              style={{ maxWidth: 920, marginTop: 24, position: "relative" }}
            >
              <div className="slab-panel__head">
                <span className="slab-eyebrow slab-eyebrow--gold">// Live</span>
                <span className="slab-status slab-status--terminal">
                  <span className="slab-status__dot" />
                  Deployed
                </span>
              </div>
              <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div>
                  <div className="slab-eyebrow">Class</div>
                  <div className="slab-mono slab-mono--xl slab-mono--terminal" style={{ marginTop: 4 }}>
                    {deployToAccountMut.data?.class_name ?? deployMut.data?.class_name}
                  </div>
                </div>
                {deployToAccountMut.data && (
                  <div>
                    <div className="slab-eyebrow">Account</div>
                    <div className="slab-mono slab-mono--md slab-mono--dim" style={{ marginTop: 4 }}>
                      prefix {deployToAccountMut.data.account_prefix} · {deployToAccountMut.data.label}
                    </div>
                  </div>
                )}
                <div>
                  <div className="slab-eyebrow">File path</div>
                  <div className="slab-mono slab-mono--md slab-mono--dim" style={{ marginTop: 4 }}>
                    <FileCode size={11} style={{ verticalAlign: "middle", marginRight: 6 }} />
                    {deployToAccountMut.data?.strategy_class_path ?? deployMut.data?.class_file_path}
                  </div>
                </div>
                <div
                  style={{
                    padding: 12,
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div className="slab-mono slab-mono--sm slab-mono--dim">
                    The daily scheduler will run this strategy on the chosen account at 8 PM. To run it now:
                  </div>
                  <pre
                    className="slab-mono slab-mono--md"
                    style={{
                      color: "var(--accent)",
                      marginTop: 8,
                      background: "var(--surface)",
                      padding: "8px 12px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {deployToAccountMut.data
                      ? `python -m app.services.alpaca_runner_by_name ${deployToAccountMut.data.module_name} ${deployToAccountMut.data.account_prefix}`
                      : "python -m app.services.alpaca_runner"}
                  </pre>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* History */}
        <div className="slab-panel" style={{ maxWidth: 920, marginTop: 32 }}>
          <div className="slab-panel__head">
            <span className="slab-eyebrow slab-eyebrow--gold">
              <History size={11} style={{ verticalAlign: "middle", marginRight: 6 }} />
              Deployment history
            </span>
            <span className="slab-mono slab-mono--xs slab-mono--dim">
              {deployments.data?.length ?? 0} records
            </span>
          </div>
          <div style={{ maxHeight: 360, overflow: "auto" }}>
            {deployments.isLoading ? (
              <div style={{ padding: 16 }} className="slab-mono slab-mono--sm slab-mono--dim">Loading…</div>
            ) : !deployments.data || deployments.data.length === 0 ? (
              <div style={{ padding: 16 }} className="slab-mono slab-mono--sm slab-mono--faint">
                No deployments yet.
              </div>
            ) : (
              <table className="slab-table">
                <thead>
                  <tr>
                    <th>Class</th>
                    <th>Deployed at</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {deployments.data.map((d: any) => (
                    <tr key={d.deployment_id} className={d.is_active ? "slab-table__row--winner" : ""}>
                      <td style={{ color: d.is_active ? "var(--accent)" : "var(--muted)" }}>
                        {d.class_name}
                      </td>
                      <td>{d.deployed_at?.slice(0, 19).replace("T", " ") ?? "—"}</td>
                      <td>
                        {d.is_active ? (
                          <span className="slab-tag slab-tag--gold">ACTIVE</span>
                        ) : (
                          <span className="slab-tag">rolled back</span>
                        )}
                      </td>
                      <td>
                        {d.is_active && (
                          <button
                            type="button"
                            onClick={() => rollback.mutate(d.deployment_id)}
                            disabled={rollback.isPending}
                            className="slab-btn slab-btn--xs"
                          >
                            <RotateCcw size={9} />
                            {rollback.isPending ? "rolling back…" : "rollback"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Confirm modal */}
      <AnimatePresence>
        {confirmOpen && (
          <ConfirmModal
            strategyName={strategyName}
            accountLabel={accounts.data?.find((a) => a.prefix === selectedPrefix)?.label}
            onCancel={() => setConfirmOpen(false)}
            onConfirm={handleDeployToAccount}
          />
        )}
      </AnimatePresence>

      {updateKeysPrefix && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center",
          justifyContent: "center", background: "rgba(0,0,0,0.5)",
        }} onClick={() => setUpdateKeysPrefix(null)}>
          <div
            className="slab-panel"
            style={{ maxWidth: 480, width: "100%", margin: 16 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="slab-panel__head">
              <span className="slab-eyebrow slab-eyebrow--gold">// Update account keys</span>
              <span className="slab-mono slab-mono--xs slab-mono--dim">prefix {updateKeysPrefix}</span>
            </div>
            <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <p className="slab-prose" style={{ fontSize: 12 }}>
                Paste the new API key and secret (e.g. after creating a new paper account in the
                Alpaca dashboard). The account number is auto-fetched from Alpaca using the new keys —
                leave it blank unless you want to set it explicitly.
              </p>
              <div className="slab-field">
                <label className="slab-field__label">API key</label>
                <input
                  className="slab-input"
                  value={keyForm.api_key}
                  onChange={(e) => setKeyForm({ ...keyForm, api_key: e.target.value })}
                  placeholder="PK…"
                  autoComplete="off"
                />
              </div>
              <div className="slab-field">
                <label className="slab-field__label">Secret key</label>
                <input
                  className="slab-input"
                  value={keyForm.secret_key}
                  onChange={(e) => setKeyForm({ ...keyForm, secret_key: e.target.value })}
                  placeholder="…"
                  type="password"
                  autoComplete="off"
                />
              </div>
              <div className="slab-field">
                <label className="slab-field__label">Account number (optional — auto-fetched)</label>
                <input
                  className="slab-input"
                  value={keyForm.account_number}
                  onChange={(e) => setKeyForm({ ...keyForm, account_number: e.target.value })}
                  placeholder="PA…"
                />
              </div>
              {keyMsg && (
                <div className="slab-mono slab-mono--sm" style={{ color: "var(--accent)" }}>{keyMsg}</div>
              )}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <button type="button" className="slab-btn" onClick={() => setUpdateKeysPrefix(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="slab-btn slab-btn--terminal"
                  disabled={updateKeysMut.isPending || !keyForm.api_key || !keyForm.secret_key}
                  onClick={() => updateKeysMut.mutate(updateKeysPrefix)}
                >
                  {updateKeysMut.isPending ? "Saving…" : "Save keys"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ConfirmModal({
  strategyName,
  accountLabel,
  onCancel,
  onConfirm,
}: {
  strategyName: string;
  accountLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
      onClick={onCancel}
    >
      <motion.div
        initial={{ y: 8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 8, opacity: 0 }}
        className="slab-corner-marks slab-panel"
        style={{ position: "relative", width: "100%", maxWidth: 520 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="slab-panel__head">
          <span className="slab-eyebrow slab-eyebrow--gold">// Confirm deploy</span>
          <span className="slab-mono slab-mono--xs slab-mono--dim">paper only</span>
        </div>
        <div className="slab-panel__body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <p className="slab-prose">
            This will swap <span className="slab-mono" style={{ color: "var(--accent)" }}>{strategyName}</span> onto
            account <span className="slab-mono" style={{ color: "var(--accent)" }}>{accountLabel ?? "selected"}</span>.
            The account number and balance are preserved; only the strategy changes.
          </p>
          <div
            style={{
              padding: 12,
              background: "var(--surface-raised)",
              border: "1px solid var(--border)",
            }}
          >
            <div className="slab-eyebrow">Strategy</div>
            <div className="slab-mono slab-mono--md slab-mono--gold" style={{ marginTop: 4 }}>
              {strategyName}
            </div>
            {accountLabel && (
              <>
                <div className="slab-eyebrow" style={{ marginTop: 10 }}>Account</div>
                <div className="slab-mono slab-mono--md slab-mono--dim" style={{ marginTop: 4 }}>
                  {accountLabel}
                </div>
              </>
            )}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button type="button" onClick={onCancel} className="slab-btn">
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className="slab-btn slab-btn--terminal"
            >
              <Rocket size={11} />
              Deploy
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
