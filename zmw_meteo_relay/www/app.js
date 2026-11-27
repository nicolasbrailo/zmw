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
      return <em className="text-secondary">(no current conditions)</em>;
    }
    const units = weather.current_units || {};
    return (
      <span className="row-wrap">
        {Object.keys(cur).filter((k) => k !== 'time' && k !== 'interval').map((k) => (
          <span key={k}>
            {k}: <b>{cur[k]}{units[k] ? ` ${units[k]}` : ''}</b>
          </span>
        ))}
        <span className="text-secondary">(at {cur.time})</span>
      </span>
    );
  }

  renderLocation(loc) {
    return (
      <li key={loc.id}>
        <div className="entry-head">
          <span className="entry-title">
            #{loc.id} {loc.lat.toFixed(4)}, {loc.lon.toFixed(4)}
          </span>
          {loc.is_default && <span>(default)</span>}
          <span className="entry-meta">
            {loc.request_count} requests, last {loc.last_requested_at || 'never'}
          </span>
        </div>
        <div className="entry-body">
          <div>Fetched: {loc.fetched_at || 'never'}</div>
          {loc.last_error && (
            <div className="text-error">
              Last error: {loc.last_error}
              {loc.next_retry_at ? ` (retry #${loc.retry_count} at ${loc.next_retry_at})` : ' (waiting for next periodic update)'}
            </div>
          )}
          <div>{this.renderCurrent(loc.weather)}</div>
          {loc.weather && (
            <details>
              <summary>Full report</summary>
              <pre>{JSON.stringify(loc.weather, null, 2)}</pre>
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
          <li key={`${c.transport}/${c.client}`} className="entry-head">
            <span className="entry-title">{c.client}</span>
            <span>[{c.transport}]</span>
            <span className="entry-meta">
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
        <p className="text-secondary">Refreshed every {st.update_interval_minutes} minutes</p>
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
