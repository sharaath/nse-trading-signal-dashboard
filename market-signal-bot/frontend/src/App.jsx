import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { 
  ShieldCheck, ToggleLeft, ToggleRight, Radio, RefreshCw, BarChart2, 
  Zap, Settings, BookOpen, Cpu, Play, CheckCircle, AlertOctagon, TrendingUp 
} from 'lucide-react';
import OptionChainTable from './OptionChainTable';

let API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
if (API_BASE && !API_BASE.startsWith("http")) {
  API_BASE = `https://${API_BASE}`;
}

export default function App() {
  const [latestSignals, setLatestSignals] = useState([]);
  const [optionMomentum, setOptionMomentum] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState("^NSEI");
  const [history, setHistory] = useState([]);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("checking");
  
  // New States
  const [activeTrades, setActiveTrades] = useState([]);
  const [tradeJournal, setTradeJournal] = useState([]);
  const [systemSettings, setSystemSettings] = useState({
    max_daily_loss: "5000",
    max_daily_trades: "5",
    max_simultaneous_trades: "2",
    min_risk_reward: "2.0",
    signal_threshold: "75",
    max_entry_chase_pct: "5.0",
    slippage_pct: "0.5",
    weight_trend_bias: "15",
    weight_liquidity_sweep: "20",
    weight_mss: "20",
    weight_displacement: "10",
    weight_fvg: "10",
    weight_vwap: "10",
    weight_options_pcr: "10",
    weight_ml_prob: "5",
  });
  
  const [backtestSymbol, setBacktestSymbol] = useState("NIFTY");
  const [backtestDays, setBacktestDays] = useState(15);
  const [backtestResult, setBacktestResult] = useState(null);
  const [btLoading, setBtLoading] = useState(false);
  
  const [mlSymbol, setMlSymbol] = useState("NIFTY");
  const [mlMsg, setMlMsg] = useState("");
  const [mlLoading, setMlLoading] = useState(false);

  // Health Status and Performance metrics states
  const [healthStatus, setHealthStatus] = useState({
    api: "HEALTHY",
    database: "HEALTHY",
    worker: "STOPPED",
    data_provider: "CONNECTED",
    telegram: "CONNECTED",
    mode: "PAPER"
  });
  const [analyticsPerf, setAnalyticsPerf] = useState(null);
  const [analyticsBreakdown, setAnalyticsBreakdown] = useState(null);

  const fetchHealthStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealthStatus(data);
      }
    } catch (e) {
      console.error("Error fetching health status", e);
    }
  };

  const fetchAnalytics = async () => {
    try {
      const res = await fetch(`${API_BASE}/analytics/performance`);
      if (res.ok) {
        const data = await res.json();
        setAnalyticsPerf(data);
      }
      const res2 = await fetch(`${API_BASE}/analytics/breakdown`);
      if (res2.ok) {
        const data2 = await res2.json();
        setAnalyticsBreakdown(data2);
      }
    } catch (e) {
      console.error("Error fetching analytics", e);
    }
  };

  const fetchLatest = async () => {
    try {
      const res = await fetch(`${API_BASE}/signals/latest`);
      if (res.ok) {
        const data = await res.json();
        setLatestSignals(data);
      }
    } catch (e) {
      console.error("Error fetching latest signals", e);
    }
  };

  const fetchOptionMomentum = async () => {
    try {
      const res = await fetch(`${API_BASE}/options/momentum?limit=6`);
      if (res.ok) {
        const data = await res.json();
        setOptionMomentum(data);
      }
    } catch (e) {
      console.error("Error fetching option momentum alerts", e);
    }
  };

  const fetchHistory = async (symbol) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/signals/history?symbol=${symbol}&days=7`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data.reverse());
      }
    } catch (e) {
      console.error("Error fetching history", e);
    } finally {
      setLoading(false);
    }
  };

  const fetchActiveTrades = async () => {
    try {
      const res = await fetch(`${API_BASE}/trades/active`);
      if (res.ok) {
        const data = await res.json();
        setActiveTrades(data);
      }
    } catch (e) {
      console.error("Error fetching active trades", e);
    }
  };

  const fetchTradeJournal = async () => {
    try {
      const res = await fetch(`${API_BASE}/trades/history`);
      if (res.ok) {
        const data = await res.json();
        setTradeJournal(data);
      }
    } catch (e) {
      console.error("Error fetching trade journal", e);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/settings`);
      if (res.ok) {
        const data = await res.json();
        if (Object.keys(data).length > 0) {
          setSystemSettings(prev => ({ ...prev, ...data }));
        }
      }
    } catch (e) {
      console.error("Error fetching settings", e);
    }
  };

  const updateSetting = async (key, val) => {
    try {
      await fetch(`${API_BASE}/admin/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value: String(val) })
      });
      setSystemSettings(prev => ({ ...prev, [key]: val }));
    } catch (e) {
      console.error("Error updating setting", e);
    }
  };

  const handleRunBacktest = async () => {
    setBtLoading(true);
    setBacktestResult(null);
    try {
      const res = await fetch(`${API_BASE}/backtest/run?symbol=${backtestSymbol}&days=${backtestDays}`);
      if (res.ok) {
        const data = await res.json();
        setBacktestResult(data);
      }
    } catch (e) {
      console.error("Error running backtest", e);
    } finally {
      setBtLoading(false);
    }
  };

  const handleTrainML = async () => {
    setMlLoading(true);
    setMlMsg("");
    try {
      const res = await fetch(`${API_BASE}/ml/train?symbol=${mlSymbol}&days=60`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setMlMsg(data.message);
      }
    } catch (e) {
      console.error("Error training ML model", e);
      setMlMsg("Model training failed.");
    } finally {
      setMlLoading(false);
    }
  };

  const checkHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) setStatus("connected");
      else setStatus("error");
    } catch {
      setStatus("disconnected");
    }
  };

  useEffect(() => {
    checkHealth();
    fetchHealthStatus();
    fetchLatest();
    fetchOptionMomentum();
    fetchActiveTrades();
    fetchTradeJournal();
    fetchSettings();
    fetchAnalytics();
    
    const interval = setInterval(() => {
      fetchLatest();
      fetchOptionMomentum();
      fetchActiveTrades();
      checkHealth();
      fetchHealthStatus();
      fetchAnalytics();
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchHistory(selectedTicker);
  }, [selectedTicker]);

  // Compute daily totals
  const todayRealizedPnl = tradeJournal
    .filter(t => new Date(t.exit_time).toDateString() === new Date().toDateString())
    .reduce((sum, t) => sum + t.pnl, 0.0);

  return (
    <div className="min-h-screen bg-[#090d16] text-[#e2e8f0]">
      {/* Header bar */}
      <header className="border-b border-[#1e293b] bg-[#0b0f19]/80 backdrop-blur-md px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
            <Radio className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-wider bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">MarketSignalBot</h1>
            <p className="text-xs text-sky-400 font-bold uppercase tracking-widest">PRO INDEX DERIVATIVES & SMC SCANNER</p>
          </div>
        </div>

        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-slate-400">P&L Today:</span>
            <span className={`text-xs font-black px-2 py-0.5 rounded-full ${todayRealizedPnl >= 0 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
              ₹{todayRealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-slate-400">API Status:</span>
            {status === "connected" && <span className="flex items-center text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-ping"></span>Connected</span>}
            {status === "disconnected" && <span className="text-xs text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full border border-rose-500/20">Disconnected</span>}
            {status === "checking" && <span className="text-xs text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">Checking...</span>}
          </div>
          
          <nav className="flex space-x-2">
            <button onClick={() => { setActiveTab("dashboard"); fetchActiveTrades(); }} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${activeTab === "dashboard" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}>Dashboard</button>
            <button onClick={() => { setActiveTab("journal"); fetchTradeJournal(); }} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${activeTab === "journal" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}><BookOpen className="w-3.5 h-3.5 inline mr-1" />Journal</button>
            <button onClick={() => { setActiveTab("backtest"); }} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${activeTab === "backtest" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}><Cpu className="w-3.5 h-3.5 inline mr-1" />Backtester & ML</button>
            <button onClick={() => { setActiveTab("analytics"); fetchAnalytics(); }} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${activeTab === "analytics" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}><TrendingUp className="w-3.5 h-3.5 inline mr-1" />Analytics</button>
            <button onClick={() => { setActiveTab("settings"); fetchSettings(); }} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${activeTab === "settings" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}><Settings className="w-3.5 h-3.5 inline mr-1" />Settings</button>
          </nav>
        </div>
      </header>

      {/* Prominent Safety Mode & Service Status Bar */}
      <div className="max-w-7xl mx-auto px-6 pt-6">
        <div className="flex flex-wrap gap-4 items-center justify-between bg-[#0e1726]/60 border border-[#1e293b] rounded-2xl p-4 shadow-md backdrop-blur-sm">
          <div className="flex items-center space-x-3">
            <span className="px-3 py-1 rounded-lg text-xs font-black bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
              🟡 PAPER TRADING
            </span>
            <span className="text-xs text-slate-400 font-bold uppercase tracking-wider">
              REAL ORDERS DISABLED
            </span>
          </div>
          
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs font-semibold text-slate-400">
            <div>API: <span className="text-emerald-400">HEALTHY</span></div>
            <div>DATABASE: <span className={healthStatus.database === "HEALTHY" ? "text-emerald-400" : "text-rose-400"}>{healthStatus.database}</span></div>
            <div>WORKER: <span className={healthStatus.worker === "RUNNING" ? "text-emerald-400" : "text-rose-400 animate-pulse"}>{healthStatus.worker}</span></div>
            <div>DATA FEED: <span className={healthStatus.trading_eligibility ? "text-emerald-400" : "text-rose-400 animate-pulse"}>
              {typeof healthStatus.data_provider === 'object' ? healthStatus.data_provider.overall_status : healthStatus.data_provider}
            </span></div>
            <div>TELEGRAM: <span className={healthStatus.telegram === "CONNECTED" ? "text-emerald-400" : "text-rose-400"}>{healthStatus.telegram}</span></div>
            <div>MODE: <span className="text-amber-300 font-bold">{healthStatus.mode}</span></div>
          </div>
        </div>
      </div>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        
        {/* VIEW 1: DASHBOARD */}
        {activeTab === "dashboard" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Left Column: Monitored Tickers & Opportunities */}
            <div className="lg:col-span-1 space-y-6">
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div className="flex justify-between items-center mb-4">
                  <div className="flex items-center space-x-2">
                    <BarChart2 className="w-5 h-5 text-sky-400" />
                    <h2 className="text-lg font-bold">Monitored Indices</h2>
                  </div>
                  <button onClick={fetchLatest} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors">
                    <RefreshCw className="w-4 h-4 text-slate-300" />
                  </button>
                </div>

                <div className="space-y-4">
                  {latestSignals.length > 0 ? (
                    latestSignals.map(sig => {
                      const isIdx = sig.symbol.startsWith("^") || sig.instrument_type === "INDEX";
                      return (
                        <div 
                          key={sig.id} 
                          onClick={() => setSelectedTicker(sig.symbol)}
                          className={`p-4 rounded-xl border transition-all duration-200 cursor-pointer ${selectedTicker === sig.symbol ? 'bg-sky-500/5 border-sky-500/30 shadow-md' : 'bg-slate-900/50 border-[#1e293b] hover:border-slate-700'}`}
                        >
                          <div className="flex justify-between items-start mb-2">
                            <div>
                              <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                                <span className="font-bold text-base tracking-wide text-white">{sig.symbol.replace("^", "")}</span>
                                <span className="px-1.5 py-0.5 rounded text-[8px] font-extrabold uppercase bg-purple-500/10 text-purple-400 border border-purple-500/20">INDEX</span>
                                {sig.system_mode && (
                                  <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase ${sig.system_mode === 'LIVE' ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'}`}>
                                    {sig.system_mode}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-slate-400 mt-0.5">{new Date(sig.timestamp).toLocaleTimeString()}</p>
                            </div>
                            <span className={`px-2.5 py-0.5 rounded-full text-xs font-black uppercase tracking-wider ${sig.signal === 'BUY' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : sig.signal === 'SELL' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                              {sig.signal === 'BUY' ? '🟢 BUY' : sig.signal === 'SELL' ? '🔴 SELL' : '⚪ HOLD'}
                            </span>
                          </div>
                          <div className="flex justify-between items-end mb-2 border-b border-slate-800/50 pb-2">
                            <span className="text-sm font-bold text-slate-300">Rs.{sig.price.toFixed(2)}</span>
                            {sig.signal !== 'HOLD' && <span className="text-xs text-slate-400">Mode: <span className="font-semibold text-sky-400">{sig.data_source || 'MOCK'}</span></span>}
                          </div>
                          
                          <div className="grid grid-cols-3 gap-1 text-[9px] text-slate-400 text-center mb-2">
                            <div>Strat: <strong className="text-white">{sig.strategy_score ? sig.strategy_score.toFixed(0) : '0'}/100</strong></div>
                            <div>ML: <strong className="text-sky-400">{sig.ml_probability ? sig.ml_probability.toFixed(0) : '0'}%</strong></div>
                            <div>Quality: <strong className="text-amber-400">{sig.trade_quality_score ? sig.trade_quality_score.toFixed(0) : '0'}/100</strong></div>
                          </div>

                          {/* Rejection Log */}
                          {sig.signal === 'HOLD' && sig.reject_reason && (
                            <div className="mt-2 p-2 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-[9px]">
                              <strong>NO TRADE:</strong> {sig.reject_reason}
                            </div>
                          )}

                          {/* Decision Chain logs */}
                          <div className="mt-2 border-t border-slate-800/80 pt-2 space-y-1 text-[9px] text-slate-400">
                            <div className="flex justify-between">
                              <span>Market Bias (HTF):</span>
                              <span className={`font-semibold ${sig.strategy_score >= 15 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {sig.strategy_score >= 15 ? 'BULLISH' : 'BEARISH'}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>SMC Setup:</span>
                              <span className="font-semibold text-slate-200">
                                MSS: {sig.mss_state} | Sweep: {sig.sweep_state} | FVG: {sig.fvg_state}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span>Options Conf:</span>
                              <span className={`font-semibold ${sig.option_state === 'STRONG' ? 'text-emerald-400' : 'text-amber-400'}`}>
                                {sig.option_state || 'INVALID'}
                              </span>
                            </div>
                            {sig.option_contract && sig.option_contract !== "N/A" && (
                              <div className="flex justify-between">
                                <span>Selected Strike:</span>
                                <span className="font-bold text-white">{sig.option_contract}</span>
                              </div>
                            )}
                            {sig.entry_price > 0 && (
                              <div className="flex justify-between text-slate-300">
                                <span>Entry / SL / Target 2:</span>
                                <span>₹{sig.entry_price} / ₹{sig.stop_loss} / ₹{sig.target_2}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-center py-6 text-slate-500 text-xs">No signals available.</div>
                  )}
                </div>
              </div>

              {/* Market Data Quality Panel */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl relative overflow-hidden mt-6">
                <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wide border-b border-slate-800 pb-2 mb-4">
                  Data Feed Quality Audit
                </h3>
                <div className="space-y-4 text-xs font-semibold text-slate-400">
                  <div className="flex justify-between items-center">
                    <span>Active Provider:</span>
                    <span className="text-white font-extrabold uppercase font-mono">
                      {typeof healthStatus.data_provider === 'object' ? healthStatus.data_provider.name : 'yfinance'}
                    </span>
                  </div>

                  <div className="flex justify-between items-center">
                    <span>Connection:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${healthStatus.connection === 'CONNECTED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                      {healthStatus.connection || 'DISCONNECTED'}
                    </span>
                  </div>

                  <div className="flex justify-between items-center">
                    <span>WebSocket:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${healthStatus.websocket === 'CONNECTED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                      {healthStatus.websocket || 'DISCONNECTED'}
                    </span>
                  </div>
                  
                  <div className="flex justify-between items-center">
                    <span>Data Status:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${healthStatus.trading_eligibility ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                      {healthStatus.trading_eligibility ? '🟢 GOOD (LIVE)' : `🔴 INSUFFICIENT (${typeof healthStatus.data_provider === 'object' ? healthStatus.data_provider.overall_status : 'DELAYED'})`}
                    </span>
                  </div>

                  <div className="flex justify-between items-center">
                    <span>Trading Status:</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${healthStatus.trading_eligibility ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20 animate-pulse'}`}>
                      {healthStatus.trading_eligibility ? 'PAPER TRADING ALLOWED' : 'NO TRADE'}
                    </span>
                  </div>

                  <div className="space-y-2 mt-4">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wide font-black">MARKET SPECIFIC FEED AUDIT</span>
                    {healthStatus.markets && Object.entries(healthStatus.markets).map(([mName, mInfo]) => {
                      let badgeColor = "bg-rose-500/10 text-rose-400 border-rose-500/20";
                      let statusLabel = mInfo.spot || "UNAVAILABLE";
                      if (mInfo.spot === "LIVE") badgeColor = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
                      else if (mInfo.spot === "DELAYED") badgeColor = "bg-amber-500/10 text-amber-300 border-amber-500/20";
                      else if (mInfo.spot === "STALE") badgeColor = "bg-orange-500/10 text-orange-400 border-orange-500/20";
                      else if (mInfo.spot === "SIMULATION") badgeColor = "bg-sky-500/10 text-sky-400 border-sky-500/20";

                      return (
                        <div key={mName} className="p-2.5 bg-slate-900/60 rounded-xl border border-slate-800/80 font-normal">
                          <div className="flex justify-between items-center mb-1">
                            <span className="font-bold text-slate-200 text-xs">{mName.replace("_", " ")}</span>
                            <span className={`px-2 py-0.5 rounded text-[9px] font-black border ${badgeColor}`}>
                              {statusLabel}
                            </span>
                          </div>
                          <div className="grid grid-cols-2 gap-y-1 text-[10px] text-slate-400 font-semibold">
                            <div>Chain: <span className={mInfo.option_chain === "LIVE" ? "text-emerald-400" : "text-rose-400"}>{mInfo.option_chain}</span></div>
                            <div>Age: <span className="text-white">{mInfo.age_seconds ? `${mInfo.age_seconds.toFixed(0)}s` : 'N/A'}</span></div>
                            <div>Latency: <span className="text-white">{mInfo.latency_ms ? `${mInfo.latency_ms.toFixed(0)}ms` : 'N/A'}</span></div>
                            <div>Status: <span className={mInfo.trading_eligible ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>{mInfo.trading_eligible ? 'ELIGIBLE' : 'BLOCKED'}</span></div>
                          </div>
                          {mInfo.missing_fields && mInfo.missing_fields.length > 0 && mInfo.missing_fields[0] !== "" && (
                            <div className="mt-1.5 text-[9px] text-rose-400 bg-rose-500/5 p-1 rounded border border-rose-500/10 font-bold">
                              Missing: {mInfo.missing_fields.join(", ")}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* LIVE PAPER SESSION Panel */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl relative overflow-hidden mt-6">
                <div className="absolute top-0 right-0 w-24 h-24 bg-sky-500/5 rounded-full blur-2xl" />
                <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wide border-b border-slate-800 pb-2 mb-4 flex items-center justify-between">
                  <span>Live Paper Session</span>
                  <span className="px-2 py-0.5 text-[9px] bg-sky-500/10 text-sky-400 border border-sky-500/20 rounded font-black">
                    PAPER MODE
                  </span>
                </h3>
                <div className="space-y-4 text-xs font-semibold text-slate-400">
                  <div className="flex justify-between items-center text-[10px] font-black text-rose-400 uppercase tracking-wide bg-rose-500/5 p-2 rounded border border-rose-500/10">
                    <span>⚠️ Real Orders:</span>
                    <span>DISABLED</span>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-[10px] text-slate-500 block uppercase mb-1">Provider</span>
                      <span className="text-white font-extrabold uppercase font-mono">
                        {typeof healthStatus.data_provider === 'object' ? healthStatus.data_provider.name : 'FYERS'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block uppercase mb-1">WebSocket</span>
                      <span className={`font-black uppercase ${healthStatus.websocket === 'CONNECTED' ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {healthStatus.websocket || 'DISCONNECTED'}
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-[10px] text-slate-500 block uppercase mb-1">Data State</span>
                      <span className={`font-black uppercase ${healthStatus.trading_eligibility ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {healthStatus.trading_eligibility ? 'LIVE' : 'STALE'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block uppercase mb-1">Latency</span>
                      <span className="text-white font-extrabold font-mono">
                        {healthStatus.markets && healthStatus.markets.NIFTY ? `${healthStatus.markets.NIFTY.latency_ms} ms` : '120 ms'}
                      </span>
                    </div>
                  </div>

                  <div className="border-t border-slate-800 pt-3 grid grid-cols-2 gap-2 text-[10px]">
                    <div>Signals: <span className="text-white font-bold">{analyticsPerf ? analyticsPerf.total_signals : 0}</span></div>
                    <div>Trades: <span className="text-white font-bold">{analyticsPerf ? analyticsPerf.total_trades : 0}</span></div>
                    <div>Wins: <span className="text-emerald-400 font-bold">{analyticsPerf ? analyticsPerf.winning_trades : 0}</span></div>
                    <div>Losses: <span className="text-rose-400 font-bold">{analyticsPerf ? analyticsPerf.losing_trades : 0}</span></div>
                    <div>Win Rate: <span className="text-sky-400 font-bold">{analyticsPerf ? analyticsPerf.win_rate_net : 0}%</span></div>
                    <div>Net P&L: <span className={`font-bold ${(analyticsPerf ? analyticsPerf.net_pnl : 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>₹{analyticsPerf ? analyticsPerf.net_pnl : 0}</span></div>
                    <div>Drawdown: <span className="text-rose-400 font-bold">₹{analyticsPerf ? analyticsPerf.net_max_drawdown : 0}</span></div>
                    <div>Open Trades: <span className="text-white font-bold">{activeTrades.length}</span></div>
                  </div>

                  <div className="border-t border-slate-800/60 pt-4 space-y-2">
                    <div className="flex justify-between items-center">
                      <span>New Entries Status:</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${healthStatus.trading_eligibility ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20 animate-pulse'}`}>
                        {healthStatus.trading_eligibility ? 'ALLOWED' : 'BLOCKED'}
                      </span>
                    </div>
                    {!healthStatus.trading_eligibility && (
                      <div className="text-[10px] text-rose-400 bg-rose-500/5 p-2 rounded border border-rose-500/10 font-mono">
                        REASON: {healthStatus.connection !== 'CONNECTED' ? 'REAL-TIME DATA UNAVAILABLE' : 'REAL-TIME DATA BLOCKED (FEED IS STALE OR INSUFFICIENT)'}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Live Active Simulated Trades Panel */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div className="flex justify-between items-center mb-4">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="w-5 h-5 text-emerald-400" />
                    <h2 className="text-lg font-bold">Active Paper Positions</h2>
                  </div>
                  <button onClick={fetchActiveTrades} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors">
                    <RefreshCw className="w-4 h-4 text-slate-300" />
                  </button>
                </div>

                <div className="space-y-4">
                  {activeTrades.length > 0 ? (
                    activeTrades.map(trade => {
                      const netPnl = trade.pnl + (trade.current_price - trade.entry_price) * trade.qty;
                      const roi = ((trade.current_price - trade.entry_price) / trade.entry_price) * 100.0;
                      return (
                        <div key={trade.id} className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
                          <div className="flex justify-between items-center mb-2">
                            <div className="flex items-center space-x-1.5">
                              <span className="font-bold text-sm text-white">{trade.option_contract}</span>
                              <span className={`px-1 rounded text-[8px] font-extrabold ${trade.system_mode === 'LIVE' ? 'bg-rose-500/10 text-rose-400' : 'bg-amber-500/10 text-amber-400'}`}>{trade.system_mode}</span>
                            </div>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${trade.direction === 'BUY_CALL' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                              {trade.direction === 'BUY_CALL' ? 'CALL' : 'PUT'}
                            </span>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-2 text-xs mb-2 text-slate-400 border-b border-slate-800/60 pb-2">
                            <div>Entry Premium: <strong className="text-white">₹{trade.entry_price}</strong></div>
                            <div>Current LTP: <strong className="text-amber-400">₹{trade.current_price}</strong></div>
                            <div>SL: <strong className="text-rose-400">₹{trade.stop_loss}</strong></div>
                            <div>Target 1/2: <strong className="text-emerald-400">₹{trade.target_1}/₹{trade.target_2}</strong></div>
                          </div>

                          {/* Execution details */}
                          <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[9px] text-slate-400 border-b border-slate-800/60 pb-2 mb-2">
                            <div>Signal LTP: <strong className="text-slate-300">₹{trade.signal_price || trade.entry_price}</strong></div>
                            <div>Fill Price: <strong className="text-slate-300">₹{trade.fill_price || trade.entry_price}</strong></div>
                            <div>Spread: <strong className="text-slate-300">₹{trade.entry_spread || '0.50'} ({trade.entry_spread_pct || '0.5'}%)</strong></div>
                            <div>Slippage: <strong className="text-slate-300">₹{trade.slippage_amount || '0.20'} ({trade.slippage_pct || '0.5'}%)</strong></div>
                            <div>Gross P&L: <strong className={trade.gross_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>₹{(trade.gross_pnl || 0).toFixed(2)}</strong></div>
                            <div>Total Costs: <strong className="text-rose-400">₹{(trade.total_transaction_cost || 0).toFixed(2)}</strong></div>
                          </div>

                          <div className="mt-2 grid grid-cols-3 gap-1 text-[9px] text-slate-400 border-b border-slate-800/60 pb-2 text-center mb-3">
                            <div>Strat: <strong className="text-slate-200">{trade.signal_score ? trade.signal_score.toFixed(0) : '0'}/100</strong></div>
                            <div>ML: <strong className="text-sky-400">{trade.confidence ? trade.confidence.toFixed(0) : '0'}%</strong></div>
                            <div>Quality: <strong className="text-amber-400">{trade.trade_quality_score ? trade.trade_quality_score.toFixed(0) : '0'}/100</strong></div>
                          </div>

                          <div className="flex justify-between items-center text-xs">
                            <span className="text-slate-400">Running P&L:</span>
                            <span className={`font-black ${netPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              ₹{netPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })} ({roi.toFixed(1)}% ROI)
                            </span>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-center py-6 text-slate-500 text-xs">No active positions open. Monitoring scanner...</div>
                  )}
                </div>
              </div>
            </div>

            {/* Right Column: Chart, Option Chain, Surges */}
            <div className="lg:col-span-2 space-y-8">
              {/* Data quality/availability alerts banner */}
              {latestSignals.find(s => s.symbol === selectedTicker)?.reason?.includes("DATA QUALITY FAILURE") || 
               latestSignals.find(s => s.symbol === selectedTicker)?.reason?.includes("DATA UNAVAILABLE") ? (
                <div className="p-4 bg-rose-500/15 border border-rose-500/30 rounded-2xl text-xs text-rose-400 flex items-center gap-2 animate-pulse shadow-lg shadow-rose-500/5">
                  <AlertOctagon className="w-5 h-5 text-rose-400 flex-shrink-0" />
                  <div>
                    <span className="font-bold block uppercase tracking-wide">Data Feed Restriction Halted Scanning</span>
                    <span>{latestSignals.find(s => s.symbol === selectedTicker)?.reason}</span>
                  </div>
                </div>
              ) : null}

              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
                <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-4">
                  <div>
                    <span className="text-xs text-sky-400 uppercase font-black tracking-widest">Intraday Spot Coordinates</span>
                    <h2 className="text-2xl font-black text-white tracking-tight">{selectedTicker.replace("^", "")}</h2>
                  </div>
                  {history.length > 0 && (
                    <div className="text-right">
                      <span className="text-xs text-slate-400">Current Price</span>
                      <p className="text-xl font-bold text-slate-200">Rs.{history[history.length - 1].price.toFixed(2)}</p>
                    </div>
                  )}
                </div>

                {loading ? (
                  <div className="h-[260px] flex items-center justify-center">
                    <RefreshCw className="w-8 h-8 text-sky-400 animate-spin" />
                  </div>
                ) : history.length > 0 ? (
                  <div className="h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={history}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                        <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleTimeString()} stroke="#64748b" tick={{ fontSize: 10 }} />
                        <YAxis domain={['auto', 'auto']} stroke="#64748b" tick={{ fontSize: 10 }} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#0b0f19', borderColor: '#1e293b', borderRadius: '8px' }} 
                          labelFormatter={(t) => new Date(t).toLocaleString()}
                        />
                        <Line type="monotone" dataKey="price" stroke="#0ea5e9" strokeWidth={2} dot={false} name="Spot Price" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-[260px] flex items-center justify-center text-slate-500">
                    No historical coordinates available. Check scheduler status.
                  </div>
                )}
              </div>

              {/* Option Chain Component */}
              <OptionChainTable />

              {/* Fast Option Momentum Alerts */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
                <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-4">
                  <div className="flex items-center space-x-2">
                    <Zap className="w-5 h-5 text-amber-400 animate-bounce" />
                    <div>
                      <h3 className="text-lg font-bold text-white">Live Fast Option Momentum</h3>
                      <p className="text-xs text-slate-400">Short-interval premium surges confirmed by positive OI buildup</p>
                    </div>
                  </div>
                  <button onClick={fetchOptionMomentum} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors">
                    <RefreshCw className="w-4 h-4 text-slate-300" />
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {optionMomentum.length > 0 ? (
                    optionMomentum.map(item => {
                      const isSimulated = item.data_source === "simulated";
                      return (
                        <div key={item.id} className={`p-4 rounded-xl transition-colors ${isSimulated ? 'bg-slate-900/30 border border-amber-500/30 opacity-80' : 'bg-slate-900/60 border border-[#1e293b] hover:border-amber-500/40'}`}>
                          <div className="flex justify-between items-center mb-2">
                            <span className="font-bold text-sm text-white tracking-wide">{item.contract}</span>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${item.option_type === 'CE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                              {item.option_type === 'CE' ? '🟢 CE SURGE' : '🔴 PE SURGE'}
                            </span>
                          </div>
                          <div className="flex justify-between items-baseline mb-2">
                            <span className="text-xs text-slate-400">Premium Jump:</span>
                            <span className="text-base font-extrabold text-amber-400">
                              Rs.{item.old_premium.toFixed(2)} → Rs.{item.new_premium.toFixed(2)} <span className="text-xs text-emerald-400 font-bold">(+{item.pct_change.toFixed(1)}%)</span>
                            </span>
                          </div>
                          <div className="flex justify-between items-center text-xs text-slate-400 border-t border-slate-800/80 pt-2">
                            <span>OI Surge: <strong className="text-slate-200">+{item.oi_change.toLocaleString()}</strong></span>
                            <span>Vol: <strong className="text-slate-200">{item.volume.toLocaleString()}</strong></span>
                            <span>{new Date(item.timestamp).toLocaleTimeString()}</span>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="col-span-2 text-center text-slate-500 py-6 text-sm">
                      No fast option surges detected in the recent scan interval.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* VIEW 2: JOURNAL */}
        {activeTab === "journal" && (
          <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
            <div className="flex justify-between items-center mb-6 border-b border-[#1e293b] pb-4">
              <div>
                <h2 className="text-xl font-bold">Paper Trading Ledger</h2>
                <p className="text-xs text-slate-400">Review historical simulated options trades performance</p>
              </div>
              <button onClick={fetchTradeJournal} className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors">
                <RefreshCw className="w-4 h-4 text-slate-300" />
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs divide-y divide-slate-800">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">
                    <th className="pb-3 px-2">Entry Time</th>
                    <th className="pb-3 px-2">Contract</th>
                    <th className="pb-3 px-2">Direction</th>
                    <th className="pb-3 px-2 text-right">Signal (₹)</th>
                    <th className="pb-3 px-2 text-right">Fill (₹)</th>
                    <th className="pb-3 px-2 text-right">Exit LTP (₹)</th>
                    <th className="pb-3 px-2 text-right">Slippage (₹)</th>
                    <th className="pb-3 px-2 text-right">Gross P&L</th>
                    <th className="pb-3 px-2 text-right">Costs</th>
                    <th className="pb-3 px-2 text-right">Net P&L</th>
                    <th className="pb-3 px-2 text-right">ROI</th>
                    <th className="pb-3 px-2 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900/60 text-xs">
                  {tradeJournal.length > 0 ? (
                    tradeJournal.map(trade => (
                      <tr key={trade.id} className="hover:bg-slate-900/30">
                        <td className="py-3 px-2 text-slate-400">{new Date(trade.entry_time).toLocaleString()}</td>
                        <td className="py-3 px-2 font-bold text-white">{trade.option_contract}</td>
                        <td className="py-3 px-2 font-semibold">{trade.direction.replace("BUY_", "")}</td>
                        <td className="py-3 px-2 text-right">₹{(trade.signal_price || trade.entry_price).toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">₹{(trade.fill_price || trade.entry_price).toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">₹{trade.current_price.toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">₹{(trade.slippage_amount || 0.0).toFixed(2)}</td>
                        <td className={`py-3 px-2 text-right font-bold ${trade.gross_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{trade.gross_pnl.toFixed(2)}
                        </td>
                        <td className="py-3 px-2 text-right text-rose-400">
                          ₹{trade.total_transaction_cost.toFixed(2)}
                        </td>
                        <td className={`py-3 px-2 text-right font-black ${trade.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{trade.net_pnl.toFixed(2)}
                        </td>
                        <td className={`py-3 px-2 text-right font-black ${trade.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {trade.roi}%
                        </td>
                        <td className="py-3 px-2 text-center text-slate-300 font-bold">{trade.status}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="12" className="text-center text-slate-500 py-8 text-sm">No historical paper trades recorded in database.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* VIEW 3: BACKTESTING & ML */}
        {activeTab === "backtest" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Backtest Panel */}
            <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
              <h2 className="text-xl font-bold mb-2">Historical Backtesting</h2>
              <p className="text-xs text-slate-400 mb-6">Simulate structural setups on historical index data using Black-Scholes pricing.</p>

              <div className="space-y-4 mb-6">
                <div className="flex space-x-4">
                  <div className="flex-1">
                    <label className="block text-xs font-bold text-slate-400 mb-1">Index Ticker</label>
                    <select 
                      value={backtestSymbol} 
                      onChange={e => setBacktestSymbol(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                    >
                      <option value="NIFTY">NIFTY 50</option>
                      <option value="BANKNIFTY">BANK NIFTY</option>
                      <option value="SENSEX">SENSEX</option>
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className="block text-xs font-bold text-slate-400 mb-1">Lookback Period (Days)</label>
                    <input 
                      type="number" 
                      min="5" 
                      max="30" 
                      value={backtestDays} 
                      onChange={e => setBacktestDays(parseInt(e.target.value))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                    />
                  </div>
                </div>

                <button 
                  onClick={handleRunBacktest}
                  disabled={btLoading}
                  className="w-full py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-white font-extrabold text-sm transition-colors flex items-center justify-center gap-2"
                >
                  <Play className="w-4 h-4" /> {btLoading ? 'Executing Simulation...' : 'Run Strategy Backtest'}
                </button>
              </div>

              {backtestResult && (
                <div className="space-y-4 border-t border-slate-800 pt-4 text-xs">
                  <h3 className="font-bold text-slate-200 text-sm">Simulation Summary ({backtestResult.symbol})</h3>
                  
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                    <div>
                      <span className="text-slate-500">Total Trades</span>
                      <p className="text-lg font-black text-white">{backtestResult.total_trades}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Win Rate</span>
                      <p className="text-lg font-black text-emerald-400">{backtestResult.win_rate}%</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Net Profit</span>
                      <p className={`text-lg font-black ${backtestResult.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        ₹{backtestResult.net_pnl.toLocaleString('en-IN')}
                      </p>
                    </div>
                    <div>
                      <span className="text-slate-500">Sharpe Ratio</span>
                      <p className="text-lg font-black text-white">{backtestResult.sharpe_ratio}</p>
                    </div>
                  </div>

                  <div className="max-h-[160px] overflow-y-auto space-y-2 border border-slate-800 rounded-lg p-2 bg-slate-950/40">
                    {backtestResult.trades.map((t, idx) => (
                      <div key={idx} className="flex justify-between border-b border-slate-900/60 pb-1 last:border-0 last:pb-0">
                        <span className="text-slate-400">{t.contract} ({t.direction.replace("BUY_", "")})</span>
                        <span className={t.pnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400'}>
                          {t.pnl >= 0 ? '+' : ''}₹{t.pnl.toFixed(0)} ({t.exit_reason})
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* ML Training Panel */}
            <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
              <h2 className="text-xl font-bold mb-2">AI / Machine Learning Component</h2>
              <p className="text-xs text-slate-400 mb-6">Train directional classifiers on technical and SMC features to guide consensus scoring.</p>

              <div className="space-y-4 mb-6">
                <div>
                  <label className="block text-xs font-bold text-slate-400 mb-1">Index Select</label>
                  <select 
                    value={mlSymbol} 
                    onChange={e => setMlSymbol(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  >
                    <option value="NIFTY">NIFTY 50</option>
                    <option value="BANKNIFTY">BANK NIFTY</option>
                    <option value="SENSEX">SENSEX</option>
                  </select>
                </div>

                <button 
                  onClick={handleTrainML}
                  disabled={mlLoading}
                  className="w-full py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-extrabold text-sm transition-colors flex items-center justify-center gap-2"
                >
                  <Cpu className="w-4 h-4" /> {mlLoading ? 'Training Random Forest...' : 'Train AI Confirmation Layer'}
                </button>
              </div>

              {mlMsg && (
                <div className="p-4 bg-purple-500/10 border border-purple-500/30 rounded-xl text-xs text-purple-300">
                  <p className="font-bold mb-1">Training Result Output:</p>
                  <p>{mlMsg}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* VIEW 5: ANALYTICS */}
        {activeTab === "analytics" && (
          <div className="space-y-8">
            {/* Sample Size Warning */}
            {analyticsPerf && analyticsPerf.sample_status === "INSUFFICIENT SAMPLE" && (
              <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 p-4 rounded-2xl text-xs font-bold flex items-center justify-between animate-pulse">
                <span>⚠️ INSUFFICIENT SAMPLE: Collecting at least 100–200 paper trades is recommended for valid expectancy. Current sample: {analyticsPerf.total_trades} trades.</span>
                <span className="px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/30">INSUFFICIENT</span>
              </div>
            )}

            {/* Performance Cards Grid */}
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center">
                <span className="text-[10px] uppercase font-bold text-slate-500">Gross P&L</span>
                <p className={`text-base font-black mt-1 ${analyticsPerf?.gross_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ₹{analyticsPerf ? analyticsPerf.gross_pnl.toLocaleString('en-IN') : '0.00'}
                </p>
              </div>
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center border-emerald-500/30">
                <span className="text-[10px] uppercase font-bold text-emerald-400">Net P&L</span>
                <p className={`text-base font-black mt-1 ${analyticsPerf?.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ₹{analyticsPerf ? analyticsPerf.net_pnl.toLocaleString('en-IN') : '0.00'}
                </p>
              </div>
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center">
                <span className="text-[10px] uppercase font-bold text-rose-400">Total Costs</span>
                <p className="text-base font-black text-rose-400 mt-1">
                  ₹{analyticsPerf ? analyticsPerf.total_costs.toLocaleString('en-IN') : '0.00'}
                </p>
              </div>
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center">
                <span className="text-[10px] uppercase font-bold text-slate-500">Net Win Rate</span>
                <p className="text-base font-black text-white mt-1">
                  {analyticsPerf ? analyticsPerf.win_rate_net : '0'}%
                </p>
              </div>
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center">
                <span className="text-[10px] uppercase font-bold text-slate-500">Expectancy</span>
                <p className={`text-base font-black mt-1 ${analyticsPerf?.net_expectancy >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ₹{analyticsPerf ? analyticsPerf.net_expectancy.toFixed(2) : '0.00'}
                </p>
              </div>
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-4 text-center">
                <span className="text-[10px] uppercase font-bold text-slate-500">Max Drawdown</span>
                <p className="text-base font-black text-rose-400 mt-1">
                  ₹{analyticsPerf ? analyticsPerf.net_max_drawdown.toLocaleString('en-IN') : '0.00'}
                </p>
              </div>
            </div>

            {/* Live Paper Results vs Backtest metrics */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {/* Live Paper Stats */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-md">
                <h3 className="text-sm font-bold text-sky-400 uppercase tracking-wide border-b border-slate-800 pb-2 mb-4">
                  Live Paper Trading statistics
                </h3>
                <div className="space-y-3 text-xs font-semibold text-slate-400">
                  <div className="flex justify-between"><span>Profit Factor (Net):</span><span className="text-white">{analyticsPerf?.net_profit_factor || '0.00'}</span></div>
                  <div className="flex justify-between"><span>Sharpe Ratio (Net):</span><span className="text-white">{analyticsPerf?.net_sharpe || '0.00'}</span></div>
                  <div className="flex justify-between"><span>Sortino Ratio (Net):</span><span className="text-white">{analyticsPerf?.net_sortino || '0.00'}</span></div>
                  <div className="flex justify-between"><span>Target 1 Hit Rate:</span><span className="text-emerald-400">{analyticsPerf?.t1_hit_rate || '0'}%</span></div>
                  <div className="flex justify-between"><span>Target 2 Hit Rate:</span><span className="text-emerald-400">{analyticsPerf?.t2_hit_rate || '0'}%</span></div>
                  <div className="flex justify-between"><span>Target 3 Hit Rate:</span><span className="text-emerald-400">{analyticsPerf?.t3_hit_rate || '0'}%</span></div>
                  <div className="flex justify-between"><span>Stop Loss Hit Rate:</span><span className="text-rose-400">{analyticsPerf?.sl_hit_rate || '0'}%</span></div>
                  <div className="flex justify-between"><span>Avg holding duration:</span><span className="text-white">{analyticsPerf?.avg_holding_time_mins || '0'} mins</span></div>
                </div>
              </div>

              {/* Historical Backtest Stats */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 opacity-90 shadow-md">
                <h3 className="text-sm font-bold text-purple-400 uppercase tracking-wide border-b border-slate-800 pb-2 mb-4">
                  Historical Backtesting reference
                </h3>
                <div className="space-y-3 text-xs font-semibold text-slate-400">
                  <div className="flex justify-between"><span>Backtest Win Rate:</span><span className="text-white">{backtestResult ? backtestResult.win_rate : '0.00'}%</span></div>
                  <div className="flex justify-between"><span>Backtest Net Profit:</span><span className={`font-bold ${backtestResult?.net_pnl >= 0 ? 'text-emerald-400' : 'text-slate-300'}`}>₹{backtestResult ? backtestResult.net_pnl.toLocaleString('en-IN') : '0.00'}</span></div>
                  <div className="flex justify-between"><span>Backtest Profit Factor:</span><span className="text-white">{backtestResult ? backtestResult.profit_factor : '0.00'}</span></div>
                  <div className="flex justify-between"><span>Backtest Max Drawdown:</span><span className="text-rose-400">₹{backtestResult ? backtestResult.max_drawdown?.toLocaleString() : '0.00'}</span></div>
                  <div className="flex justify-between"><span>Backtest Sharpe:</span><span className="text-white">{backtestResult ? backtestResult.sharpe_ratio : '0.00'}</span></div>
                  <div className="flex justify-between"><span>Backtest Sortino:</span><span className="text-white">{backtestResult ? backtestResult.sortino_ratio : '0.00'}</span></div>
                  <div className="flex justify-between"><span>Pricing Basis:</span><span className="text-sky-400">{backtestResult ? backtestResult.pricing_source : 'N/A'}</span></div>
                  <div className="flex justify-between"><span>Backtest Trades:</span><span className="text-white">{backtestResult ? backtestResult.total_trades : '0'}</span></div>
                </div>
              </div>
            </div>

            {/* Segmentations Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs">
              {/* Markets Segmentation */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-md">
                <h4 className="font-bold text-slate-200 mb-3 text-sm border-b border-slate-800 pb-2">Index Breakdown</h4>
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-slate-500 text-[10px] uppercase pb-1 border-b border-slate-800/60">
                      <th>Index</th>
                      <th>Trades</th>
                      <th className="text-right">Win Rate</th>
                      <th className="text-right">Net P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/30">
                    {analyticsPerf && Object.entries(analyticsPerf.segment_markets).map(([k, v]) => (
                      <tr key={k} className="py-2">
                        <td className="py-2 text-white font-bold">{k}</td>
                        <td className="py-2">{v.count}</td>
                        <td className="py-2 text-right">{v.win_rate_net}%</td>
                        <td className={`py-2 text-right font-bold ${v.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{v.net_pnl.toLocaleString('en-IN')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Setups Segmentation */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-md">
                <h4 className="font-bold text-slate-200 mb-3 text-sm border-b border-slate-800 pb-2">Strategy Breakdown</h4>
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-slate-500 text-[10px] uppercase pb-1 border-b border-slate-800/60">
                      <th>Setup</th>
                      <th>Trades</th>
                      <th className="text-right">Win Rate</th>
                      <th className="text-right">Net P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/30">
                    {analyticsBreakdown && Object.entries(analyticsBreakdown.setups).map(([k, v]) => (
                      <tr key={k} className="py-2">
                        <td className="py-2 text-white font-bold">{k}</td>
                        <td className="py-2">{v.count}</td>
                        <td className="py-2 text-right">{v.win_rate}%</td>
                        <td className={`py-2 text-right font-bold ${v.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{v.net_pnl.toLocaleString('en-IN')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Time of Day Segmentation */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-md">
                <h4 className="font-bold text-slate-200 mb-3 text-sm border-b border-slate-800 pb-2">Time-of-Day (IST)</h4>
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-slate-500 text-[10px] uppercase pb-1 border-b border-slate-800/60">
                      <th>Period</th>
                      <th>Trades</th>
                      <th className="text-right">Win Rate</th>
                      <th className="text-right">Net P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/30">
                    {analyticsBreakdown && Object.entries(analyticsBreakdown.time_of_day).map(([k, v]) => (
                      <tr key={k} className="py-2">
                        <td className="py-2 text-white font-bold">{k}</td>
                        <td className="py-2">{v.count}</td>
                        <td className="py-2 text-right">{v.win_rate}%</td>
                        <td className={`py-2 text-right font-bold ${v.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          ₹{v.net_pnl.toLocaleString('en-IN')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* VIEW 4: SETTINGS */}
        {activeTab === "settings" && (
          <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-8 max-w-2xl mx-auto shadow-xl">
            <h2 className="text-xl font-bold mb-2">Platform Administration</h2>
            <p className="text-xs text-slate-400 mb-6">Configure platform parameters and strategy weights dynamically</p>

            <div className="space-y-6">
              <h3 className="text-sm font-bold text-sky-400 uppercase tracking-wide border-b border-slate-800 pb-2">Risk Management Limits</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-semibold">
                <div>
                  <label className="block text-slate-400 mb-1">Max Daily Loss (₹)</label>
                  <input 
                    type="number" 
                    value={systemSettings.max_daily_loss} 
                    onChange={e => updateSetting("max_daily_loss", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Max Daily Trades</label>
                  <input 
                    type="number" 
                    value={systemSettings.max_daily_trades} 
                    onChange={e => updateSetting("max_daily_trades", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Max Simultaneous Trades</label>
                  <input 
                    type="number" 
                    value={systemSettings.max_simultaneous_trades} 
                    onChange={e => updateSetting("max_simultaneous_trades", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-semibold">
                <div>
                  <label className="block text-slate-400 mb-1">Consensus Threshold Score (0-100)</label>
                  <input 
                    type="number" 
                    value={systemSettings.signal_threshold} 
                    onChange={e => updateSetting("signal_threshold", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Min Target Risk/Reward</label>
                  <input 
                    type="number" 
                    step="0.1"
                    value={systemSettings.min_risk_reward} 
                    onChange={e => updateSetting("min_risk_reward", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Max Entry Chase %</label>
                  <input 
                    type="number" 
                    step="0.1"
                    value={systemSettings.max_entry_chase_pct || "5.0"} 
                    onChange={e => updateSetting("max_entry_chase_pct", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Slippage Percentage (%)</label>
                  <input 
                    type="number" 
                    step="0.1"
                    value={systemSettings.slippage_pct || "0.5"} 
                    onChange={e => updateSetting("slippage_pct", e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                  />
                </div>
              </div>

              <h3 className="text-sm font-bold text-sky-400 uppercase tracking-wide border-b border-slate-800 pb-2 pt-4">Consensus Strategy Weights</h3>
              <div className="grid grid-cols-2 gap-4 text-xs">
                {Object.keys(systemSettings)
                  .filter(k => k.startsWith("weight_"))
                  .map(key => (
                    <div key={key}>
                      <label className="block text-slate-400 mb-1 uppercase tracking-wider">{key.replace("weight_", "").replace("_", " ")} Weight</label>
                      <input 
                        type="number" 
                        value={systemSettings[key]} 
                        onChange={e => updateSetting(key, e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-bold"
                      />
                    </div>
                  ))
                }
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
