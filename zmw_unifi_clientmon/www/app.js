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

  formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  render() {
    if (!this.state.clients || !this.state.events || !this.state.presence || !this.state.allDevices) {
      return ( <div className="app-loading">Loading...</div> );
    }

    const presenceEntries = Object.entries(this.state.presence);
    const unknownDevices = this.state.allDevices.filter(d => !d.known);
    const knownDevices = this.state.allDevices.filter(d => d.known);

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

        {unknownDevices.length > 0 && (
          <div>
            <h3 style={{ color: '#ff6b6b' }}>Unknown Devices</h3>
            <table>
              <thead>
                <tr><th>Hostname</th><th>MAC</th><th>IP</th><th>Status</th></tr>
              </thead>
              <tbody>
                {unknownDevices.map((d, idx) => (
                  <tr key={idx}>
                    <td>{d.hostname}</td>
                    <td>{d.mac}</td>
                    <td>{d.ip || '-'}</td>
                    <td>
                      <span style={{ color: d.online ? '#4caf50' : '#888', fontWeight: 'bold' }}>
                        {d.online ? 'ONLINE' : 'OFFLINE'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h3>All Devices</h3>
        <table>
          <thead>
            <tr><th>Hostname</th><th>MAC</th><th>IP</th><th>Status</th><th>Known</th></tr>
          </thead>
          <tbody>
            {knownDevices.map((d, idx) => (
              <tr key={idx}>
                <td>{d.hostname}</td>
                <td>{d.mac}</td>
                <td>{d.ip || '-'}</td>
                <td>
                  <span style={{ color: d.online ? '#4caf50' : '#888', fontWeight: 'bold' }}>
                    {d.online ? 'ONLINE' : 'OFFLINE'}
                  </span>
                </td>
                <td>
                  <span style={{ color: '#4caf50' }}>YES</span>
                </td>
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
