class ZmwSucks extends React.Component {
  static buildProps(api_base_path = '') {
    return {
      key: 'ZmwSucks',
      api_base_path,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      robots: null,
    };
    this.fetchState = this.fetchState.bind(this);
    this.refreshInterval = null;
  }

  componentDidMount() {
    this.fetchState();
    this.refreshInterval = setInterval(this.fetchState, 5000);
  }

  componentWillUnmount() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
    }
  }

  on_app_became_visible() {
    this.fetchState();
  }

  fetchState() {
    mJsonGet(`${this.props.api_base_path}/get_state`, (res) => {
      this.setState({ robots: res });
    });
  }

  sendCommand(cmd, alias) {
    mJsonPut(`${this.props.api_base_path}/${cmd}/${encodeURIComponent(alias)}`, {}, () => this.fetchState());
  }

  formatArea(sqft) {
    if (sqft === null || sqft === undefined) {
      return '?';
    }
    return `${(sqft * 0.0929).toFixed(1)} m²`;
  }

  formatInitiator(initiator) {
    const known = {
      localApp: 'ZMW',
      rmtApp: 'iRobot app',
      schedule: 'schedule',
      manual: 'button',
    };
    return known[initiator] || initiator || '?';
  }

  formatWifi(wifi) {
    if (wifi.rssi === null || wifi.rssi === undefined) {
      return '?';
    }
    const quality = wifi.rssi > -60 ? 'good' : (wifi.rssi > -70 ? 'ok' : 'weak');
    const snr = (wifi.snr === null || wifi.snr === undefined) ? '' : `, SNR ${wifi.snr} dB`;
    return `${quality} (${wifi.rssi} dBm${snr})`;
  }

  formatPosition(r) {
    if (r.position_supported === false) {
      return 'not supported by this robot';
    }
    if (!r.position) {
      return r.position_supported === null ? 'unknown (only checked away from the dock)' : 'no fix';
    }
    const p = r.position;
    const heading = Math.round(p.theta_rad * 180 / Math.PI);
    return `${p.x_m.toFixed(2)} m, ${p.y_m.toFixed(2)} m from dock, heading ${heading}°`;
  }

  renderMission(m) {
    if (!m.cycle || m.cycle === 'none') {
      return (<tr><td>Mission</td><td>none</td></tr>);
    }
    const started = m.start_time ? new Date(m.start_time * 1000).toLocaleTimeString() : '?';
    return (<>
      <tr><td>Mission</td><td>{m.cycle}, started {started} by {this.formatInitiator(m.initiator)}</td></tr>
      <tr><td>Duration</td><td>{m.minutes ?? '?'} min</td></tr>
      <tr><td>Cleaned</td><td>{this.formatArea(m.sqft)}</td></tr>
      {m.recharge_minutes > 0 && (<tr><td>Recharging</td><td>{m.recharge_minutes} min left</td></tr>)}
      {m.expire_minutes > 0 && (<tr><td>Expires</td><td>in {m.expire_minutes} min, if not resumed</td></tr>)}
    </>);
  }

  formatPct(part, total) {
    if (!total || part === null || part === undefined) {
      return '';
    }
    return ` (${Math.round(100 * part / total)}%)`;
  }

  renderLifetime(l, b) {
    const runtime = (l.runtime_hours === null || l.runtime_hours === undefined)
      ? '?' : `${l.runtime_hours} h ${l.runtime_minutes ?? 0} min`;
    return (
      <details>
        <summary>Lifetime stats</summary>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Runtime</td><td>{runtime}</td></tr>
            <tr><td>Area cleaned</td><td>{this.formatArea(l.sqft)}</td></tr>
            <tr><td>Missions</td><td>{l.missions ?? '?'}</td></tr>
            <tr><td>Completed</td><td>{l.missions_ok ?? '?'}{this.formatPct(l.missions_ok, l.missions)}</td></tr>
            <tr><td>Failed</td><td>{l.missions_failed ?? '?'}{this.formatPct(l.missions_failed, l.missions)}</td></tr>
            <tr><td>Cancelled</td><td>{l.missions_cancelled ?? '?'}{this.formatPct(l.missions_cancelled, l.missions)}</td></tr>
            <tr><td>Average mission</td><td>{l.avg_mission_minutes ?? '?'} min</td></tr>
            <tr><td>Got stuck</td><td>{l.stuck_count ?? '?'} times</td></tr>
            <tr><td>Battery cycles</td><td>{b.charge_cycles ?? '?'}</td></tr>
            <tr><td>Battery capacity</td><td>{b.est_capacity_mah ?? '?'} mAh (estimated)</td></tr>
            <tr><td>Battery made</td><td>{b.manufacture_date || '?'}</td></tr>
          </tbody>
        </table>
      </details>
    );
  }

  setSetting(alias, setting, value) {
    const url = `${this.props.api_base_path}/set_setting/${encodeURIComponent(alias)}/${setting}/${value}`;
    // The robot takes a moment to report the new value
    mJsonPut(url, {}, () => setTimeout(this.fetchState, 1500));
  }

  renderSettings(r) {
    const s = r.settings;
    return (
      <details>
        <summary>Settings</summary>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Passes</td><td>
              <select value={s.passes} onChange={(e) => this.setSetting(r.alias, 'passes', e.target.value)}>
                <option value="auto">Auto</option>
                <option value="one">One</option>
                <option value="two">Two</option>
              </select>
            </td></tr>
            <tr><td>Pause when bin full</td><td>
              <input type="checkbox" checked={s.bin_pause}
                     onChange={(e) => this.setSetting(r.alias, 'bin_pause', e.target.checked)} />
            </td></tr>
            <tr><td>Child lock</td><td>
              <input type="checkbox" checked={s.child_lock}
                     onChange={(e) => this.setSetting(r.alias, 'child_lock', e.target.checked)} />
            </td></tr>
          </tbody>
        </table>
      </details>
    );
  }

  renderSchedule(sch) {
    if (!sch.entries || sch.entries.length === 0) {
      return (<p><small>No schedule set on the robot</small></p>);
    }
    const pad = (n) => String(n ?? 0).padStart(2, '0');
    return (
      <details>
        <summary>Schedule{sch.paused ? ' (on hold)' : ''}</summary>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <thead><tr><th>Days</th><th>Time</th><th>Active</th></tr></thead>
          <tbody>
            {sch.entries.map((e, i) => (
              <tr key={i}>
                <td>{e.days.join(', ')}</td>
                <td>{pad(e.hour)}:{pad(e.min)}{e.command && e.command !== 'start' ? ` (${e.command})` : ''}</td>
                <td>{e.enabled && !sch.paused ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sch.timezone && (<p><small>Times in the robot's timezone, {sch.timezone}</small></p>)}
      </details>
    );
  }

  renderRobot(r) {
    if (!r.connected) {
      return (
        <div key={r.alias} className="card warn">
          <p><b>{r.alias}</b>: not connected</p>
        </div>
      );
    }

    const rawStateUrl = `${this.props.api_base_path}/get_raw_state/${encodeURIComponent(r.alias)}`;
    return (
      <div key={r.alias} className="card hint">
        <p><b>{r.alias}</b>: {r.state || '?'}</p>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Battery</td><td>{r.battery_pct ?? '?'}%</td></tr>
            <tr><td>Phase</td><td>{r.phase || '?'}</td></tr>
            <tr><td>Bin</td><td>{r.bin_full ? <span className="warn">full</span> : 'ok'}</td></tr>
            {r.error && (<tr><td>Error</td><td className="warn">{r.error}</td></tr>)}
            {this.renderMission(r.mission)}
            <tr><td>Position</td><td>{this.formatPosition(r)}</td></tr>
            <tr><td>Wi-Fi</td><td>{this.formatWifi(r.wifi)}</td></tr>
            <tr><td>IP</td><td>{r.ip}</td></tr>
          </tbody>
        </table>
        {this.renderSchedule(r.schedule)}
        {this.renderSettings(r)}
        {this.renderLifetime(r.lifetime, r.battery)}
        <button onClick={() => this.sendCommand('start', r.alias)}>Start</button>
        <button onClick={() => this.sendCommand('pause', r.alias)}>Pause</button>
        <button onClick={() => this.sendCommand('dock', r.alias)}>Dock</button>
        <button onClick={() => this.sendCommand('find', r.alias)}>Find</button>
        <p><small><a href={rawStateUrl} target="_blank" rel="noreferrer">Raw state (debug)</a></small></p>
      </div>
    );
  }

  render() {
    if (!this.state.robots) {
      return (<div className="app-loading">Loading...</div>);
    }

    const robots = Object.values(this.state.robots);
    if (robots.length === 0) {
      return (<p>No robots configured</p>);
    }
    return (<div>{robots.map((r) => this.renderRobot(r))}</div>);
  }
}
