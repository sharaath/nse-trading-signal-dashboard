import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import uuid
import logging

from signals.engine import calculate_crt_po3_signal
from signals.premarket import calculate_premarket_bias

logger = logging.getLogger(__name__)

class CRTPO3Backtester:
    """
    Realistic, Point-in-Time CRT + PO3 Backtesting Engine for NIFTY & BANK NIFTY.
    - Strictly sequential bar-by-bar stepping (timestamp <= T)
    - Full Indian statutory transaction costs & configurable slippage
    - Tracks Index P&L vs Option Premium P&L
    - Continuous MFE / MAE tracking for time-exit optimization
    - Evaluates holding times: 1m, 3m, 5m, 10m, 15m
    """
    def __init__(
        self,
        symbol: str = "NIFTY",
        lot_size: int = 50,
        brokerage_per_order: float = 20.0,
        stt_rate_sell: float = 0.000625,
        exchange_turnover_rate: float = 0.00053,
        gst_rate: float = 0.18,
        stamp_duty_rate: float = 0.00003,
        sebi_turnover_rate: float = 0.000001,
        default_slippage: float = 0.005
    ):
        self.symbol = symbol.upper()
        self.lot_size = lot_size
        self.brokerage = brokerage_per_order
        self.stt_rate = stt_rate_sell
        self.exchange_rate = exchange_turnover_rate
        self.gst_rate = gst_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.sebi_rate = sebi_turnover_rate
        self.default_slippage = default_slippage

    def calculate_statutory_costs(self, entry_price: float, exit_price: float, qty: int) -> Dict[str, float]:
        """Calculates exact Indian statutory transaction costs for options."""
        buy_value = entry_price * qty
        sell_value = exit_price * qty
        turnover = buy_value + sell_value

        brokerage_total = self.brokerage * 2.0  # Entry + Exit
        stt = round(sell_value * self.stt_rate, 2)
        exchange_charges = round(turnover * self.exchange_rate, 2)
        gst = round((brokerage_total + exchange_charges) * self.gst_rate, 2)
        stamp_duty = round(buy_value * self.stamp_duty_rate, 2)
        sebi_charges = round(turnover * self.sebi_rate, 2)

        total_costs = round(brokerage_total + stt + exchange_charges + gst + stamp_duty + sebi_charges, 2)

        return {
            "brokerage": brokerage_total,
            "stt": stt,
            "exchange_charges": exchange_charges,
            "gst": gst,
            "stamp_duty": stamp_duty,
            "sebi_charges": sebi_charges,
            "total_costs": total_costs
        }

    def run_backtest(
        self,
        df_1m: pd.DataFrame,
        holding_periods: List[int] = [1, 3, 5, 10, 15],
        slippages: List[float] = [0.001, 0.0025, 0.005, 0.010],
        min_signal_score: float = 7.0,
        min_rr: float = 1.5,
        sweep_mode: str = "LIVE_SWEEP",
        delta: float = 0.55
    ) -> Dict[str, Any]:
        """
        Runs sequential simulation across multiple holding times and slippage parameters.
        Returns segregated reports for CALL vs PUT and overall metrics.
        """
        if df_1m.empty or len(df_1m) < 60:
            return {"error": "Insufficient historical data for backtesting"}

        # Ensure datetime index
        if not isinstance(df_1m.index, pd.DatetimeIndex):
            df_1m.index = pd.to_datetime(df_1m.index)
        df_1m = df_1m.sort_index()

        results_by_holding_time = {}

        for hold_mins in holding_periods:
            for slip in slippages:
                key = f"hold_{hold_mins}m_slip_{int(slip*10000)}bps"
                trades, no_trades_count = self._simulate_single_run(
                    df_1m=df_1m,
                    max_hold_mins=hold_mins,
                    slippage=slip,
                    min_signal_score=min_signal_score,
                    min_rr=min_rr,
                    sweep_mode=sweep_mode,
                    delta=delta
                )
                metrics = self._compute_performance_metrics(trades, no_trades_count)
                metrics["max_holding_time_minutes"] = hold_mins
                metrics["slippage_percent"] = slip * 100.0
                results_by_holding_time[key] = metrics

        # Select standard baseline: 5m holding time with default slippage
        baseline_key = f"hold_5m_slip_{int(self.default_slippage*10000)}bps"
        baseline_metrics = results_by_holding_time.get(baseline_key, list(results_by_holding_time.values())[0])

        return {
            "symbol": self.symbol,
            "total_bars_tested": len(df_1m),
            "start_time": str(df_1m.index[0]),
            "end_time": str(df_1m.index[-1]),
            "baseline_metrics": baseline_metrics,
            "parameter_matrix": results_by_holding_time
        }

    def _simulate_single_run(
        self,
        df_1m: pd.DataFrame,
        max_hold_mins: int,
        slippage: float,
        min_signal_score: float,
        min_rr: float,
        sweep_mode: str,
        delta: float
    ) -> (List[Dict[str, Any]], int):
        """Simulates sequentially bar-by-bar with zero future lookahead."""
        trades: List[Dict[str, Any]] = []
        no_trades_count = 0
        active_trade: Optional[Dict[str, Any]] = None

        # Build resampled HTF bars point-in-time safely
        # Step through bars sequentially
        n = len(df_1m)
        start_idx = 40  # warmup bars

        for i in range(start_idx, n):
            current_bar = df_1m.iloc[i]
            bar_time = df_1m.index[i]

            # 1. Update Active Trade if any
            if active_trade is not None:
                entry_time = active_trade["entry_time"]
                hold_duration = (bar_time - entry_time).total_seconds() / 60.0
                spot_price = float(current_bar["Close"])
                spot_high = float(current_bar["High"])
                spot_low = float(current_bar["Low"])

                opt_dir = active_trade["direction"]  # "BUY_CALL" or "BUY_PUT"
                idx_entry = active_trade["index_entry"]
                opt_entry = active_trade["option_entry"]
                opt_sl = active_trade["option_sl"]
                opt_target = active_trade["option_target"]

                # Synthetic Option Current Valuation using Delta approximation
                if opt_dir == "BUY_CALL":
                    curr_opt_high = max(1.0, opt_entry + delta * (spot_high - idx_entry))
                    curr_opt_low = max(1.0, opt_entry + delta * (spot_low - idx_entry))
                    curr_opt_close = max(1.0, opt_entry + delta * (spot_price - idx_entry))
                else:
                    curr_opt_high = max(1.0, opt_entry + delta * (idx_entry - spot_low))
                    curr_opt_low = max(1.0, opt_entry + delta * (idx_entry - spot_high))
                    curr_opt_close = max(1.0, opt_entry + delta * (idx_entry - spot_price))

                # Track MFE and MAE
                active_trade["mfe"] = max(active_trade["mfe"], curr_opt_high - opt_entry)
                active_trade["mae"] = max(active_trade["mae"], opt_entry - curr_opt_low)

                # Check Exit Conditions:
                # TIME_EXIT_RULE:
                # If target was reached: TP_EXIT
                # Else if stop was reached: SL_EXIT
                # Else if MAX_HOLDING_TIME reached: TIME_EXIT
                exit_triggered = False
                exit_price = curr_opt_close
                exit_reason = "TIME_EXIT"

                if curr_opt_high >= opt_target:
                    exit_triggered = True
                    exit_price = opt_target
                    exit_reason = "TP_EXIT"
                elif curr_opt_low <= opt_sl:
                    exit_triggered = True
                    exit_price = opt_sl
                    exit_reason = "SL_EXIT"
                elif hold_duration >= max_hold_mins:
                    exit_triggered = True
                    exit_price = curr_opt_close
                    if curr_opt_close >= opt_target:
                        exit_reason = "TP_EXIT"
                    elif curr_opt_close <= opt_sl:
                        exit_reason = "SL_EXIT"
                    else:
                        exit_reason = "TIME_EXIT"

                if exit_triggered:
                    # Apply slippage on exit
                    fill_exit_price = max(0.1, exit_price * (1.0 - slippage))
                    costs = self.calculate_statutory_costs(active_trade["fill_entry_price"], fill_exit_price, self.lot_size)

                    opt_gross = round((fill_exit_price - active_trade["fill_entry_price"]) * self.lot_size, 2)
                    opt_net = round(opt_gross - costs["total_costs"], 2)

                    # Underlying Index movement P&L
                    if opt_dir == "BUY_CALL":
                        idx_gross_pts = round(spot_price - idx_entry, 2)
                    else:
                        idx_gross_pts = round(idx_entry - spot_price, 2)

                    active_trade["exit_time"] = bar_time
                    active_trade["exit_reason"] = exit_reason
                    active_trade["exit_price"] = round(exit_price, 2)
                    active_trade["fill_exit_price"] = round(fill_exit_price, 2)
                    active_trade["holding_minutes"] = round(hold_duration, 1)
                    active_trade["transaction_costs"] = costs["total_costs"]
                    active_trade["slippage_costs"] = round((active_trade["fill_entry_price"] - active_trade["option_entry"] + exit_price - fill_exit_price) * self.lot_size, 2)
                    active_trade["option_gross_pnl"] = opt_gross
                    active_trade["option_net_pnl"] = opt_net
                    active_trade["index_pnl_pts"] = idx_gross_pts
                    active_trade["is_win"] = (opt_net > 0.0)

                    trades.append(active_trade)
                    active_trade = None
                continue

            # 2. Sequential Point-in-Time Slice
            df_slice_1m = df_1m.iloc[max(0, i - 120):i + 1]

            # Construct 5M, 15M, and 4H bars strictly from df_slice_1m
            df_slice_5m = df_slice_1m.resample("5min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
            df_slice_15m = df_slice_1m.resample("15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
            df_slice_4h = df_slice_1m.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()

            # Execute CRT + PO3 Engine
            analysis = calculate_crt_po3_signal(
                df_1m=df_slice_1m,
                df_5m=df_slice_5m,
                df_15m=df_slice_15m,
                df_4h=df_slice_4h,
                symbol=self.symbol,
                current_time=bar_time,
                min_signal_score=min_signal_score,
                min_rr=min_rr,
                sweep_mode=sweep_mode,
                force_session_valid=True
            )

            if analysis["status"] == "SIGNAL_DETECTED" and analysis["signal"] in ["BUY", "SELL"]:
                opt_dir = "BUY_CALL" if analysis["signal"] == "BUY" else "BUY_PUT"
                opt_entry = float(analysis["option_entry"])
                fill_entry_price = round(opt_entry * (1.0 + slippage), 2)

                active_trade = {
                    "signal_id": analysis["signal_id"],
                    "entry_time": bar_time,
                    "direction": opt_dir,
                    "index_direction": analysis["index_direction"],
                    "index_entry": analysis["index_entry"],
                    "index_stop": analysis["index_stop"],
                    "index_target": analysis["index_target"],
                    "option_entry": opt_entry,
                    "fill_entry_price": fill_entry_price,
                    "option_sl": float(analysis["option_sl"]),
                    "option_target": float(analysis["option_target"]),
                    "signal_score": analysis["signal_score"],
                    "mfe": 0.0,
                    "mae": 0.0
                }
            else:
                no_trades_count += 1

        return trades, no_trades_count

    def _compute_performance_metrics(self, trades: List[Dict[str, Any]], no_trades_count: int) -> Dict[str, Any]:
        """Calculates institutional statistical performance metrics."""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "no_trades_count": no_trades_count,
                "win_rate": 0.0,
                "loss_rate": 0.0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown": 0.0,
                "max_consecutive_losses": 0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_holding_time": 0.0,
                "avg_mfe": 0.0,
                "avg_mae": 0.0,
                "total_transaction_costs": 0.0,
                "total_slippage_costs": 0.0,
                "call_trades": {},
                "put_trades": {}
            }

        call_trades = [t for t in trades if t["direction"] == "BUY_CALL"]
        put_trades = [t for t in trades if t["direction"] == "BUY_PUT"]

        wins = [t for t in trades if t["is_win"]]
        losses = [t for t in trades if not t["is_win"]]

        gross_pnl = sum(t["option_gross_pnl"] for t in trades)
        net_pnl = sum(t["option_net_pnl"] for t in trades)
        total_costs = sum(t["transaction_costs"] for t in trades)
        total_slippage = sum(t["slippage_costs"] for t in trades)

        gross_wins = sum(t["option_gross_pnl"] for t in wins)
        gross_losses = abs(sum(t["option_gross_pnl"] for t in losses))

        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)
        win_rate = round(len(wins) / total_trades * 100.0, 1)
        loss_rate = round(len(losses) / total_trades * 100.0, 1)

        avg_win = round(sum(t["option_net_pnl"] for t in wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(sum(t["option_net_pnl"] for t in losses) / len(losses), 2) if losses else 0.0
        expectancy = round((win_rate / 100.0 * avg_win) + (loss_rate / 100.0 * avg_loss), 2)

        # Max Drawdown
        cum_pnl = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cum_pnl += t["option_net_pnl"]
            if cum_pnl > peak:
                peak = cum_pnl
            dd = peak - cum_pnl
            if dd > max_dd:
                max_dd = dd

        # Max Consecutive Losses
        consec_losses = 0
        max_consec = 0
        for t in trades:
            if not t["is_win"]:
                consec_losses += 1
                if consec_losses > max_consec:
                    max_consec = consec_losses
            else:
                consec_losses = 0

        avg_hold = round(sum(t["holding_minutes"] for t in trades) / total_trades, 1)
        avg_mfe = round(sum(t["mfe"] for t in trades) / total_trades, 2)
        avg_mae = round(sum(t["mae"] for t in trades) / total_trades, 2)

        def get_sub_metrics(sub_list):
            if not sub_list:
                return {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0}
            sub_w = [t for t in sub_list if t["is_win"]]
            return {
                "trades": len(sub_list),
                "net_pnl": round(sum(t["option_net_pnl"] for t in sub_list), 2),
                "win_rate": round(len(sub_w) / len(sub_list) * 100.0, 1),
                "avg_mfe": round(sum(t["mfe"] for t in sub_list) / len(sub_list), 2),
                "avg_mae": round(sum(t["mae"] for t in sub_list) / len(sub_list), 2)
            }

        return {
            "total_trades": total_trades,
            "no_trades_count": no_trades_count,
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown": round(max_dd, 2),
            "max_consecutive_losses": max_consec,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_holding_time": avg_hold,
            "avg_mfe": avg_mfe,
            "avg_mae": avg_mae,
            "total_transaction_costs": round(total_costs, 2),
            "total_slippage_costs": round(total_slippage, 2),
            "call_trades": get_sub_metrics(call_trades),
            "put_trades": get_sub_metrics(put_trades)
        }
