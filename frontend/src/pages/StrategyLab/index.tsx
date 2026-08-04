import { useState } from "react";
import { motion } from "framer-motion";
import { StepSidebar } from "../../components/strategy-lab/StepSidebar";
import { StepBacktest } from "./StepBacktest";
import { StepDeploy } from "./StepDeploy";
import { StepLibrary } from "./StepLibrary";
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
          {activeStep === 0 ? (
            <StepLibrary key="step-0" onSelectStrategy={handleSelectStrategy} />
          ) : activeStep === 1 && selectedStrategyPath ? (
            <StepBacktest
              key={`step-1-${selectedStrategyPath}`}
              strategyClassPath={selectedStrategyPath}
              onWinnerPicked={handleWinnerPicked}
            />
          ) : activeStep === 2 && selectedStrategyPath && selectedExperimentId ? (
            <StepDeploy
              key={`step-2-${selectedStrategyPath}`}
              strategyClassPath={selectedStrategyPath}
              experimentId={selectedExperimentId}
              onDeployed={() => {}}
            />
          ) : (
            <StepNoStrategy key="step-no-strategy" />
          )}
        </motion.div>
      </main>
    </div>
  );
}

function StepNoStrategy() {
  return (
    <div className="slab-page-body">
      <div className="slab-eyebrow slab-eyebrow--gold mb-3">// 01 · Backtest</div>
      <h1 className="slab-display slab-h2 mb-3">Select a strategy first.</h1>
      <p className="slab-lede">
        Pick a strategy from the library or use the terminal to generate one with Claude Code.
        Generated strategies live in <span className="slab-mono">backend/app/services/strategies/</span>.
      </p>
    </div>
  );
}
