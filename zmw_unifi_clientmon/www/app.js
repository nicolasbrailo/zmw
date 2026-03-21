class UnifiClientmon extends React.Component {
  static buildProps() {
    return {
      key: 'UnifiClientmon',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      clients: null,
      events: null,
      presence: null,
      allDevices: null,
      editingAlias: null, // mac of device being edited
      aliasInput: '',
    };
    this.fetchData = this.fetchData.bind(this);
  }

  async componentDidMount() {
    this.fetchData();
  }

  on_app_became_visible() {
    this.fetchData();
  }

  fetchData() {
    mJsonGet('/clients', (res) => {
      this.setState({ clients: res });
    });
    mJsonGet('/events', (res) => {
      this.setState({ events: res });
    });
    mJsonGet('/presence', (res) => {
      this.setState({ presence: res });
    });
    mJsonGet('/all_devices', (res) => {
      this.setState({ allDevices: res });
    });
  }

  setTrusted(mac, trusted) {
    fetch('/device_trust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac, trusted }),
    }).then(() => this.fetchData());
  }

  startEditAlias(mac, currentAlias) {
    this.setState({ editingAlias: mac, aliasInput: currentAlias || '' });
  }

  saveAlias(mac) {
    fetch('/device_alias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac, alias: this.state.aliasInput }),
    }).then(() => {
      this.setState({ editingAlias: null, aliasInput: '' });
      this.fetchData();
    });
  }

  cancelEditAlias() {
    this.setState({ editingAlias: null, aliasInput: '' });
  }

  formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  renderDeviceName(d) {
    if (d.alias) {
      return <span>{d.alias} <span style={{ color: '#888', fontSize: '0.85em' }}>({d.hostname})</span></span>;
    }
    return d.hostname;
  }

  renderAliasCell(d) {
    if (this.state.editingAlias === d.mac) {
      return (
        <td>
          <input
            type="text"
            value={this.state.aliasInput}
            onChange={(e) => this.setState({ aliasInput: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Enter') this.saveAlias(d.mac);
              if (e.key === 'Escape') this.cancelEditAlias();
            }}
            style={{ width: '8em' }}
            autoFocus
          />
          <button onClick={() => this.saveAlias(d.mac)}>Save</button>
          <button onClick={() => this.cancelEditAlias()}>Cancel</button>
        </td>
      );
    }
    return (
      <td>
        <span
          onClick={() => this.startEditAlias(d.mac, d.alias)}
          style={{ cursor: 'pointer', textDecoration: 'underline dotted', color: '#aaa' }}
          title="Click to edit alias"
        >
          {d.alias || '-'}
        </span>
      </td>
    );
  }

  renderTrustCell(d) {
    return (
      <td>
        <span
          onClick={() => this.setTrusted(d.mac, !d.trusted)}
          style={{
            cursor: 'pointer',
            color: d.trusted ? '#4caf50' : '#ff6b6b',
            fontWeight: 'bold',
          }}
          title={d.trusted ? 'Click to mark untrusted' : 'Click to mark trusted'}
        >
          {d.trusted ? 'TRUSTED' : 'UNTRUSTED'}
        </span>
      </td>
    );
  }

  render() {
    if (!this.state.clients || !this.state.events || !this.state.presence || !this.state.allDevices) {
      return ( <div className="app-loading">Loading...</div> );
    }

    const presenceEntries = Object.entries(this.state.presence);
    const untrustedDevices = this.state.allDevices.filter(d => !d.trusted);
    const trustedDevices = this.state.allDevices.filter(d => d.trusted);

    return (
      <div id="UnifiClientmonContainer">
        <h3>User Presence</h3>
        {presenceEntries.length === 0 ? (
          <p>No presence data yet</p>
        ) : (
          <ul>
            {presenceEntries.map(([user, isHome]) => (
              <li key={user}>
                <span style={{ color: isHome ? '#4caf50' : '#ff6b6b', fontWeight: 'bold' }}>
                  {isHome ? 'HOME' : 'AWAY'}
                </span>
                {' '}{user}
              </li>
            ))}
          </ul>
        )}

        {untrustedDevices.length > 0 && (
          <div>
            <h3 style={{ color: '#ff6b6b' }}>Untrusted Devices</h3>
            <table>
              <thead>
                <tr><th>Name</th><th>MAC</th><th>IP</th><th>Status</th><th>Trust</th><th>Alias</th></tr>
              </thead>
              <tbody>
                {untrustedDevices.map((d) => (
                  <tr key={d.mac}>
                    <td>{this.renderDeviceName(d)}</td>
                    <td>{d.mac}</td>
                    <td>{d.ip || '-'}</td>
                    <td>
                      <span style={{ color: d.online ? '#4caf50' : '#888', fontWeight: 'bold' }}>
                        {d.online ? 'ONLINE' : 'OFFLINE'}
                      </span>
                    </td>
                    {this.renderTrustCell(d)}
                    {this.renderAliasCell(d)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h3>All Devices</h3>
        <table>
          <thead>
            <tr><th>Name</th><th>MAC</th><th>IP</th><th>Status</th><th>Trust</th><th>Alias</th></tr>
          </thead>
          <tbody>
            {trustedDevices.map((d) => (
              <tr key={d.mac}>
                <td>{this.renderDeviceName(d)}</td>
                <td>{d.mac}</td>
                <td>{d.ip || '-'}</td>
                <td>
                  <span style={{ color: d.online ? '#4caf50' : '#888', fontWeight: 'bold' }}>
                    {d.online ? 'ONLINE' : 'OFFLINE'}
                  </span>
                </td>
                {this.renderTrustCell(d)}
                {this.renderAliasCell(d)}
              </tr>
            ))}
          </tbody>
        </table>

        <h3>Event History</h3>
        {this.state.events.length === 0 ? (
          <p>No events yet</p>
        ) : (
          <ul>
            {[...this.state.events].reverse().map((ev, idx) => (
              <li key={idx}>
                <span style={{ color: ev.event === 'joined' ? '#4caf50' : '#ff6b6b', fontWeight: 'bold' }}>
                  {ev.event.toUpperCase()}
                </span>
                {' '}
                <span>{ev.hostname} ({ev.mac}) {ev.ip}</span>
                {' '}
                <span style={{ color: '#888', fontSize: '0.9em' }}>
                  {this.formatTimestamp(ev.time)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
}

z2mStartReactApp('#app_root', UnifiClientmon);
