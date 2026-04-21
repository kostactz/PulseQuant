import React, { useMemo, useState } from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface Trade {
  timestamp: number;
  side: string;
  price: number;
  qty: number;
  type?: string;
  reason?: string;
  indicators?: any;
}

interface Cancellation {
  timestamp: number;
  submitted_at?: number;
  resting_ms?: number;
  side: string;
  price: number;
  qty: number;
  reason: string;
  trigger_detail?: {
    zscore_gate?: boolean;
    zscore_cancel_level?: number;
  };
  toxicity?: {
    zscore?: number;
    spread?: number;
    beta?: number;
  };
}

interface TradesListProps {
  trades: Trade[] | null;
  cancellations?: Cancellation[];
  pendingOrders?: any[];
}

export const TradesList: React.FC<TradesListProps> = ({ trades, cancellations = [], pendingOrders = [] }) => {
  const events = useMemo(() => {
    const tradeObjects: Trade[] = (trades && trades.length > 0) ? trades : [];
    return [
      ...pendingOrders.map((order) => ({ type: 'pending' as const, timestamp: order.submitted_at || 0, order })),
      ...tradeObjects.map((trade) => ({ type: 'trade' as const, timestamp: trade.timestamp, trade })),
      ...cancellations.map((cancel) => ({ type: 'cancel' as const, timestamp: cancel.timestamp, cancel })),
    ].sort((a, b) => b.timestamp - a.timestamp);
  }, [trades, cancellations, pendingOrders]);

  const [openRows, setOpenRows] = useState<Record<string, boolean>>({});

  const formatTime = (ts: number) => {
    const date = new Date(ts);
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
  };

  const toggleRow = (key: string) => setOpenRows((s) => ({ ...s, [key]: !s[key] }));

  const copyJSON = async (obj: any) => {
    try { await navigator.clipboard.writeText(JSON.stringify(obj, null, 2)); } catch (e) { /* noop */ }
  };

  // Real-time filters
  const [eventFilter, setEventFilter] = useState<'all' | 'fills' | 'cancels'>('all');
  const [sideFilter, setSideFilter] = useState<'all' | 'buy' | 'sell'>('all');
  const [reasonQuery, setReasonQuery] = useState<string>('');
  const [minRestSec, setMinRestSec] = useState<number>(0);

  const filteredEvents = useMemo(() => {
    const q = reasonQuery.trim().toLowerCase();
    return events.filter((e) => {
      if (eventFilter === 'fills' && e.type !== 'trade') return false;
      if (eventFilter === 'cancels' && e.type !== 'cancel') return false;
      if (sideFilter !== 'all') {
        const side = e.type === 'trade' ? e.trade.side : (e.type === 'cancel' ? e.cancel.side : e.order.side);
        if (side !== sideFilter) return false;
      }
      if (e.type === 'cancel' && minRestSec > 0) {
        const resting = (e.cancel.resting_ms ?? 0) / 1000;
        if (resting < minRestSec) return false;
      }
      if (q) {
        if (e.type === 'cancel') {
          const r = (e.cancel.reason || '').toLowerCase();
          const inReason = r.includes(q);
          const inTrigger = JSON.stringify(e.cancel.trigger_detail || {}).toLowerCase().includes(q);
          if (!inReason && !inTrigger) return false;
        } else if (e.type === 'trade') {
          const r = (e.trade.reason || '').toLowerCase();
          if (!r.includes(q)) return false;
        } else if (e.type === 'pending') {
          const r = (e.order.reason || '').toLowerCase();
          if (!r.includes(q)) return false;
        }
      }
      return true;
    });
  }, [events, eventFilter, sideFilter, reasonQuery, minRestSec]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="inline-flex bg-gray-50 rounded-lg p-1">
          <button className={`px-3 py-1 text-xs ${eventFilter === 'all' ? 'bg-white shadow-sm' : ''}`} onClick={() => setEventFilter('all')}>All</button>
          <button className={`px-3 py-1 text-xs ${eventFilter === 'fills' ? 'bg-white shadow-sm' : ''}`} onClick={() => setEventFilter('fills')}>Fills</button>
          <button className={`px-3 py-1 text-xs ${eventFilter === 'cancels' ? 'bg-white shadow-sm' : ''}`} onClick={() => setEventFilter('cancels')}>Cancels</button>
        </div>
        <div className="inline-flex bg-gray-50 rounded-lg p-1">
          <button className={`px-2 py-1 text-xs ${sideFilter === 'all' ? 'bg-white shadow-sm' : ''}`} onClick={() => setSideFilter('all')}>All</button>
          <button className={`px-2 py-1 text-xs ${sideFilter === 'buy' ? 'bg-white shadow-sm' : ''}`} onClick={() => setSideFilter('buy')}>Buy</button>
          <button className={`px-2 py-1 text-xs ${sideFilter === 'sell' ? 'bg-white shadow-sm' : ''}`} onClick={() => setSideFilter('sell')}>Sell</button>
        </div>
        <div className="flex items-center gap-2">
          <input placeholder="reason filter" value={reasonQuery} onChange={(e) => setReasonQuery(e.target.value)} className="text-xs px-2 py-1 border rounded" />
          <input type="number" min={0} placeholder="min rest s" value={minRestSec} onChange={(e) => setMinRestSec(Number(e.target.value || 0))} className="w-20 text-xs px-2 py-1 border rounded" />
        </div>
      </div>

      {/* Desktop header */}
      <div className="hidden sm:grid grid-cols-[95px_95px_95px_110px_90px_1fr] text-gray-500 font-medium pb-2 border-b border-gray-200 mb-2 text-xs uppercase tracking-wider">
        <div>Time</div>
        <div>Event</div>
        <div>Side</div>
        <div className="text-right">Price</div>
        <div className="text-right">Qty</div>
        <div className="text-right">Debug</div>
      </div>

      {/* Desktop list */}
      <div className="hidden sm:block flex-1 overflow-y-auto pr-2 space-y-1 custom-scrollbar min-h-0">
        {filteredEvents.map((event, i) => {
          const key = `${event.type}-${i}-${event.timestamp}`;
          if (event.type === 'trade') {
            const trade = event.trade;
            const isBuy = trade.side === 'buy';
            return (
              <div key={key}>
                <div className="grid grid-cols-[95px_95px_95px_110px_90px_1fr] items-center py-1.5 text-sm border-b border-emerald-100 last:border-0 bg-emerald-50/10 hover:bg-emerald-50 transition-colors rounded px-1 cursor-pointer" onClick={() => toggleRow(key)}>
                  <div className="text-gray-500 font-mono text-xs min-w-0">{formatTime(trade.timestamp)}</div>
                  <div className="text-[10px] uppercase tracking-wide text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5 w-fit">Fill</div>
                  <div className={`flex items-center gap-1 font-medium ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>
                    {isBuy ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                    {isBuy ? 'BUY' : 'SELL'}
                  </div>
                  <div className="text-right font-mono text-gray-700 min-w-0">${trade.price?.toFixed(2) ?? '-'}</div>
                  <div className="text-right font-mono text-xs text-gray-600 leading-tight min-w-0">{trade.qty !== undefined ? (Number.isInteger(trade.qty) ? trade.qty : trade.qty.toFixed(4)) : '-'}</div>
                  <div className="text-right font-mono text-xs text-gray-600 truncate min-w-0" title={trade.reason}>{trade.reason || '-'}</div>
                </div>

                {openRows[key] && (
                  <div className="bg-white border-l-4 border-emerald-200 p-3 text-xs text-gray-700 rounded-b mb-2">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <div className="font-medium text-sm">Trade Detail</div>
                        <div className="text-[13px] text-gray-600 mt-1">Type: {trade.type || 'taker'}</div>
                        <div className="text-[13px] text-gray-600">Reason: {trade.reason || '-'}</div>
                      </div>
                      <div>
                        <div className="font-medium text-sm">Indicator Snapshot</div>
                        <div className="text-[13px] text-gray-600 mt-1">Z-Score: {trade.indicators?.zscore?.toFixed(3) ?? '-'}</div>
                        <div className="text-[13px] text-gray-600">Spread: {trade.indicators?.spread?.toFixed(3) ?? '-'}</div>
                      </div>
                    </div>

                    <div className="mt-3 flex gap-2">
                      <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                      <button onClick={() => copyJSON(trade)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                    </div>
                  </div>
                )}
              </div>
            );
          }

          if (event.type === 'pending') {
            const order = event.order;
            const isBuy = order.side === 'buy';
            return (
              <div key={key}>
                <div className="grid grid-cols-[95px_95px_95px_110px_90px_1fr] items-center py-1.5 text-sm border-b border-blue-100 last:border-0 bg-blue-50/30 hover:bg-blue-50 transition-colors rounded px-1 cursor-pointer" onClick={() => toggleRow(key)}>
                  <div className="text-gray-500 font-mono text-xs min-w-0">{formatTime(order.submitted_at || event.timestamp)}</div>
                  <div className="text-[10px] uppercase tracking-wide text-blue-700 bg-blue-100 border border-blue-200 rounded px-1.5 py-0.5 w-fit animate-pulse">Pending</div>
                  <div className={`flex items-center gap-1 font-medium ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>
                    {isBuy ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                    {isBuy ? 'BUY' : 'SELL'}
                  </div>
                  <div className="text-right font-mono text-gray-700 min-w-0">${order.price?.toFixed(2) ?? '-'}</div>
                  <div className="text-right font-mono text-xs text-gray-600 leading-tight min-w-0">{order.qty !== undefined ? (Number.isInteger(order.qty) ? order.qty : order.qty.toFixed(4)) : '-'}</div>
                  <div className="text-right font-mono text-xs text-gray-600 truncate min-w-0" title={order.reason}>{order.reason || '-'}</div>
                </div>

                {openRows[key] && (
                  <div className="bg-white border-l-4 border-blue-200 p-3 text-xs text-gray-700 rounded-b mb-2">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <div className="font-medium text-sm">Order Detail</div>
                        <div className="text-[13px] text-gray-600 mt-1">Type: {order.type || 'maker'}</div>
                        <div className="text-[13px] text-gray-600">Status: {order.status}</div>
                        <div className="text-[13px] text-gray-600">Reason: {order.reason || '-'}</div>
                      </div>
                      <div>
                        <div className="font-medium text-sm">Indicator Snapshot</div>
                        <div className="text-[13px] text-gray-600 mt-1">Z-Score: {order.ind?.zscore?.toFixed(3) ?? '-'}</div>
                        <div className="text-[13px] text-gray-600">Spread: {order.ind?.spread?.toFixed(3) ?? '-'}</div>
                      </div>
                    </div>

                    <div className="mt-3 flex gap-2">
                      <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                      <button onClick={() => copyJSON(order)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                    </div>
                  </div>
                )}
              </div>
            );
          }

          const cancel = event.cancel;
          const isBuy = cancel.side === 'buy';
          const zscore = cancel.toxicity?.zscore ?? 0;
          const spread = cancel.toxicity?.spread ?? 0;
          const restingSec = (cancel.resting_ms ?? 0) / 1000;
          const gates = [cancel.trigger_detail?.zscore_gate ? 'Z-SCORE' : null].filter(Boolean).join('+');

          return (
            <div key={key}>
              <div className="grid grid-cols-[95px_95px_95px_110px_90px_1fr] items-center py-1.5 text-sm border-b border-amber-100 last:border-0 bg-amber-50/30 hover:bg-amber-50 transition-colors rounded px-1" onClick={() => toggleRow(key)}>
                <div className="text-gray-600 font-mono text-xs min-w-0" title={`Submitted ${formatTime(cancel.submitted_at ?? cancel.timestamp)}`}>{formatTime(cancel.timestamp)}</div>
                <div className="text-[10px] uppercase tracking-wide text-amber-700 bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5 w-fit">Cancel</div>
                <div className={`flex items-center gap-1 font-medium ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>
                  {isBuy ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                  {isBuy ? 'BUY' : 'SELL'}
                </div>
                <div className="text-right font-mono text-gray-700 min-w-0">${cancel.price?.toFixed(2) ?? '-'}</div>
                <div className="text-right font-mono text-xs text-gray-600 leading-tight min-w-0">{cancel.qty !== undefined ? (Number.isInteger(cancel.qty) ? cancel.qty : cancel.qty.toFixed(4)) : '-'}</div>
                <div className="text-right text-xs text-gray-700 truncate">{gates || 'TOX'} {restingSec.toFixed(1)}s | z-score {zscore.toFixed(2)} spread {spread.toFixed(2)}</div>
              </div>

              {openRows[key] && (
                <div className="bg-white border-l-4 border-amber-200 p-3 text-xs text-gray-700 rounded-b mb-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <div className="font-medium text-sm">Cancel Detail</div>
                      <div className="text-[13px] text-gray-600 mt-1">Submitted: {formatTime(cancel.submitted_at ?? cancel.timestamp)} ({((cancel.resting_ms ?? 0) / 1000).toFixed(2)}s)</div>
                      <div className="text-[13px] text-gray-600">Reason: {cancel.reason}</div>
                      <div className="text-[13px] text-gray-600">Triggers: {gates || 'Z-SCORE'}</div>
                    </div>
                    <div>
                      <div className="font-medium text-sm">Indicator Snapshot</div>
                      <div className="text-[13px] text-gray-600 mt-1">Z-Score: {zscore.toFixed(3)}</div>
                      <div className="text-[13px] text-gray-600">Spread: {spread.toFixed(3)}</div>
                    </div>
                  </div>

                  <div className="mt-3 flex gap-2">
                    <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                    <button onClick={() => copyJSON(cancel)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Mobile stacked list */}
      <div className="sm:hidden flex-1 overflow-y-auto space-y-2 min-h-0">
        {filteredEvents.map((event, i) => {
          const key = `${event.type}-${i}-${event.timestamp}`;
          if (event.type === 'trade') {
            const trade = event.trade;
            const isBuy = trade.side === 'buy';
            return (
              <div key={key} className="bg-white border border-gray-100 rounded-lg p-3 shadow-sm">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="font-mono text-xs text-gray-500">{formatTime(trade.timestamp)}</div>
                    <div className="text-[10px] uppercase tracking-wide text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5">Fill</div>
                  </div>
                  <div className={`text-xs font-semibold ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>{isBuy ? 'BUY' : 'SELL'}</div>
                </div>

                <div className="mt-2 flex items-center justify-between">
                  <div className="font-mono text-sm">${trade.price?.toFixed(2) ?? '-'}</div>
                  <div className="font-mono text-sm">{trade.qty !== undefined ? (Number.isInteger(trade.qty) ? trade.qty : trade.qty.toFixed(4)) : '-'}</div>
                </div>

                <div className="mt-2 text-xs text-gray-600 truncate">{trade.reason || '-'}</div>

                {openRows[key] && (
                  <div className="mt-3 border-t pt-3 text-xs text-gray-700">
                    <div className="font-medium">Trade Detail</div>
                    <div className="text-[13px] text-gray-600 mt-1">Type: {trade.type || 'taker'}</div>
                    <div className="text-[13px] text-gray-600">Reason: {trade.reason || '-'}</div>
                    <div className="mt-2 flex gap-2">
                      <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                      <button onClick={() => copyJSON(trade)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                    </div>
                  </div>
                )}

                {!openRows[key] && (
                  <div className="mt-3 flex justify-end">
                    <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-50 rounded border">Details</button>
                  </div>
                )}
              </div>
            );
          }

          if (event.type === 'pending') {
            const order = event.order;
            const isBuy = order.side === 'buy';
            return (
              <div key={key} className="bg-white border border-gray-100 rounded-lg p-3 shadow-sm">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="font-mono text-xs text-gray-500">{formatTime(order.submitted_at || event.timestamp)}</div>
                    <div className="text-[10px] uppercase tracking-wide text-blue-700 bg-blue-50 border border-blue-100 rounded px-1.5 py-0.5">Pending</div>
                  </div>
                  <div className={`text-xs font-semibold ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>{isBuy ? 'BUY' : 'SELL'}</div>
                </div>

                <div className="mt-2 flex items-center justify-between">
                  <div className="font-mono text-sm">${order.price?.toFixed(2) ?? '-'}</div>
                  <div className="font-mono text-sm">{order.qty !== undefined ? (Number.isInteger(order.qty) ? order.qty : order.qty.toFixed(4)) : '-'}</div>
                </div>

                <div className="mt-2 text-xs text-gray-600 truncate">{order.reason || '-'}</div>

                {openRows[key] && (
                  <div className="mt-3 border-t pt-3 text-xs text-gray-700">
                    <div className="font-medium">Order Detail</div>
                    <div className="text-[13px] text-gray-600 mt-1">Type: {order.type || 'maker'}</div>
                    <div className="text-[13px] text-gray-600">Status: {order.status}</div>
                    <div className="text-[13px] text-gray-600">Reason: {order.reason || '-'}</div>
                    <div className="mt-2 flex gap-2">
                      <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                      <button onClick={() => copyJSON(order)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                    </div>
                  </div>
                )}

                {!openRows[key] && (
                  <div className="mt-3 flex justify-end">
                    <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-50 rounded border">Details</button>
                  </div>
                )}
              </div>
            );
          }

          const cancel = event.cancel;
          const isBuy = cancel.side === 'buy';
          const zscore = cancel.toxicity?.zscore ?? 0;
          const spread = cancel.toxicity?.spread ?? 0;
          const restingSec = (cancel.resting_ms ?? 0) / 1000;
          const gates = [cancel.trigger_detail?.zscore_gate ? 'Z-SCORE' : null].filter(Boolean).join('+');

          return (
            <div key={key} className="bg-white border border-gray-100 rounded-lg p-3 shadow-sm">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="font-mono text-xs text-gray-500">{formatTime(cancel.timestamp)}</div>
                  <div className="text-[10px] uppercase tracking-wide text-amber-700 bg-amber-50 border border-amber-100 rounded px-1.5 py-0.5">Cancel</div>
                </div>
                <div className={`text-xs font-semibold ${isBuy ? 'text-emerald-600' : 'text-red-600'}`}>{isBuy ? 'BUY' : 'SELL'}</div>
              </div>

              <div className="mt-2 flex items-center justify-between">
                <div className="font-mono text-sm">${cancel.price?.toFixed(2) ?? '-'}</div>
                <div className="font-mono text-sm">{cancel.qty !== undefined ? (Number.isInteger(cancel.qty) ? cancel.qty : cancel.qty.toFixed(4)) : '-'}</div>
              </div>

              <div className="mt-2 text-xs text-gray-600 truncate">{gates || 'TOX'} {restingSec.toFixed(1)}s | z-score {zscore.toFixed(2)} spread {spread.toFixed(2)}</div>

              {openRows[key] && (
                <div className="mt-3 border-t pt-3 text-xs text-gray-700">
                  <div className="font-medium">Cancel Detail</div>
                  <div className="text-[13px] text-gray-600 mt-1">Submitted: {formatTime(cancel.submitted_at ?? cancel.timestamp)} ({((cancel.resting_ms ?? 0) / 1000).toFixed(2)}s)</div>
                  <div className="text-[13px] text-gray-600">Reason: {cancel.reason}</div>
                  <div className="text-[13px] text-gray-600">Triggers: {gates || 'Z-SCORE'}</div>
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-100 rounded">Close</button>
                    <button onClick={() => copyJSON(cancel)} className="px-2 py-1 text-xs bg-gray-100 rounded">Copy JSON</button>
                  </div>
                </div>
              )}

              {!openRows[key] && (
                <div className="mt-3 flex justify-end">
                  <button onClick={() => toggleRow(key)} className="px-2 py-1 text-xs bg-gray-50 rounded border">Details</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
