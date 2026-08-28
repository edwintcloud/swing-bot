import { useEffect, useState } from 'react';
import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Gauge,
  LayoutDashboard,
  Menu,
  Pause,
  Play,
  RefreshCw,
  Settings,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  WalletCards,
  X,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const number = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
const compactMoney = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
});

const EMPTY_STATE = {
  status: 'offline', paused: true, equity: null, positions: [], trades: [], equity_curve: [], updated_at: null,
};

function valueClass(value) {
  return value > 0 ? 'gain' : value < 0 ? 'loss' : '';
}

function formatTime(value, options = {}) {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat('en-US', options).format(new Date(value));
}

function durationSince(value) {
  if (!value) return '--';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function useDashboardState() {
  const [state, setState] = useState(EMPTY_STATE);
  const [reachable, setReachable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function refresh() {
    try {
      const response = await fetch('/api/state', { cache: 'no-store' });
      if (!response.ok) throw new Error('Dashboard state unavailable');
      setState(await response.json());
      setReachable(true);
      setError('');
    } catch (requestError) {
      setReachable(false);
      setError(requestError.message || 'Dashboard state unavailable');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  return { state, reachable, loading, error, setError, refresh };
}

function useMetrics(state) {
  const positions = state.positions || [];
  const trades = state.trades || [];
  const curve = state.equity_curve || [];
  const realized = trades.reduce((sum, trade) => sum + Number(trade.realized_pnl || 0), 0);
  const unrealized = positions.reduce((sum, position) => sum + Number(position.unrealized_pnl || 0), 0);
  const exposure = positions.reduce(
    (sum, position) => sum + Math.abs(Number(position.mark_price || 0) * Number(position.quantity || 0)), 0,
  );
  const winners = trades.filter((trade) => Number(trade.realized_pnl) > 0).length;
  const curveChange = curve.length > 1 ? Number(curve.at(-1).equity) - Number(curve[0].equity) : null;
  return {
    positions, trades, curve, realized, unrealized, exposure, curveChange,
    winRate: trades.length ? winners / trades.length : null,
    averageTrade: trades.length ? realized / trades.length : null,
  };
}

function StatusPill({ state, reachable }) {
  const updated = state.updated_at ? Date.now() - new Date(state.updated_at).getTime() : Infinity;
  const stale = updated > 20000;
  const online = reachable && state.status === 'running' && !stale;
  const label = !reachable ? 'Disconnected' : stale ? 'Stale data' : state.paused ? 'Paused' : 'Live';
  return (
    <div className={`status-pill ${online ? 'online' : state.paused && reachable && !stale ? 'paused' : 'offline'}`}>
      <span className="status-dot" />{label}
    </div>
  );
}

function Sidebar({ page, setPage, open, close }) {
  const items = [
    ['overview', 'Overview', LayoutDashboard],
    ['positions', 'Positions', BriefcaseBusiness],
    ['trades', 'Trades', BarChart3],
    ['controls', 'Controls', Settings],
  ];
  return (
    <>
      {open && <button className="scrim" onClick={close} aria-label="Close navigation" />}
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark"><Activity size={18} /></div>
          <div><strong>Swing Control</strong><span>Operator console</span></div>
        </div>
        <nav>
          <div className="nav-label">Workspace</div>
          {items.map(([id, label, Icon]) => (
            <button key={id} className={page === id ? 'active' : ''} onClick={() => { setPage(id); close(); }}>
              <Icon size={17} /><span>{label}</span>{page === id && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot"><Gauge size={15} /><span>5-second strategy telemetry</span></div>
      </aside>
    </>
  );
}

function StatCard({ label, value, detail, icon: Icon, tone = '' }) {
  return (
    <div className={`stat-card ${tone}`}>
      <div className="stat-top"><span>{label}</span><Icon size={17} /></div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function Empty({ children }) {
  return <div className="empty-state"><Activity size={22} /><span>{children}</span></div>;
}

function EquityChart({ curve }) {
  const data = curve.map((point) => ({ ...point, equity: Number(point.equity) }));
  if (data.length < 2) return <Empty>Equity samples will appear as the strategy publishes them.</Empty>;
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 8, left: 0, bottom: 0 }}>
          <defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#3b82f6" stopOpacity={0.3} /><stop offset="1" stopColor="#3b82f6" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid stroke="#242836" vertical={false} />
          <XAxis dataKey="timestamp" tickFormatter={(value) => formatTime(value, { hour: 'numeric', minute: '2-digit' })} stroke="#596175" tickLine={false} axisLine={false} minTickGap={50} />
          <YAxis domain={['auto', 'auto']} tickFormatter={(value) => compactMoney.format(value)} stroke="#596175" tickLine={false} axisLine={false} width={70} />
          <Tooltip contentStyle={{ background: '#171a23', border: '1px solid #2a2f3e', borderRadius: 6 }} labelFormatter={(value) => formatTime(value, { dateStyle: 'medium', timeStyle: 'short' })} formatter={(value) => [money.format(value), 'Equity']} />
          <Area type="monotone" dataKey="equity" stroke="#60a5fa" strokeWidth={2} fill="url(#equityFill)" isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function PageHeading({ title, detail, right }) {
  return <div className="page-heading"><div><h2>{title}</h2><p>{detail}</p></div>{right}</div>;
}

function PositionTable({ positions, onFlatten, compact = false }) {
  if (!positions.length) return <Empty>No open positions.</Empty>;
  return (
    <div className="table-scroll"><table><thead><tr><th>Instrument</th><th>Side</th><th>Quantity</th><th>Average</th><th>Mark</th><th>Exposure</th><th>Unrealized</th><th>Open</th>{!compact && <th />}</tr></thead>
      <tbody>{positions.map((position) => {
        const exposure = Math.abs(Number(position.mark_price) * Number(position.quantity));
        return <tr key={position.position_id}>
          <td><strong className="symbol">{position.instrument_id}</strong></td>
          <td><span className={`side ${position.side === 'LONG' ? 'long' : 'short'}`}>{position.side}</span></td>
          <td>{number.format(position.quantity)}</td><td>{money.format(position.avg_px_open)}</td><td>{money.format(position.mark_price)}</td>
          <td>{money.format(exposure)}</td><td className={valueClass(position.unrealized_pnl)}>{money.format(position.unrealized_pnl)}</td><td>{durationSince(position.opened_at)}</td>
          {!compact && <td><button className="icon-button danger" onClick={() => onFlatten(position.instrument_id)} title={`Flatten ${position.instrument_id}`}><X size={15} /></button></td>}
        </tr>;
      })}</tbody></table></div>
  );
}

function TradeTable({ trades }) {
  if (!trades.length) return <Empty>No closed trades recorded.</Empty>;
  return (
    <div className="table-scroll"><table><thead><tr><th>Closed</th><th>Instrument</th><th>Side</th><th>Quantity</th><th>Entry</th><th>Exit</th><th>Realized P&amp;L</th><th>Held</th></tr></thead>
      <tbody>{trades.map((trade) => <tr key={trade.position_id}><td>{formatTime(trade.closed_at, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</td><td><strong className="symbol">{trade.instrument_id}</strong></td><td><span className={`side ${trade.side === 'LONG' ? 'long' : 'short'}`}>{trade.side}</span></td><td>{number.format(trade.quantity)}</td><td>{money.format(trade.avg_px_open)}</td><td>{money.format(trade.avg_px_close)}</td><td className={valueClass(trade.realized_pnl)}>{money.format(trade.realized_pnl)}</td><td>{durationSince(trade.opened_at).replace(/^/, '')}</td></tr>)}</tbody></table></div>
  );
}

function Overview({ state, metrics, onNavigate }) {
  return <div className="page-stack">
    <PageHeading title="Trading overview" detail="Portfolio health, strategy activity, and broker-reported performance." right={<span className="strategy-tag">PRICE ACCELERATION</span>} />
    <div className="stat-grid">
      <StatCard label="Net liquidation" value={state.equity == null ? '--' : money.format(state.equity)} detail="Broker-reported equity" icon={WalletCards} />
      <StatCard label="Equity change" value={metrics.curveChange == null ? '--' : money.format(metrics.curveChange)} detail="Across retained samples" icon={metrics.curveChange >= 0 ? TrendingUp : TrendingDown} tone={valueClass(metrics.curveChange)} />
      <StatCard label="Unrealized P&L" value={money.format(metrics.unrealized)} detail={`${metrics.positions.length} open position${metrics.positions.length === 1 ? '' : 's'}`} icon={CircleDollarSign} tone={valueClass(metrics.unrealized)} />
      <StatCard label="Gross exposure" value={money.format(metrics.exposure)} detail={state.equity ? `${((metrics.exposure / state.equity) * 100).toFixed(1)}% of equity` : 'No equity reference'} icon={Gauge} />
    </div>
    <section className="panel chart-panel"><div className="panel-header"><div><h3>Equity curve</h3><span>{metrics.curve.length.toLocaleString()} retained samples</span></div><button className="text-button" onClick={() => onNavigate('trades')}>Trade history <ChevronRight size={14} /></button></div><EquityChart curve={metrics.curve} /></section>
    <div className="two-column">
      <section className="panel"><div className="panel-header"><div><h3>Open positions</h3><span>Live broker marks</span></div><button className="text-button" onClick={() => onNavigate('positions')}>View all <ChevronRight size={14} /></button></div><PositionTable positions={metrics.positions.slice(0, 5)} compact /></section>
      <section className="panel activity-panel"><div className="panel-header"><div><h3>Control activity</h3><span>Last acknowledged command</span></div></div>{state.last_command ? <div className="command-card"><div className="command-icon"><Activity size={18} /></div><div><strong>{state.last_command.action.replaceAll('_', ' ')}</strong><p>{state.last_command.result}</p><time>{formatTime(state.last_command.processed_at, { dateStyle: 'medium', timeStyle: 'short' })}</time></div></div> : <Empty>No operator commands processed.</Empty>}</section>
    </div>
  </div>;
}

function PositionsPage({ metrics, onFlatten }) {
  return <div className="page-stack"><PageHeading title="Open positions" detail="Broker marks, exposure, holding time, and direct position controls." />
    <div className="stat-grid small"><StatCard label="Positions" value={metrics.positions.length} detail="Currently open" icon={BriefcaseBusiness} /><StatCard label="Gross exposure" value={money.format(metrics.exposure)} detail="Absolute notional" icon={Gauge} /><StatCard label="Unrealized P&L" value={money.format(metrics.unrealized)} detail="Across open positions" icon={CircleDollarSign} tone={valueClass(metrics.unrealized)} /></div>
    <section className="panel"><div className="panel-header"><div><h3>Position book</h3><span>Marks refresh every five seconds</span></div></div><PositionTable positions={metrics.positions} onFlatten={onFlatten} /></section>
  </div>;
}

function TradesPage({ metrics }) {
  return <div className="page-stack"><PageHeading title="Trade history" detail="Closed positions and realized strategy performance." />
    <div className="stat-grid small"><StatCard label="Realized P&L" value={money.format(metrics.realized)} detail={`${metrics.trades.length} closed trades`} icon={CircleDollarSign} tone={valueClass(metrics.realized)} /><StatCard label="Win rate" value={metrics.winRate == null ? '--' : `${(metrics.winRate * 100).toFixed(1)}%`} detail="Profitable closes" icon={TrendingUp} /><StatCard label="Average trade" value={metrics.averageTrade == null ? '--' : money.format(metrics.averageTrade)} detail="Realized P&L per trade" icon={BarChart3} tone={valueClass(metrics.averageTrade)} /></div>
    <section className="panel"><div className="panel-header"><div><h3>Closed positions</h3><span>Newest first</span></div></div><TradeTable trades={metrics.trades} /></section>
  </div>;
}

function ConfirmDialog({ confirm, close, execute, busy }) {
  if (!confirm) return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}><div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div className="dialog-icon"><ShieldAlert size={22} /></div><h3 id="dialog-title">{confirm.title}</h3><p>{confirm.message}</p><div className="dialog-actions"><button className="button secondary" onClick={close}>Cancel</button><button className="button danger" disabled={busy} onClick={execute}>{busy ? <RefreshCw className="spin" size={16} /> : <ShieldAlert size={16} />}{confirm.label}</button></div></div></div>;
}

function ControlsPage({ state, reachable, metrics, requestConfirm }) {
  return <div className="page-stack"><PageHeading title="Strategy controls" detail="Operator interventions are queued and acknowledged by the running strategy." />
    <div className="control-grid"><section className="panel control-card"><div className="control-icon pause"><Pause size={20} /></div><div><h3>{state.paused ? 'Entries paused' : 'Pause new entries'}</h3><p>Stops new strategy entries. Existing positions and protective exits remain active.</p></div><button className={`button ${state.paused ? 'primary' : 'warning'}`} disabled={!reachable} onClick={() => requestConfirm({ title: state.paused ? 'Resume entries' : 'Pause entries', message: state.paused ? 'Allow the strategy to evaluate and submit new entries again.' : 'Prevent all new strategy entries while preserving open-position management.', label: state.paused ? 'Resume entries' : 'Pause entries', endpoint: '/api/pause', payload: { paused: !state.paused } })}>{state.paused ? <Play size={16} /> : <Pause size={16} />}{state.paused ? 'Resume' : 'Pause'}</button></section>
      <section className="panel control-card critical"><div className="control-icon danger"><ShieldAlert size={20} /></div><div><h3>Flatten portfolio</h3><p>Pauses entries, cancels working strategy orders, and submits reduce-only exits.</p></div><button className="button danger" disabled={!reachable || !metrics.positions.length} onClick={() => requestConfirm({ title: 'Flatten every position', message: `Submit flatten orders for ${metrics.positions.length} open position${metrics.positions.length === 1 ? '' : 's'}. This cannot be undone.`, label: 'Flatten all', endpoint: '/api/flatten', payload: {} })}><X size={16} />Flatten all</button></section></div>
    <section className="panel"><div className="panel-header"><div><h3>System detail</h3><span>Current strategy publication</span></div></div><dl className="detail-grid"><div><dt>Strategy status</dt><dd>{state.status || 'Unknown'}</dd></div><div><dt>Entry state</dt><dd>{state.paused ? 'Paused' : 'Enabled'}</dd></div><div><dt>Last publication</dt><dd>{formatTime(state.updated_at, { dateStyle: 'medium', timeStyle: 'medium' })}</dd></div><div><dt>Refresh cadence</dt><dd>5 seconds</dd></div><div><dt>Open positions</dt><dd>{metrics.positions.length}</dd></div><div><dt>Closed trades</dt><dd>{metrics.trades.length}</dd></div></dl></section>
    <section className="panel"><div className="panel-header"><div><h3>Position controls</h3><span>Target a single instrument</span></div></div><PositionTable positions={metrics.positions} onFlatten={(instrument) => requestConfirm({ title: `Flatten ${instrument}`, message: `Pause new entries and submit a reduce-only exit for ${instrument}.`, label: `Flatten ${instrument}`, endpoint: '/api/flatten', payload: { instrument_id: instrument } })} /></section>
  </div>;
}

export function App() {
  const [page, setPage] = useState('overview');
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const { state, reachable, loading, error, setError, refresh } = useDashboardState();
  const metrics = useMetrics(state);

  async function executeCommand() {
    if (!confirm) return;
    setBusy(true);
    try {
      const response = await fetch(confirm.endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(confirm.payload) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Command failed');
      setConfirm(null);
      await refresh();
    } catch (commandError) {
      setError(commandError.message || 'Command failed');
      setConfirm(null);
    } finally { setBusy(false); }
  }

  function requestFlatten(instrument) {
    setConfirm({ title: `Flatten ${instrument}`, message: `Pause new entries and submit a reduce-only exit for ${instrument}.`, label: `Flatten ${instrument}`, endpoint: '/api/flatten', payload: { instrument_id: instrument } });
  }

  const pages = {
    overview: <Overview state={state} metrics={metrics} onNavigate={setPage} />,
    positions: <PositionsPage metrics={metrics} onFlatten={requestFlatten} />,
    trades: <TradesPage metrics={metrics} />,
    controls: <ControlsPage state={state} reachable={reachable} metrics={metrics} requestConfirm={setConfirm} />,
  };

  return <div className="app-shell"><Sidebar page={page} setPage={setPage} open={menuOpen} close={() => setMenuOpen(false)} /><main className="main"><header className="topbar"><div className="topbar-left"><button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button><div><h1>Price Acceleration</h1><span>Paper trading · Interactive Brokers</span></div></div><div className="topbar-right"><div className="updated"><Clock3 size={14} />{state.updated_at ? formatTime(state.updated_at, { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : 'Awaiting state'}</div><StatusPill state={state} reachable={reachable} /></div></header><div className="content">{error && <div className="error-banner"><ShieldAlert size={17} /><span>{error}</span><button onClick={() => setError('')}><X size={16} /></button></div>}{loading ? <div className="loading"><RefreshCw className="spin" size={22} />Loading operator state</div> : pages[page]}</div></main><ConfirmDialog confirm={confirm} close={() => setConfirm(null)} execute={executeCommand} busy={busy} /></div>;
}