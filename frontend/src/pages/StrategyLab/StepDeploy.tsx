import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Rocket, AlertCircle, History, FileCode, RotateCcw } from "lucide-react";
import { strategyLabApi } from "../../lib/strategyLab";

interface StepDeployProps {
  strategyClassPath: string;
  experimentId: string;
  onDeployed: () => void;
}

export function StepDeploy({ strategyClassPath, experimentId, onDeployed }: StepDeployProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sourceHypothesisIds, setSourceHypothesisIds] = useState("");
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

  const strategyName = strategyClassPath.split("/").pop()?.replace(".py", "") || "Unknown";

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
                background: "var(--slab-ink-3)",
                border: "1px solid var(--slab-rule)",
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
                  updates alpaca_runner.py import
                </div>
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
                  background: "var(--slab-ink-2)",
                  color: "var(--slab-paper)",
                  border: "1px solid var(--slab-rule)",
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
                disabled={deployMut.isPending}
                className="slab-btn slab-btn--terminal"
                style={{ padding: "12px 24px" }}
              >
                <Rocket size={12} />
                {deployMut.isPending ? "Deploying…" : "Deploy to paper"}
              </button>
              {deployMut.isError && (
                <span className="slab-mono slab-mono--sm slab-mono--rose" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertCircle size={12} />
                  {String((deployMut.error as Error)?.message ?? "Deploy failed")}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Deploy result */}
        <AnimatePresence>
          {deployMut.isSuccess && deployMut.data && (
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
                    {deployMut.data.class_name}
                  </div>
                </div>
                <div>
                  <div className="slab-eyebrow">File path</div>
                  <div className="slab-mono slab-mono--md slab-mono--dim" style={{ marginTop: 4 }}>
                    <FileCode size={11} style={{ verticalAlign: "middle", marginRight: 6 }} />
                    {deployMut.data.class_file_path}
                  </div>
                </div>
                <div
                  style={{
                    padding: 12,
                    background: "var(--slab-ink-3)",
                    border: "1px solid var(--slab-rule)",
                  }}
                >
                  <div className="slab-mono slab-mono--sm slab-mono--dim">
                    The Alpaca runner is using this class. To trade live, run:
                  </div>
                  <pre
                    className="slab-mono slab-mono--md"
                    style={{
                      color: "var(--slab-gold)",
                      marginTop: 8,
                      background: "var(--slab-ink-2)",
                      padding: "8px 12px",
                      border: "1px solid var(--slab-rule)",
                    }}
                  >
                    python -m app.services.alpaca_runner
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
                      <td style={{ color: d.is_active ? "var(--slab-gold)" : "var(--slab-paper-dim)" }}>
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
            onCancel={() => setConfirmOpen(false)}
            onConfirm={() => {
              setConfirmOpen(false);
              deployMut.mutate();
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

function ConfirmModal({
  strategyName,
  onCancel,
  onConfirm,
}: {
  strategyName: string;
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
            This will update <span className="slab-mono">alpaca_runner.py</span> to
            import <span className="slab-mono" style={{ color: "var(--slab-gold)" }}>{strategyName}</span>.
            Any active deployment will be deactivated.
          </p>
          <div
            style={{
              padding: 12,
              background: "var(--slab-ink-3)",
              border: "1px solid var(--slab-rule)",
            }}
          >
            <div className="slab-eyebrow">Strategy</div>
            <div className="slab-mono slab-mono--md slab-mono--gold" style={{ marginTop: 4 }}>
              {strategyName}
            </div>
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
