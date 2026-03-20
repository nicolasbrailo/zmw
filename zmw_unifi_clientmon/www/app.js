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
  }

  formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  render() {
    if (!this.state.clients || !this.state.events || !this.state.presence) {
      return ( <div className="app-loading">Loading...</div> );
    }

    const presenceEntries = Object.entries(this.state.presence);

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

        <h3>Connected Interesting Devices</h3>
        {this.state.clients.length === 0 ? (
          <p>No interesting devices connected</p>
        ) : (
          <table>
            <thead>
              <tr><th>Hostname</th><th>MAC</th><th>IP</th></tr>
            </thead>
            <tbody>
              {this.state.clients.map((c, idx) => (
                <tr key={idx}>
                  <td>{c.hostname}</td>
                  <td>{c.mac}</td>
                  <td>{c.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

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
