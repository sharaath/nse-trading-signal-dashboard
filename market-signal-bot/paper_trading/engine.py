import logging
import os
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from db.models import PaperTrade, SystemSettings
from signals.option_chain_provider import NSEOptionChainProvider
from worker.option_scanner import send_telegram_alert
from signals.providers import get_data_provider

logger = logging.getLogger(__name__)

class PaperTradingManager:
    def __init__(self):
        self.chain_provider = NSEOptionChainProvider()

    def update_active_trades(self, db: Session):
        """
        Polls and updates active simulated trades on every tick.
        Executes strict partial profit bookings:
        - Target 1 (40% initial_qty) -> Moves Stop Loss to Break-even.
        - Target 2 (30% initial_qty) -> Trails Stop Loss to Target 1.
        - Target 3 (Remaining 30% initial_qty) -> Closes position.
        Trails Stop Loss continuously using underlying spot ATR boundaries.
        """
        active_trades = db.query(PaperTrade).filter(PaperTrade.status == "ACTIVE").all()
        if not active_trades:
            return

        chat_id = None
        set_chat = db.query(SystemSettings).filter(SystemSettings.key == "telegram_chat_id").first()
        if set_chat:
            chat_id = set_chat.value
        else:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        provider = get_data_provider()

        for trade in active_trades:
            try:
                # 1. Fetch Spot history for ATR calculation
                spot_df = provider.get_history(trade.symbol, interval="15m", period="5d")
                if spot_df.empty:
                    continue
                spot_price = float(spot_df.iloc[-1]["Close"])
                atr = float(spot_df["Close"].rolling(14).std().iloc[-1]) if len(spot_df) >= 14 else spot_price * 0.005

                # 2. Fetch live option chain & contract price
                chain = self.chain_provider.get_full_chain(trade.symbol)
                option_ltp = 0.0
                option_delta = 0.55 if "CALL" in trade.direction else -0.55
                option_spread = 0.005
                option_vol = 1000
                exit_bid = 0.0
                
                strike_num = int(trade.option_contract.split()[1])
                for contract in chain.get("chain", []):
                    if contract["strike"] == strike_num:
                        option_type = "CE" if "CALL" in trade.direction else "PE"
                        option_ltp = contract["ce_ltp"] if option_type == "CE" else contract["pe_ltp"]
                        option_delta = contract["ce_delta"] if option_type == "CE" else contract["pe_delta"]
                        option_spread = contract.get("spread_pct", 0.005)
                        option_vol = contract.get("ce_volume" if option_type == "CE" else "pe_volume", 1000)
                        exit_bid = contract.get("ce_bid" if option_type == "CE" else "pe_bid", 0.0) or 0.0
                        break

                if option_ltp <= 0.0:
                    # Fallback to Black-Scholes estimate
                    from signals.greeks import calculate_black_scholes_price
                    opt_type = "CE" if "CALL" in trade.direction else "PE"
                    option_ltp = calculate_black_scholes_price(spot_price, strike_num, 3.0/365.0, 0.07, 0.15, opt_type)
                    exit_bid = option_ltp - 0.5

                trade.current_price = option_ltp

                # Continuously track MFE (Max Favorable Excursion) & MAE (Max Adverse Excursion)
                unrealized_diff = option_ltp - trade.entry_price
                trade.mfe = max(trade.mfe or 0.0, unrealized_diff if unrealized_diff > 0 else 0.0)
                trade.mae = max(trade.mae or 0.0, -unrealized_diff if unrealized_diff < 0 else 0.0)

                # 3. ATR-based Trailing Stop updates (at 2x ATR distance)
                if "CALL" in trade.direction:
                    spot_trailing_stop = spot_price - 2 * atr
                    projected_sl = trade.entry_price - abs(option_delta) * (spot_df.iloc[0]["Close"] - spot_trailing_stop)
                    if projected_sl > trade.stop_loss:
                        trade.stop_loss = round(projected_sl, 2)
                else:
                    spot_trailing_stop = spot_price + 2 * atr
                    projected_sl = trade.entry_price - abs(option_delta) * (spot_trailing_stop - spot_df.iloc[0]["Close"])
                    if projected_sl > trade.stop_loss:
                        trade.stop_loss = round(projected_sl, 2)

                # Exit fill formulation (Bid - Slippage for option selling)
                slippage_pct_val = trade.slippage_pct or 0.5
                slippage_amt = (slippage_pct_val / 100.0) * option_ltp
                
                if exit_bid > 0.0:
                    exit_fill_price = exit_bid - slippage_amt
                else:
                    exit_fill_price = option_ltp - slippage_amt
                exit_fill_price = round(max(0.1, exit_fill_price), 2)

                # 4. Check Stop Loss
                if option_ltp <= trade.stop_loss:
                    qty_to_close = trade.qty
                    trade.exit_reason = "SL_EXIT"
                    
                    # Exit transaction costs (Brokerage: ₹20, STT: 0.0625% on sell premium, Exchange charges: 0.053%, GST: 18%)
                    brokerage_val = 20.0
                    stt_val = round(0.000625 * exit_fill_price * qty_to_close, 2)
                    exchange_charges_val = round(0.00053 * exit_fill_price * qty_to_close, 2)
                    gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
                    exit_costs = round(brokerage_val + stt_val + exchange_charges_val + gst_val, 2)

                    trade.brokerage += brokerage_val
                    trade.stt += stt_val
                    trade.exchange_charges += exchange_charges_val
                    trade.gst += gst_val
                    trade.total_transaction_cost += exit_costs

                    gross_pnl = round((exit_fill_price - trade.entry_price) * qty_to_close, 2)
                    trade.gross_pnl += gross_pnl
                    trade.qty = 0
                    
                    trade.net_pnl = round(trade.gross_pnl - trade.total_transaction_cost, 2)
                    trade.pnl = trade.net_pnl
                    
                    initial_investment = trade.entry_price * trade.initial_qty
                    trade.roi = round(((trade.pnl / initial_investment) * 100.0) if initial_investment > 0 else 0.0, 2)
                    trade.status = "CLOSED"
                    trade.exit_time = datetime.now(timezone.utc)
                    db.commit()

                    msg = (
                        f"🛑 *STOP LOSS HIT* (40/30/30 Exits)\n\n"
                        f"Contract: `{trade.option_contract}`\n"
                        f"Remaining Qty Closed: `{qty_to_close}`\n"
                        f"Exit Fill Price: ₹{exit_fill_price:.2f} (Entry Fill: ₹{trade.entry_price:.2f})\n"
                        f"Gross P&L: ₹{trade.gross_pnl:.2f}\n"
                        f"Transaction Costs: ₹{trade.total_transaction_cost:.2f}\n"
                        f"Final Net P&L: *₹{trade.net_pnl:,.2f}*\n"
                        f"ROI: *{trade.roi}%*"
                    )
                    if chat_id:
                        send_telegram_alert(msg, chat_id)
                    continue

                # 5. Target 1 Check (Book 40% initial_qty, Move SL to Break-even)
                if not trade.partial_exit_1 and option_ltp >= trade.target_1:
                    trade.partial_exit_1 = True
                    qty_to_close = int(trade.initial_qty * 0.40)
                    if qty_to_close <= 0:
                        qty_to_close = trade.qty // 2
                    
                    brokerage_val = 20.0
                    stt_val = round(0.000625 * exit_fill_price * qty_to_close, 2)
                    exchange_charges_val = round(0.00053 * exit_fill_price * qty_to_close, 2)
                    gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
                    exit_costs = round(brokerage_val + stt_val + exchange_charges_val + gst_val, 2)

                    trade.brokerage += brokerage_val
                    trade.stt += stt_val
                    trade.exchange_charges += exchange_charges_val
                    trade.gst += gst_val
                    trade.total_transaction_cost += exit_costs

                    gross_pnl = round((exit_fill_price - trade.entry_price) * qty_to_close, 2)
                    trade.gross_pnl += gross_pnl
                    trade.qty -= qty_to_close
                    
                    trade.net_pnl = round(trade.gross_pnl - trade.total_transaction_cost, 2)
                    trade.pnl = trade.net_pnl

                    # Move Stop Loss to break-even premium
                    trade.stop_loss = trade.entry_price
                    db.commit()

                    msg = (
                        f"🎯 *TARGET 1 HIT (+30%)*\n\n"
                        f"Contract: `{trade.option_contract}`\n"
                        f"Booked 40% position ({qty_to_close} Qty) at Fill: ₹{exit_fill_price:.2f}\n"
                        f"Stop Loss moved to Break-even: ₹{trade.entry_price:.2f}\n"
                        f"Net P&L (Cumulative): *₹{trade.pnl:,.2f}*"
                    )
                    if chat_id:
                        send_telegram_alert(msg, chat_id)

                # 6. Target 2 Check (Book additional 30% initial_qty, Trail SL to Target 1)
                if trade.partial_exit_1 and not trade.partial_exit_2 and option_ltp >= trade.target_2:
                    trade.partial_exit_2 = True
                    qty_to_close = int(trade.initial_qty * 0.30)
                    if qty_to_close <= 0:
                        qty_to_close = trade.qty // 2
                        
                    brokerage_val = 20.0
                    stt_val = round(0.000625 * exit_fill_price * qty_to_close, 2)
                    exchange_charges_val = round(0.00053 * exit_fill_price * qty_to_close, 2)
                    gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
                    exit_costs = round(brokerage_val + stt_val + exchange_charges_val + gst_val, 2)

                    trade.brokerage += brokerage_val
                    trade.stt += stt_val
                    trade.exchange_charges += exchange_charges_val
                    trade.gst += gst_val
                    trade.total_transaction_cost += exit_costs

                    gross_pnl = round((exit_fill_price - trade.entry_price) * qty_to_close, 2)
                    trade.gross_pnl += gross_pnl
                    trade.qty -= qty_to_close
                    
                    trade.net_pnl = round(trade.gross_pnl - trade.total_transaction_cost, 2)
                    trade.pnl = trade.net_pnl

                    # Trail Stop Loss to Target 1 premium
                    trade.stop_loss = trade.target_1
                    db.commit()

                    msg = (
                        f"🎯 *TARGET 2 HIT (+60%)*\n\n"
                        f"Contract: `{trade.option_contract}`\n"
                        f"Booked additional 30% position ({qty_to_close} Qty) at Fill: ₹{exit_fill_price:.2f}\n"
                        f"Stop Loss trailed to Target 1: ₹{trade.target_1:.2f}\n"
                        f"Net P&L (Cumulative): *₹{trade.pnl:,.2f}*"
                    )
                    if chat_id:
                        send_telegram_alert(msg, chat_id)

                # 7. Target 3 Check (Close remaining position)
                if trade.partial_exit_2 and option_ltp >= trade.target_3:
                    qty_to_close = trade.qty
                    
                    brokerage_val = 20.0
                    stt_val = round(0.000625 * exit_fill_price * qty_to_close, 2)
                    exchange_charges_val = round(0.00053 * exit_fill_price * qty_to_close, 2)
                    gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
                    exit_costs = round(brokerage_val + stt_val + exchange_charges_val + gst_val, 2)

                    trade.brokerage += brokerage_val
                    trade.stt += stt_val
                    trade.exchange_charges += exchange_charges_val
                    trade.gst += gst_val
                    trade.total_transaction_cost += exit_costs

                    gross_pnl = round((exit_fill_price - trade.entry_price) * qty_to_close, 2)
                    trade.gross_pnl += gross_pnl
                    trade.qty = 0
                    
                    trade.net_pnl = round(trade.gross_pnl - trade.total_transaction_cost, 2)
                    trade.pnl = trade.net_pnl
                    
                    initial_investment = trade.entry_price * trade.initial_qty
                    trade.roi = round(((trade.pnl / initial_investment) * 100.0) if initial_investment > 0 else 0.0, 2)
                    trade.exit_reason = "TP_EXIT"
                    trade.status = "CLOSED"
                    trade.exit_time = datetime.now(timezone.utc)
                    db.commit()

                    msg = (
                        f"🏆 *TARGET 3 HIT (+100%)*\n\n"
                        f"Contract: `{trade.option_contract}`\n"
                        f"Remaining 30% position closed at Fill: ₹{exit_fill_price:.2f}\n"
                        f"Gross P&L: ₹{trade.gross_pnl:.2f}\n"
                        f"Transaction Costs: ₹{trade.total_transaction_cost:.2f}\n"
                        f"Final Net P&L: *₹{trade.net_pnl:,.2f}*\n"
                        f"ROI: *{trade.roi}%*"
                    )
                    if chat_id:
                        send_telegram_alert(msg, chat_id)
                    continue

                # 8. Check TIME_EXIT_RULE
                now_utc = datetime.now(timezone.utc)
                entry_utc = trade.entry_time.replace(tzinfo=timezone.utc) if (trade.entry_time and trade.entry_time.tzinfo is None) else (trade.entry_time or now_utc)
                duration_mins = (now_utc - entry_utc).total_seconds() / 60.0
                max_hold = trade.max_holding_time_minutes or 5

                if duration_mins >= max_hold and trade.status == "ACTIVE" and trade.qty > 0:
                    qty_to_close = trade.qty
                    brokerage_val = 20.0
                    stt_val = round(0.000625 * exit_fill_price * qty_to_close, 2)
                    exchange_charges_val = round(0.00053 * exit_fill_price * qty_to_close, 2)
                    gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
                    exit_costs = round(brokerage_val + stt_val + exchange_charges_val + gst_val, 2)

                    trade.brokerage += brokerage_val
                    trade.stt += stt_val
                    trade.exchange_charges += exchange_charges_val
                    trade.gst += gst_val
                    trade.total_transaction_cost += exit_costs

                    gross_pnl = round((exit_fill_price - trade.entry_price) * qty_to_close, 2)
                    trade.gross_pnl += gross_pnl
                    trade.qty = 0
                    trade.net_pnl = round(trade.gross_pnl - trade.total_transaction_cost, 2)
                    trade.pnl = trade.net_pnl
                    initial_investment = trade.entry_price * trade.initial_qty
                    trade.roi = round(((trade.pnl / initial_investment) * 100.0) if initial_investment > 0 else 0.0, 2)
                    trade.status = "CLOSED"
                    trade.exit_time = now_utc

                    if option_ltp >= trade.target_1:
                        trade.exit_reason = "TP_EXIT"
                    elif option_ltp <= trade.stop_loss:
                        trade.exit_reason = "SL_EXIT"
                    else:
                        trade.exit_reason = "TIME_EXIT"

                    db.commit()

                    msg = (
                        f"⏱️ *{trade.exit_reason} (Holding Time Limit {max_hold}m Reached)*\n\n"
                        f"Contract: `{trade.option_contract}`\n"
                        f"Remaining Qty Closed: `{qty_to_close}`\n"
                        f"Exit Fill Price: ₹{exit_fill_price:.2f} (Entry: ₹{trade.entry_price:.2f})\n"
                        f"MFE (Max Gain): +₹{trade.mfe:.2f} | MAE (Max Drawdown): -₹{trade.mae:.2f}\n"
                        f"Holding Duration: {duration_mins:.1f} minutes\n"
                        f"Final Net P&L: *₹{trade.net_pnl:,.2f}*\n"
                        f"ROI: *{trade.roi}%*"
                    )
                    if chat_id:
                        send_telegram_alert(msg, chat_id)
                    continue

            except Exception as e:
                logger.error(f"Error updating paper trade {trade.id}: {e}")
