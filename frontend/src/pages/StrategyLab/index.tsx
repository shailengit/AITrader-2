import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { StepSidebar } from "../../components/strategy-lab/StepSidebar";
import { StepBacktest } from "./StepBacktest";
import { StepDeploy } from "./StepDeploy";
import { StepLibrary } from "./StepLibrary";
import { useActiveBatch } from "../../hooks/useActiveBatch";
import "../../components/strategy-lab/lab.css";

const STEPS = [
  { id: 0, label: "Library", meta: "Saved" },
  { id: 1, label: "Backtest", meta: "Run" },
  { id: 2, label: "Deploy", meta: "Ship" },
] as const;

export default function StrategyLabPage() {
  const [activeStep, setActiveStep] = useState<number>(0);
  const [selectedStrategyPath, setSelectedStrategyPath] = useState<string | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const { batch } = useActiveBatch();

  // If there's an active batch in sessionStorage (after navigating away and
  // back, or a refresh), default to the Backtest tab for that strategy so the
  // running batch + results are immediately visible instead of landing on the
  // Library. Only applies on mount (don't override an in-progress selection).
  useEffect(() => {
    if (batch?.strategyClassPath && !selectedStrategyPath) {
      setSelectedStrategyPath(batch.strategyClassPath);
      setActiveStep(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.strategyClassPath]);

  const handleSelectStrategy = (path: string) => {
    setSelectedStrategyPath(path);
    setActiveStep(1);
  };

  const handleWinnerPicked = (experimentId: string) => {
    setSelectedExperimentId(experimentId);
    setActiveStep(2);
  };

  const handleSelectStep = (stepId: number) => {
    if (stepId === 0) { setActiveStep(0); return; }
    if (stepId === 1 && !selectedStrategyPath) return;
    if (stepId === 2 && !selectedExperimentId) return;
    setActiveStep(stepId);
  };

  return (
    <div className="slab flex h-full min-h-[calc(100vh-4rem)]">
      <StepSidebar
        steps={STEPS.map((s) => ({
          id: s.id,
          label: s.label,
          meta: s.meta,
          completed: s.id < activeStep,
          active: s.id === activeStep,
        }))}
        onSelect={handleSelectStep}
        sessionName={selectedStrategyPath ? selectedStrategyPath.split("/").pop() : undefined}
      />
      <main className="flex-1 overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
        >
          {/* All steps stay mounted so their state (form inputs, fetched
              data, running batch) is preserved when switching tabs. Inactive
              steps are hidden with display:none rather than unmounted. Each
              step is keyed by strategy so selecting a different strategy
              resets it, while tab switches keep the same key and state. */}
          <div style={{ display: activeStep === 0 ? "block" : "none" }}>
            <StepLibrary onSelectStrategy={handleSelectStrategy} />
          </div>
          {selectedStrategyPath && (
            <div style={{ display: activeStep === 1 ? "block" : "none" }}>
              <StepBacktest
                key={selectedStrategyPath}
                strategyClassPath={selectedStrategyPath}
                onWinnerPicked={handleWinnerPicked}
                onSelectStrategy={handleSelectStrategy}
              />
            </div>
          )}
          {selectedStrategyPath && selectedExperimentId && (
            <div style={{ display: activeStep === 2 ? "block" : "none" }}>
              <StepDeploy
                key={selectedStrategyPath}
                strategyClassPath={selectedStrategyPath}
                experimentId={selectedExperimentId}
                onDeployed={() => {}}
              />
            </div>
          )}
        </motion.div>
      </main>
    </div>
  );
}
