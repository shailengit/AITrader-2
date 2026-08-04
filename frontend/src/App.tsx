import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import QueryProvider from './components/QueryProvider'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/layout/Layout'
import Welcome from './pages/Welcome'
import CommandCenter from './pages/CommandCenter'
import SectorRotation from './pages/SectorRotation'
import ScreenerBuilder from './pages/app/ScreenerBuilder'
import ChartView from './pages/app/ScreenerBuilder/ChartView'
import QuantGen from './pages/QuantGen'
import EarningsCalendar from './pages/EarningsCalendar'
import Markov from './pages/Markov'
import MarkovChartView from './pages/Markov/MarkovChartView'
import CoachIndex from './pages/Coach'
import CoachTrades from './pages/Coach/trades'
import StrategyLabPage from './pages/StrategyLab'
import TerminalPage from './pages/Terminal'
import Hypotheses from './pages/Hypotheses'

function App() {
  return (
    <QueryProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={
            <ErrorBoundary>
              <CommandCenter />
            </ErrorBoundary>
          } />
          <Route path="welcome" element={
            <ErrorBoundary>
              <Welcome />
            </ErrorBoundary>
          } />
          <Route element={<Layout />}>
            <Route path="sectors" element={
              <ErrorBoundary>
                <SectorRotation />
              </ErrorBoundary>
            } />
            <Route path="screener" element={
              <Navigate to="/screener/build" replace />
            } />
            <Route path="screener/build" element={
              <ErrorBoundary>
                <ScreenerBuilder />
              </ErrorBoundary>
            } />
            <Route path="screener/build/chart/:ticker" element={
              <ErrorBoundary>
                <ChartView />
              </ErrorBoundary>
            } />
            <Route path="earnings" element={
              <ErrorBoundary>
                <EarningsCalendar />
              </ErrorBoundary>
            } />
            <Route path="quantgen/*" element={
              <ErrorBoundary>
                <QuantGen />
              </ErrorBoundary>
            } />
            <Route path="markov" element={
              <ErrorBoundary>
                <Markov />
              </ErrorBoundary>
            } />
            <Route path="markov/chart/:ticker" element={
              <ErrorBoundary>
                <MarkovChartView />
              </ErrorBoundary>
            } />
            <Route path="coach" element={
              <ErrorBoundary>
                <CoachIndex />
              </ErrorBoundary>
            } />
            <Route path="coach/trades" element={
              <ErrorBoundary>
                <CoachTrades />
              </ErrorBoundary>
            } />
            <Route path="strategy-lab" element={
              <ErrorBoundary>
                <StrategyLabPage />
              </ErrorBoundary>
            } />
            <Route path="terminal" element={
              <ErrorBoundary>
                <TerminalPage />
              </ErrorBoundary>
            } />
            <Route path="hypotheses" element={<ErrorBoundary><Hypotheses /></ErrorBoundary>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  )
}

export default App
