import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ShieldCheck, ToggleLeft, ToggleRight, Radio, RefreshCw, BarChart2, BellRing, Settings, Zap } from 'lucide-react';

let API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
if (API_BASE && !API_BASE.startsWith("http")) {
  API_BASE = `https://${API_BASE}`;
}

export default function App() {
  const [latestSignals, setLatestSignals] = useState([]);
  const [optionMomentum, setOptionMomentum] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState("^NSEI");
  const [history, setHistory] = useState([]);
  const [strategies, setStrategies] = useState({
    ema_crossover: true,
    rsi: true,
    macd: true,
    bollinger_bands: true,
  });
  const [activeTab, setActiveTab] = useState("dashboard");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("checking");

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
      const res = await fetch(`${API_BASE}/options/momentum?limit=10`);
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
        // Reverse history to show chronologically from oldest to newest on the chart
        setHistory(data.reverse());
      }
    } catch (e) {
      console.error("Error fetching history", e);
    } finally {
      setLoading(false);
    }
  };

  const toggleStrategy = async (name, currentVal) => {
    const newVal = !currentVal;
    try {
      const res = await fetch(`${API_BASE}/admin/strategy/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_name: name, is_enabled: newVal })
      });
      if (res.ok) {
        setStrategies(prev => ({ ...prev, [name]: newVal }));
      }
    } catch (e) {
      console.error("Error toggling strategy", e);
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
    fetchLatest();
    fetchOptionMomentum();
    fetchHistory(selectedTicker);
    const interval = setInterval(() => {
      fetchLatest();
      fetchOptionMomentum();
      checkHealth();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchHistory(selectedTicker);
  }, [selectedTicker]);

  const [typeFilter, setTypeFilter] = useState("ALL"); // ALL, INDEX, STOCK

  const filteredSignals = latestSignals.filter(sig => {
    const isIdx = sig.symbol.startsWith("^") || sig.instrument_type === "INDEX";
    if (typeFilter === "INDEX") return isIdx;
    if (typeFilter === "STOCK") return !isIdx;
    return true;
  });

  const isSelectedIndex = selectedTicker.startsWith("^");

  return (
    <div className="min-h-screen bg-[#090d16] text-[#e2e8f0]">
      {/* Header bar */}
      <header className="border-b border-[#1e293b] bg-[#0b0f19]/80 backdrop-blur-md px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
            <Radio className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-wider bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">MarketSignalBot</h1>
            <p className="text-xs text-sky-400 font-semibold uppercase tracking-widest">Intraday & Index Derivative Console</p>
          </div>
        </div>

        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-slate-400">API Status:</span>
            {status === "connected" && <span className="flex items-center text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-ping"></span>Connected</span>}
            {status === "disconnected" && <span className="text-xs text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full border border-rose-500/20">Disconnected</span>}
            {status === "checking" && <span className="text-xs text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">Checking...</span>}
          </div>
          
          <nav className="flex space-x-2">
            <button onClick={() => setActiveTab("dashboard")} className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-all duration-200 ${activeTab === "dashboard" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}>Dashboard</button>
            <button onClick={() => setActiveTab("strategies")} className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-all duration-200 ${activeTab === "strategies" ? "bg-sky-500/15 text-sky-400 border border-sky-500/30" : "text-slate-400 hover:text-white"}`}>Strategy Manager</button>
          </nav>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {activeTab === "dashboard" ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Left Feed */}
            <div className="lg:col-span-1 bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl relative overflow-hidden">
              <div className="flex justify-between items-center mb-4">
                <div className="flex items-center space-x-2">
                  <BarChart2 className="w-5 h-5 text-sky-400" />
                  <h2 className="text-lg font-bold">Monitored Tickers</h2>
                </div>
                <button onClick={fetchLatest} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors">
                  <RefreshCw className="w-4 h-4 text-slate-300" />
                </button>
              </div>

              {/* Instrument Type Filter Pills */}
              <div className="flex space-x-1 bg-slate-900/80 p-1 rounded-xl border border-[#1e293b] mb-6 text-xs font-semibold">
                <button onClick={() => setTypeFilter("ALL")} className={`flex-1 py-1.5 rounded-lg transition-colors ${typeFilter === "ALL" ? "bg-sky-500/20 text-sky-400 font-bold border border-sky-500/30" : "text-slate-400 hover:text-slate-200"}`}>All</button>
                <button onClick={() => setTypeFilter("INDEX")} className={`flex-1 py-1.5 rounded-lg transition-colors ${typeFilter === "INDEX" ? "bg-purple-500/20 text-purple-400 font-bold border border-purple-500/30" : "text-slate-400 hover:text-slate-200"}`}>Indices</button>
                <button onClick={() => setTypeFilter("STOCK")} className={`flex-1 py-1.5 rounded-lg transition-colors ${typeFilter === "STOCK" ? "bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30" : "text-slate-400 hover:text-slate-200"}`}>Stocks</button>
              </div>

              <div className="space-y-4">
                {filteredSignals.length > 0 ? (
                  filteredSignals.map(sig => {
                    const isIdx = sig.symbol.startsWith("^") || sig.instrument_type === "INDEX";
                    return (
                      <div 
                        key={sig.id} 
                        onClick={() => setSelectedTicker(sig.symbol)}
                        className={`p-4 rounded-xl border transition-all duration-200 cursor-pointer ${selectedTicker === sig.symbol ? 'bg-sky-500/5 border-sky-500/30 shadow-md shadow-sky-500/5' : 'bg-slate-900/50 border-[#1e293b] hover:border-slate-700'}`}
                      >
                        <div className="flex justify-between items-start mb-2">
                          <div>
                            <div className="flex items-center space-x-2">
                              <span className="font-bold text-base tracking-wide text-white">{sig.symbol}</span>
                              <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold uppercase ${isIdx ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'}`}>
                                {isIdx ? 'INDEX' : 'STOCK'}
                              </span>
                            </div>
                            <p className="text-xs text-slate-400 mt-0.5">{new Date(sig.timestamp).toLocaleTimeString()}</p>
                          </div>
                          <span className={`px-2.5 py-0.5 rounded-full text-xs font-black uppercase tracking-wider ${sig.signal === 'BUY' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : sig.signal === 'SELL' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                            {sig.signal}
                          </span>
                        </div>
                        <div className="flex justify-between items-end">
                          <span className="text-sm font-bold text-slate-300">Rs.{sig.price.toFixed(2)}</span>
                          {sig.signal !== 'HOLD' && <span className="text-xs text-slate-400">Confidence: <span className="font-semibold text-sky-400">{sig.confidence.toFixed(0)}%</span></span>}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-slate-500 text-center text-sm py-8">No active signals match the selected filter.</p>
                )}
              </div>
            </div>

            {/* Right Chart Analysis & Option Momentum Feed */}
            <div className="lg:col-span-2 space-y-8">
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
                <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-4">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="text-xs text-sky-400 uppercase font-black tracking-widest">Currently Analyzing</span>
                      {selectedTicker.startsWith("^") && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-black bg-purple-500/15 text-purple-400 border border-purple-500/30">
                          INDEX (DERIVATIVES & ETF ROUTED)
                        </span>
                      )}
                    </div>
                    <h2 className="text-2xl font-black text-white tracking-tight">{selectedTicker}</h2>
                  </div>
                  {history.length > 0 && (
                    <div className="text-right">
                      <span className="text-xs text-slate-400">Current Spot</span>
                      <p className="text-xl font-bold text-slate-200">Rs.{history[history.length - 1].price.toFixed(2)}</p>
                    </div>
                  )}
                </div>

                {loading ? (
                  <div className="h-[300px] flex items-center justify-center">
                    <RefreshCw className="w-8 h-8 text-sky-400 animate-spin" />
                  </div>
                ) : history.length > 0 ? (
                  <div className="h-[300px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={history}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                        <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleTimeString()} stroke="#64748b" tick={{ fontSize: 10 }} />
                        <YAxis domain={['auto', 'auto']} stroke="#64748b" tick={{ fontSize: 10 }} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#0b0f19', borderColor: '#1e293b', borderRadius: '8px' }} 
                          labelFormatter={(t) => new Date(t).toLocaleString()}
                        />
                        <Line type="monotone" dataKey="price" stroke="#0ea5e9" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-[300px] flex items-center justify-center text-slate-500">
                    No historical coordinates available. Check scheduler status.
                  </div>
                )}
              </div>

              {/* Fast Option Momentum Alerts Panel */}
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
                            <div className="flex items-center space-x-2">
                              <span className="font-bold text-sm text-white tracking-wide">{item.contract}</span>
                              {isSimulated ? (
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase bg-amber-500/20 text-amber-300 border border-amber-500/40">SIMULATED</span>
                              ) : (
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">LIVE NSE</span>
                              )}
                            </div>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${item.option_type === 'CE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                              {item.option_type === 'CE' ? '🟢 CALL SURGE' : '🔴 PUT SURGE'}
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

              {/* Strategy Details Table */}
              <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl">
                <div className="flex items-center space-x-2 mb-4">
                  <ShieldCheck className="w-5 h-5 text-sky-400" />
                  <h3 className="text-lg font-bold">Signal Log Registry</h3>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-[#1e293b] text-slate-400 text-xs uppercase tracking-widest">
                        <th className="pb-3 font-semibold">Time</th>
                        <th className="pb-3 font-semibold">Signal</th>
                        <th className="pb-3 font-semibold">Trigger Price</th>
                        <th className="pb-3 font-semibold">Confidence</th>
                        <th className="pb-3 font-semibold">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.slice().reverse().map(record => (
                        <tr key={record.id} className="border-b border-slate-900/50 last:border-0 hover:bg-slate-900/30">
                          <td className="py-3 font-medium text-slate-400">{new Date(record.timestamp).toLocaleTimeString()}</td>
                          <td className="py-3">
                            <span className={`px-2 py-0.5 rounded-full text-2xs font-extrabold uppercase ${record.signal === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : record.signal === 'SELL' ? 'bg-rose-500/10 text-rose-400' : 'bg-slate-800 text-slate-400'}`}>
                              {record.signal}
                            </span>
                          </td>
                          <td className="py-3 font-bold text-slate-200">Rs.{record.price.toFixed(2)}</td>
                          <td className="py-3 font-semibold text-sky-400">{record.confidence.toFixed(0)}%</td>
                          <td className="py-3 text-xs text-slate-400">{record.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Strategy Manager Tab */
          <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-8 max-w-2xl mx-auto shadow-xl">
            <div className="flex items-center space-x-3 mb-6 border-b border-[#1e293b] pb-4">
              <Settings className="w-6 h-6 text-sky-400" />
              <div>
                <h2 className="text-xl font-bold">Indicator Configuration</h2>
                <p className="text-xs text-slate-400">Toggle quantitative scanning criteria dynamically</p>
              </div>
            </div>

            <div className="space-y-6">
              {Object.keys(strategies).map(name => (
                <div key={name} className="flex justify-between items-center p-4 bg-slate-900/50 border border-[#1e293b] rounded-xl">
                  <div>
                    <h3 className="font-bold text-slate-200 uppercase tracking-wide text-sm">{name.replace("_", " ")}</h3>
                    <p className="text-xs text-slate-400">
                      {name === "ema_crossover" && "Triggers when 9 EMA crosses above/below 21 EMA"}
                      {name === "rsi" && "Alerts when RSI is oversold (<30) or overbought (>70)"}
                      {name === "macd" && "Triggers on bullish/bearish MACD Line Crossovers"}
                      {name === "bollinger_bands" && "Alerts on breakouts beyond dynamic standard deviation envelopes"}
                    </p>
                  </div>
                  <button onClick={() => toggleStrategy(name, strategies[name])} className="focus:outline-none">
                    {strategies[name] ? (
                      <ToggleRight className="w-12 h-12 text-sky-400" />
                    ) : (
                      <ToggleLeft className="w-12 h-12 text-slate-600" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
