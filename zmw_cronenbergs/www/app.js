class CronenbergMon extends React.Component {
  static buildProps() {
    return {
      key: 'CronenbergMon',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      stats: null,
    };
    this.fetchStats = this.fetchStats.bind(this);
  }

  async componentDidMount() {
    this.fetchStats();
  }

  on_app_became_visible() {
    this.fetchStats();
  }

  fetchStats() {
    mJsonGet('/stats', (res) => {
      this.setState({ stats: res });
    });
  }

  formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString();
  }

  formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  calculateSummary() {
    const history = this.state.stats?.light_check_history;
    if (!history || history.length === 0) {
      return { forgotten: 0, clean: 0 };
    }

    const forgotten = history.filter(s => s.lights_forgotten).length;
    const clean = history.filter(s => !s.lights_forgotten).length;

    return { forgotten, clean };
  }

  renderBatterySection() {
    const batteryThings = this.state.stats.battery_things || [];

    if (batteryThings.length === 0) {
      return null;
    }

    const critical = batteryThings.filter(t => t.battery !== null && t.battery < 15);
    const low = batteryThings.filter(t => t.battery !== null && t.battery >= 15 && t.battery < 30);
    const ok = batteryThings.filter(t => t.battery !== null && t.battery >= 30);
    const unknown = batteryThings.filter(t => t.battery === null);

    return (
      <div className="battery-section">
        <h4>Battery Levels</h4>
        <ul className="battery-list">
          {critical.map((thing, idx) => (
            <li key={`critical-${idx}`} className="battery-item battery-critical">
              <span className="battery-name">{thing.name}</span>
              <span className="battery-level">{thing.battery}%</span>
            </li>
          ))}
          {low.map((thing, idx) => (
            <li key={`low-${idx}`} className="battery-item battery-low">
              <span className="battery-name">{thing.name}</span>
              <span className="battery-level">{thing.battery}%</span>
            </li>
          ))}
          {ok.map((thing, idx) => (
            <li key={`ok-${idx}`} className="battery-item battery-ok">
              <span className="battery-name">{thing.name}</span>
              <span className="battery-level">{thing.battery}%</span>
            </li>
          ))}
          {unknown.map((thing, idx) => (
            <li key={`unknown-${idx}`} className="battery-item battery-unknown">
              <span className="battery-name">{thing.name}</span>
              <span className="battery-level">?</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  render() {
    if (!this.state.stats) {
      return ( <div className="app-loading">Loading...</div> );
    }

    const summary = this.calculateSummary();
    const history = this.state.stats.light_check_history;
    const vacationsMode = this.state.stats.vacations_mode;
    const speakerAnnounce = this.state.stats.speaker_announce || [];

    return (
      <div id="CronenbergMonitorContainer">
        <div className={vacationsMode ? "card warn" : "card hint"}>
          <strong>Vacations Mode:</strong> {vacationsMode ? "Enabled" : "Disabled"}
          {vacationsMode && <p>Random light effects are active to simulate presence.</p>}
        </div>

        {this.renderBatterySection()}

        {speakerAnnounce.length > 0 && (
          <div className="announcements-section">
            <h4>Scheduled Announcements</h4>
            <ul className="announcements-list">
              {speakerAnnounce.map((announce, idx) => (
                <li key={idx} className="announcement-item">
                  <span className="announcement-time">{announce.time}</span>
                  <span className="announcement-msg">{announce.msg}</span>
                  <span className="announcement-meta">({announce.lang}, vol: {announce.vol})</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {history.length === 0 ? (
          <p>No light checks recorded yet</p>
        ) : (
          <div>
            <div className="summary-section">
              <h4>Summary</h4>
              <div className="summary-stats">
                <div className="summary-stat">
                  <span className="summary-value forgotten">{summary.forgotten}</span>
                  <div className="summary-label">Days with lights forgotten</div>
                </div>
                <div className="summary-stat">
                  <span className="summary-value clean">{summary.clean}</span>
                  <div className="summary-label">Days with no lights on</div>
                </div>
                <div className="summary-stat">
                  <span className="summary-value total">{history.length}</span>
                  <div className="summary-label">Total checks (last 10 days)</div>
                </div>
              </div>
            </div>

            <h4>Recent Checks</h4>
            <ul className="checks-list">
              {history.slice().reverse().map((check, idx) => this.renderCheck(check, idx))}
            </ul>
          </div>
        )}
      </div>
    )
  }

  renderCheck(check, idx) {
    const statusClass = check.lights_forgotten ? 'forgotten' : 'clear';
    const statusIcon = check.lights_forgotten ? '⚠️' : '✓';
    const statusText = check.lights_forgotten ? 'Lights forgotten' : 'All clear';

    return (
      <li key={idx} className={`check-item ${statusClass}`}>
        <div className="check-header">
          <div className="check-status">
            <span className="check-icon">{statusIcon}</span>
            <span className="check-text">{statusText}</span>
          </div>
          <div className="check-date">
            {this.formatDate(check.date)} at {new Date(check.timestamp).toLocaleTimeString()}
          </div>
        </div>
        {check.lights_forgotten && check.lights_left_on && check.lights_left_on.length > 0 && (
          <div className="check-details">
            <strong>Lights left on:</strong> {check.lights_left_on.join(', ')}
          </div>
        )}
      </li>
    );
  }
}

z2mStartReactApp('#app_root', CronenbergMon);
