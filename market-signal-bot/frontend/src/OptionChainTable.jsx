import React, { useState, useEffect } from 'react';
import { RefreshCw, Calculator, X, TrendingUp, AlertTriangle } from 'lucide-react';

export default function OptionChainTable() {
  const [symbol, setSymbol] = useState('NIFTY');
  const [expiry, setExpiry] = useState('Current Expiry');
  const [chainData, setChainData] = useState(null);
  const [loading, setLoading] = useState(true);

  // Profit Calculator Modal state
  const [selectedContract, setSelectedContract] = useState(null);
  const [entryPremium, setEntryPremium] = useState('');
  const [targetPremium, setTargetPremium] = useState('');
  const [lots, setLots] = useState(1);
  const [calcResult, setCalcResult] = useState(null);
  const [calcLoading, setCalcLoading] = useState(false);

  const fetchChain = async () => {
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/options/chain?symbol=${symbol}`);
      if (res.ok) {
        const data = await res.json();
        setChainData(data);
      }
    } catch (err) {
      console.error('Error fetching option chain:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChain();
    const interval = setInterval(fetchChain, 30000); // Auto refresh every 30s
    return () => clearInterval(interval);
  }, [symbol]);

  const openCalculator = (strike, optType, ltp) => {
    const defaultTarget = ltp > 0 ? (ltp * 1.20).toFixed(2) : '100';
    setSelectedContract({ strike, optType, ltp });
    setEntryPremium(ltp > 0 ? ltp.toFixed(2) : '100');
    setTargetPremium(defaultTarget);
    setLots(1);
    setCalcResult(null);
  };

  const handleCalculateProfit = async () => {
    if (!selectedContract) return;
    setCalcLoading(true);
    try {
      const res = await fetch('http://localhost:8000/options/profit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          strike: selectedContract.strike,
          option_type: selectedContract.optType,
          entry_premium: parseFloat(entryPremium) || 0,
          target_premium: parseFloat(targetPremium) || 0,
          quantity_lots: parseInt(lots) || 1,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setCalcResult(data);
      }
    } catch (err) {
      console.error('Error calculating profit:', err);
    } finally {
      setCalcLoading(false);
    }
  };

  const isSimulated = chainData?.data_source === 'simulated';

  return (
    <div className="bg-[#0b0f19] border border-[#1e293b] rounded-2xl p-6 shadow-xl mb-8">
      {/* Top Header Bar */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <div className="flex items-center space-x-3">
            <h2 className="text-xl font-black text-white tracking-wide">Option Chain Matrix</h2>
            {isSimulated ? (
              <span className="px-2.5 py-0.5 rounded text-xs font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" /> SIMULATED DATA
              </span>
            ) : (
              <span className="px-2 py-0.5 rounded text-xs font-black bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                LIVE NSE
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Click any Call/Put LTP cell to launch the instant Profit & Loss Calculator
          </p>
        </div>

        {/* Controls */}
        <div className="flex items-center space-x-3 w-full md:w-auto">
          {chainData && (
            <div className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300">
              Spot: <span className="font-extrabold text-amber-400">Rs.{chainData.spot_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
            </div>
          )}
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-bold text-white focus:outline-none focus:border-amber-500"
          >
            <option value="NIFTY">NIFTY 50</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
          </select>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-bold text-slate-300 focus:outline-none focus:border-amber-500"
          >
            <option value="Current Expiry">Current Expiry</option>
            <option value="Next Expiry">Next Expiry</option>
          </select>
          <button
            onClick={fetchChain}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Refresh Option Chain"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Option Chain Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-xs text-left">
          <thead className="bg-slate-900/90 text-slate-400 font-bold border-b border-slate-800">
            <tr>
              <th colSpan="4" className="text-center py-2 bg-emerald-950/20 text-emerald-400 border-r border-slate-800">
                CALLS (CE)
              </th>
              <th className="text-center py-2 bg-amber-950/20 text-amber-400 font-extrabold">STRIKE</th>
              <th colSpan="4" className="text-center py-2 bg-rose-950/20 text-rose-400 border-l border-slate-800">
                PUTS (PE)
              </th>
            </tr>
            <tr className="border-b border-slate-800 text-[11px]">
              <th className="py-2 px-3 text-right">OI</th>
              <th className="py-2 px-3 text-right">Volume</th>
              <th className="py-2 px-3 text-right">Chng %</th>
              <th className="py-2 px-3 text-right border-r border-slate-800 text-emerald-400">LTP (Rs.)</th>
              <th className="py-2 px-4 text-center font-extrabold bg-slate-900 text-white">Strike Price</th>
              <th className="py-2 px-3 text-left border-l border-slate-800 text-rose-400">LTP (Rs.)</th>
              <th className="py-2 px-3 text-left">Chng %</th>
              <th className="py-2 px-3 text-left">Volume</th>
              <th className="py-2 px-3 text-left">OI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {chainData?.chain?.map((row) => {
              const isAtm = row.strike === chainData.atm_strike;
              const isCeInMoney = row.strike < chainData.spot_price;
              const isPeInMoney = row.strike > chainData.spot_price;

              return (
                <tr
                  key={row.strike}
                  className={`transition-colors ${
                    isAtm
                      ? 'bg-amber-500/15 font-bold border-y-2 border-amber-500/50'
                      : 'hover:bg-slate-800/40'
                  }`}
                >
                  {/* CALLS */}
                  <td className={`py-2 px-3 text-right ${isCeInMoney ? 'bg-slate-900/40 text-slate-300' : 'text-slate-400'}`}>
                    {row.ce_oi.toLocaleString()}
                  </td>
                  <td className={`py-2 px-3 text-right ${isCeInMoney ? 'bg-slate-900/40 text-slate-300' : 'text-slate-400'}`}>
                    {row.ce_volume.toLocaleString()}
                  </td>
                  <td className={`py-2 px-3 text-right font-bold ${row.ce_chng_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {row.ce_chng_pct >= 0 ? `+${row.ce_chng_pct.toFixed(1)}%` : `${row.ce_chng_pct.toFixed(1)}%`}
                  </td>
                  <td
                    onClick={() => openCalculator(row.strike, 'CE', row.ce_ltp)}
                    className="py-2 px-3 text-right font-extrabold text-emerald-400 cursor-pointer hover:bg-emerald-500/20 border-r border-slate-800 transition-colors"
                    title="Click to calculate Call option profit"
                  >
                    Rs.{row.ce_ltp.toFixed(2)}
                  </td>

                  {/* STRIKE PRICE CENTER */}
                  <td className={`py-2 px-4 text-center font-extrabold text-sm ${isAtm ? 'text-amber-300' : 'text-white'}`}>
                    {row.strike}
                    {isAtm && <span className="ml-1 text-[9px] bg-amber-500 text-slate-950 px-1 py-0.5 rounded font-black">ATM</span>}
                  </td>

                  {/* PUTS */}
                  <td
                    onClick={() => openCalculator(row.strike, 'PE', row.pe_ltp)}
                    className="py-2 px-3 text-left font-extrabold text-rose-400 cursor-pointer hover:bg-rose-500/20 border-l border-slate-800 transition-colors"
                    title="Click to calculate Put option profit"
                  >
                    Rs.{row.pe_ltp.toFixed(2)}
                  </td>
                  <td className={`py-2 px-3 text-left font-bold ${row.pe_chng_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {row.pe_chng_pct >= 0 ? `+${row.pe_chng_pct.toFixed(1)}%` : `${row.pe_chng_pct.toFixed(1)}%`}
                  </td>
                  <td className={`py-2 px-3 text-left ${isPeInMoney ? 'bg-slate-900/40 text-slate-300' : 'text-slate-400'}`}>
                    {row.pe_volume.toLocaleString()}
                  </td>
                  <td className={`py-2 px-3 text-left ${isPeInMoney ? 'bg-slate-900/40 text-slate-300' : 'text-slate-400'}`}>
                    {row.pe_oi.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Profit Calculator Modal */}
      {selectedContract && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0f172a] border border-slate-700 rounded-2xl p-6 max-w-md w-full shadow-2xl relative animate-in fade-in zoom-in-95">
            <button
              onClick={() => setSelectedContract(null)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center space-x-2 mb-4">
              <Calculator className="w-5 h-5 text-amber-400" />
              <h3 className="text-lg font-bold text-white">
                Profit Calculator — {symbol} {selectedContract.strike} {selectedContract.optType}
              </h3>
            </div>

            <div className="space-y-4 mb-6">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Entry Premium (Rs.)</label>
                <input
                  type="number"
                  step="0.05"
                  value={entryPremium}
                  onChange={(e) => setEntryPremium(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white text-sm font-bold focus:outline-none focus:border-amber-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Target Premium (Rs.)</label>
                <input
                  type="number"
                  step="0.05"
                  value={targetPremium}
                  onChange={(e) => setTargetPremium(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white text-sm font-bold focus:outline-none focus:border-amber-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Quantity (Lots)</label>
                <input
                  type="number"
                  min="1"
                  value={lots}
                  onChange={(e) => setLots(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white text-sm font-bold focus:outline-none focus:border-amber-500"
                />
              </div>

              <button
                onClick={handleCalculateProfit}
                disabled={calcLoading}
                className="w-full py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-extrabold text-sm transition-colors shadow-lg shadow-amber-500/20"
              >
                {calcLoading ? 'Calculating...' : 'Calculate Potential Return'}
              </button>
            </div>

            {/* Calculated Output Card */}
            {calcResult && (
              <div className="p-4 rounded-xl bg-slate-900 border border-amber-500/30 space-y-2 text-xs">
                <div className="flex justify-between text-slate-400">
                  <span>Contract Lot Size:</span>
                  <span className="font-bold text-white">{calcResult.lot_size} shares/lot ({calcResult.total_shares} total)</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Total Capital Required:</span>
                  <span className="font-bold text-white">Rs.{calcResult.total_investment.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Profit Per Lot:</span>
                  <span className={`font-bold ${calcResult.profit_per_lot >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {calcResult.profit_per_lot >= 0 ? `+Rs.${calcResult.profit_per_lot.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : `-Rs.${Math.abs(calcResult.profit_per_lot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`}
                  </span>
                </div>
                <div className="flex justify-between text-sm border-t border-slate-800 pt-2 font-bold">
                  <span className="text-slate-200">Total Net Profit:</span>
                  <span className={calcResult.total_profit >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {calcResult.total_profit >= 0 ? `+Rs.${calcResult.total_profit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : `-Rs.${Math.abs(calcResult.total_profit).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`}
                    <span className="ml-1 text-xs">({calcResult.roi_pct >= 0 ? `+${calcResult.roi_pct}%` : `${calcResult.roi_pct}%`})</span>
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
