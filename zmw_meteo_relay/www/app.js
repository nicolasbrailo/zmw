class MeteoRelay extends React.Component {
  static buildProps() {
    return {
      key: 'MeteoRelay',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      status: null,
    };
    this.fetchStatus = this.fetchStatus.bind(this);
  }

  async componentDidMount() {
    this.fetchStatus();
  }

  on_app_became_visible() {
    this.fetchStatus();
  }

  fetchStatus() {
    mJsonGet('/status', (res) => {
      this.setState({ status: res });
    });
  }

  renderCurrent(weather) {
    const cur = weather && weather.current;
    if (!cur) {
      return <em style={{ color: '#888' }}>(no current conditions)</em>;
    }
    const units = weather.current_units || {};
    return (
      <span>
        {Object.keys(cur).filter((k) => k !== 'time' && k !== 'interval').map((k) => (
          <span key={k} style={{ marginRight: '12px' }}>
            {k}: <b>{cur[k]}{units[k] ? ` ${units[k]}` : ''}</b>
          </span>
        ))}
        <span style={{ color: '#888' }}>(at {cur.time})</span>
      </span>
    );
  }

  renderLocation(loc) {
    return (
      <li key={loc.id}>
        <div style={{ marginBottom: '5px' }}>
          <span style={{ color: '#4a90e2', fontWeight: 'bold' }}>
            #{loc.id} {loc.lat.toFixed(4)}, {loc.lon.toFixed(4)}
          </span>
          {loc.is_default && <span style={{ marginLeft: '10px' }}>(default)</span>}
          <span style={{ color: '#888', fontSize: '0.9em', marginLeft: '10px' }}>
            {loc.request_count} requests, last {loc.last_requested_at || 'never'}
          </span>
        </div>
        <div style={{ marginLeft: '20px', fontSize: '0.95em' }}>
          <div>Fetched: {loc.fetched_at || 'never'}</div>
          {loc.last_error && (
            <div style={{ color: '#e24a4a' }}>
              Last error: {loc.last_error}
              {loc.next_retry_at ? ` (retry #${loc.retry_count} at ${loc.next_retry_at})` : ' (waiting for next periodic update)'}
            </div>
          )}
          <div>{this.renderCurrent(loc.weather)}</div>
          {loc.weather && (
            <details>
              <summary>Full report</summary>
              <pre style={{ fontSize: '0.8em', overflowX: 'auto' }}>{JSON.stringify(loc.weather, null, 2)}</pre>
            </details>
          )}
        </div>
      </li>
    );
  }

  renderClients(clients) {
    if (clients.length === 0) {
      return <p>No requests yet</p>;
    }
    return (
      <ul>
        {clients.map((c) => (
          <li key={`${c.transport}/${c.client}`}>
            <span style={{ color: '#4a90e2', fontWeight: 'bold' }}>{c.client}</span>
            <span style={{ marginLeft: '10px' }}>[{c.transport}]</span>
            <span style={{ color: '#888', fontSize: '0.9em', marginLeft: '10px' }}>
              {c.request_count} requests, last {c.last_seen_at}, location #{c.last_location_id}
              {c.user_agent ? ` - ${c.user_agent}` : ''}
            </span>
          </li>
        ))}
      </ul>
    );
  }

  render() {
    if (!this.state.status) {
      return ( <div className="app-loading">Loading...</div> );
    }

    const st = this.state.status;
    return (
      <div id="MeteoRelayContainer">
        <h3>
          <img src="/favicon.ico" alt="Meteo relay service" />
          Known locations
        </h3>
        <p style={{ color: '#888' }}>Refreshed every {st.update_interval_minutes} minutes</p>
        <ul>
          {st.known_locations.map((loc) => this.renderLocation(loc))}
        </ul>

        <h3>Recent clients</h3>
        {this.renderClients(st.known_clients)}
      </div>
    )
  }
}

z2mStartReactApp('#app_root', MeteoRelay);
